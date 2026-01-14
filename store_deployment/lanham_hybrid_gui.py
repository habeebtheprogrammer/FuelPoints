#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - LANHAM HYBRID GUI
===============================================
GUI wrapper for the Lanham Verifone EPS Hybrid Edge Agent.
Based on: working_edgecodes/lanhamverifoneworkingpunchanddiscount.py

Features:
  - Setup wizard for IP, Port, PDI Store Number
  - Real-time status dashboard
  - System tray support
  - Raw interaction logging to text file
  - PROMOTIONS (2-for-$X, buy X get Y free, amount off)
  - PUNCH CARDS (free item, % off, $ off)
  - POINTS REDEMPTION (10,000 pts = $1.00)

Stacking Policy:
  - Promos are applied first
  - If promos apply, loyalty discounts (punch/points) are disabled
  - Points earning still occurs unless DISABLE_EARNING_WHEN_PROMO=True

EPS / PCATS REQUIREMENTS:
  - TCP framing: 4-byte BIG-ENDIAN length prefix + UTF-8 XML payload
  - ResponseHeader overallResult="success" on success
  - RewardDiscountMethod: amountOff ONLY
  - PCATS namespaces required

Build EXE on Windows with:
  pip install pyside6 requests pyinstaller
  pyinstaller --onefile --windowed --name "Birdies Lanham Hybrid" --collect-all PySide6 lanham_hybrid_gui.py

Version: 1.0 (based on lanhamverifoneworkingpunchanddiscount.py)
"""

import sys
import os
import json
import socket
import threading
import datetime
import struct
import uuid
import time
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QGroupBox, QFormLayout,
    QWizard, QWizardPage, QMessageBox, QSystemTrayIcon, QMenu, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont, QAction

# =============================================================================
# CONFIG & LOG FILE PATHS
# =============================================================================

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_config_path():
    return os.path.join(get_app_dir(), "birdies_lanham_hybrid_config.json")

def get_log_path():
    return os.path.join(get_app_dir(), "birdies_lanham_hybrid_raw_log.txt")

CONFIG_FILE = get_config_path()

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

# =============================================================================
# RAW LOGGER
# =============================================================================

class RawLogger:
    def __init__(self):
        self.log_path = get_log_path()
        self.lock = threading.Lock()
    
    def log(self, direction: str, content: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with self.lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"[{ts}] {direction}\n")
                    f.write(f"{'='*80}\n")
                    f.write(content)
                    f.write("\n")
            except Exception:
                pass

RAW_LOGGER = RawLogger()

# =============================================================================
# PCATS NAMESPACES
# =============================================================================

NS_LOY   = "http://www.pcats.org/schema/naxml/loyalty/v01"
NS_CORE  = "http://www.pcats.org/schema/core/v01"
NS_POSBO = "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
NS_DECLS = (
    f'xmlns:ns2="{NS_POSBO}" '
    f'xmlns:ns4="{NS_CORE}" '
    f'xmlns:ns3="{NS_LOY}"'
)

# =============================================================================
# SESSION DATA CLASSES
# =============================================================================

@dataclass
class PunchRewardSent:
    punch_card_id: int
    punch_card_name: str
    reward_id: str
    reward_type: str
    free_line_no: int = 0
    free_upc: str = ""
    free_units: int = 0

@dataclass
class TxnSession:
    loy_seq: str
    iface_ver: str
    customer: Optional[dict] = None
    last_seen_at: float = field(default_factory=time.time)
    promotions_applied: List[dict] = field(default_factory=list)
    promo_discount_total: float = 0.0
    promo_applied_flag: bool = False
    last_points_recommended: float = 0.0
    punch_rewards_sent: List[PunchRewardSent] = field(default_factory=list)

# =============================================================================
# EDGE AGENT SIGNALS
# =============================================================================

class EdgeAgentSignals(QObject):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    heartbeat_sent = Signal(str)

# =============================================================================
# EDGE AGENT WORKER (Based on lanhamverifoneworkingpunchanddiscount.py)
# =============================================================================

class EdgeAgentWorker(QThread):
    def __init__(self, config, signals):
        super().__init__()
        self.config = config
        self.signals = signals
        self.running = False
        self.server_socket = None
        
        self.SESSION_HTTP = requests.Session()
        self.REQUEST_TIMEOUT = (3, 5)
        
        self.HOST = config.get("host_ip", "0.0.0.0")
        self.PORT = int(config.get("port", 9000))
        self.PDI_STORE_NUMBER = config.get("store_number", "")
        self.POS_ID = "24379"
        self.POS_TYPE = "Verifone-EPS"
        self.BACKEND_URL = "https://salmanloyalty.replit.app"
        self.HEARTBEAT_INTERVAL = 15
        
        self.VENDOR_NAME = "BirdiesLoyalty"
        self.VENDOR_VER = "1.0"
        self.DEFAULT_IFACE_VER = "1.0"
        
        self.POINTS_PER_DOLLAR = 10000
        self.REWARD_ID = "DEMO-1OFF"
        self.PUNCH_REWARD_ID = "PUNCH-REWARD"
        self.RECEIPT_SHORT = "$OFF"
        self.RECEIPT_LONG = "Loyalty Discount"
        
        self.PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS = False   # requested behavior
        self.DISABLE_EARNING_WHEN_PROMO = False
        
        self.SESSIONS: Dict[str, TxnSession] = {}
        self.SESSION_TTL_SECONDS = 10 * 60

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.signals.log_message.emit(f"[{ts}] {msg}")

    def run(self):
        self.running = True
        self.signals.status_changed.emit("Starting...", "yellow")
        
        hb_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        hb_thread.start()
        
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(1.0)
            self.server_socket.bind((self.HOST, self.PORT))
            self.server_socket.listen(64)
            
            self.log(f"Listening on {self.HOST}:{self.PORT}")
            self.log(f"Store: {self.PDI_STORE_NUMBER}")
            self.log("Mode: PROMOS + PUNCH + POINTS HYBRID")
            self.log(f"Points: {self.POINTS_PER_DOLLAR} pts = $1.00")
            self.log("Protocol: Verifone EPS (4-byte BE framing)")
            self.signals.status_changed.emit("Online - Waiting for EPS", "green")
            
            while self.running:
                try:
                    conn, addr = self.server_socket.accept()
                    threading.Thread(
                        target=self.handle_client,
                        args=(conn, addr),
                        daemon=True
                    ).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"Accept error: {e}")
                        
        except Exception as e:
            self.log(f"Server error: {e}")
            self.signals.status_changed.emit(f"Error: {e}", "red")
        finally:
            if self.server_socket:
                try:
                    self.server_socket.close()
                except Exception:
                    pass
            self.signals.status_changed.emit("Stopped", "gray")

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass

    def heartbeat_loop(self):
        while self.running:
            self.send_backend_heartbeat()
            time.sleep(self.HEARTBEAT_INTERVAL)

    def send_backend_heartbeat(self, pos_ip: str = None):
        try:
            payload = {
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "posId": self.POS_ID,
                "posType": self.POS_TYPE,
                "posIpAddress": pos_ip,
                "edgeIpAddress": self.HOST,
                "edgeVersion": "birdies-lanham-hybrid-gui-1.0",
            }
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/pos/heartbeat",
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                self.signals.heartbeat_sent.emit(datetime.datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def pretty_xml(self, xml_bytes: bytes) -> str:
        try:
            return minidom.parseString(xml_bytes).toprettyxml()
        except Exception:
            try:
                return xml_bytes.decode("utf-8", errors="replace")
            except Exception:
                return str(xml_bytes)

    def strip_namespaces(self, elem: ET.Element) -> ET.Element:
        for e in elem.iter():
            if isinstance(e.tag, str) and '}' in e.tag:
                e.tag = e.tag.split('}', 1)[1]
        return elem

    def normalize_upc(self, upc: str) -> str:
        return (upc or "").strip()

    def is_masked(self, val: str) -> bool:
        return bool(val) and ("*" in val)

    def cleanup_sessions(self):
        now = time.time()
        expired = [k for k, s in self.SESSIONS.items() if (now - s.last_seen_at) > self.SESSION_TTL_SECONDS]
        for k in expired:
            del self.SESSIONS[k]
        if expired:
            self.log(f"Cleaned up {len(expired)} expired session(s)")

    # =========================================================================
    # EPS FRAMING: 4-byte BIG-ENDIAN length + UTF-8 XML
    # =========================================================================

    def send_xml(self, conn: socket.socket, xml_str: str):
        xml_bytes = xml_str.encode("utf-8")
        frame = struct.pack(">I", len(xml_bytes)) + xml_bytes
        conn.sendall(frame)
        self.log("-> Sent to EPS")
        RAW_LOGGER.log("SENT TO EPS", self.pretty_xml(xml_bytes))

    def recv_exact(self, conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return b""
            buf += chunk
        return buf

    def recv_frame(self, conn: socket.socket) -> bytes:
        hdr = self.recv_exact(conn, 4)
        if not hdr:
            return b""
        length = struct.unpack(">I", hdr)[0]
        if length <= 0:
            return b""
        return self.recv_exact(conn, length)

    def parse_xml(self, xml_bytes: bytes):
        raw = xml_bytes.decode("utf-8", errors="replace")
        RAW_LOGGER.log("RECEIVED FROM EPS", self.pretty_xml(xml_bytes))
        root = ET.fromstring(raw)
        root = self.strip_namespaces(root)
        return root, raw

    def get_req_ids(self, root: ET.Element):
        pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
        loy_seq = root.findtext(".//LoyaltySequenceID")
        if not loy_seq or not loy_seq.strip():
            loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
        return pos_seq, loy_seq

    def get_iface_ver(self, root: ET.Element) -> str:
        return (root.findtext(".//POSLoyaltyInterfaceVersion") or self.DEFAULT_IFACE_VER).strip()

    def get_pos_transaction_id(self, root: ET.Element) -> str:
        return (
            (root.findtext(".//POSTransactionID") or "").strip()
            or (root.findtext(".//TransactionID") or "").strip()
            or (root.findtext(".//TransactionHeader/TransactionID") or "").strip()
        )

    def resp_header(self, pos_seq: str, loy_seq: str, iface_ver: str) -> str:
        return (
            f'<ns3:ResponseHeader overallResult="success">'
            f'<ns3:POSLoyaltyInterfaceVersion>{iface_ver}</ns3:POSLoyaltyInterfaceVersion>'
            f'<ns2:VendorName>{self.VENDOR_NAME}</ns2:VendorName>'
            f'<ns2:VendorModelVersion>{self.VENDOR_VER}</ns2:VendorModelVersion>'
            f'<ns3:POSSequenceID>{pos_seq}</ns3:POSSequenceID>'
            f'<ns3:LoyaltySequenceID>{loy_seq}</ns3:LoyaltySequenceID>'
            f'<ns4:Result><Success/></ns4:Result>'
            f'</ns3:ResponseHeader>'
        )

    # =========================================================================
    # BASKET PARSING
    # =========================================================================

    def extract_line_items(self, root: ET.Element) -> List[dict]:
        items = []
        for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
            status = (tline.get("status") or "").strip().lower()
            if status and status != "normal":
                continue

            item_line = tline.find("./ItemLine")
            merch_line = tline.find("./MerchandiseCodeLine")
            il = item_line if item_line is not None else merch_line
            if il is None:
                continue

            is_item_line = item_line is not None

            try:
                line_no = int(tline.findtext("./LineNumber", "0"))
            except Exception:
                line_no = 0

            psc = (il.findtext(".//PaymentSystemsProductCode") or "").strip()

            upc_raw = ""
            if is_item_line:
                upc_raw = (
                    il.findtext("./ItemCode/POSCode")
                    or il.findtext(".//POSCode")
                    or il.findtext(".//UPC")
                    or ""
                )
            else:
                upc_raw = psc or (
                    il.findtext("./ItemCode/POSCode")
                    or il.findtext(".//POSCode")
                    or il.findtext(".//UPC")
                    or ""
                )

            upc = self.normalize_upc(upc_raw)
            desc = (il.findtext("Description") or il.findtext("ItemDescription") or "").strip()

            qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
            atxt = il.findtext("SalesAmount") or il.findtext("ExtendedAmount")
            unit_price_txt = il.findtext("UnitPrice", "0")
            actual_price_txt = il.findtext("ActualSalesPrice", "0")
            regular_price_txt = il.findtext("RegularSellPrice", "0")

            def to_f(x):
                try:
                    return float(x or 0)
                except Exception:
                    return 0.0

            try:
                qty = float(qtxt or 1.0)
            except Exception:
                qty = 1.0

            unit_price = to_f(unit_price_txt)
            actual_price = to_f(actual_price_txt)
            regular_price = to_f(regular_price_txt)

            if atxt and str(atxt).strip():
                amount = to_f(atxt)
            else:
                amount = actual_price * qty

            price = unit_price or actual_price or regular_price or 0.0

            items.append({
                "line_no": line_no,
                "upc": upc,
                "description": desc,
                "quantity": qty,
                "amount": amount,
                "price": price,
                "unit_price": unit_price,
                "actual_price": actual_price,
                "regular_price": regular_price,
                "is_item_line": is_item_line,
                "psc": psc,
            })
        return items

    def get_unit_price(self, it: dict) -> float:
        for k in ("unit_price", "actual_price", "regular_price", "price"):
            try:
                v = float(it.get(k, 0) or 0)
            except Exception:
                v = 0.0
            if v > 0:
                return v
        return 0.0

    def choose_cheapest_eligible_itemline(self, items: List[dict]) -> Optional[dict]:
        eligible = []
        for it in items:
            if not it.get("is_item_line"):
                continue
            if (it.get("psc") or "").strip() == "950":
                continue
            if not (it.get("upc") or "").strip():
                continue
            if float(it.get("amount", 0) or 0) <= 0:
                continue
            if self.get_unit_price(it) <= 0:
                continue
            eligible.append(it)
        if not eligible:
            return None
        return min(eligible, key=lambda x: self.get_unit_price(x))

    # =========================================================================
    # BACKEND API CALLS
    # =========================================================================

    def backend_customer_lookup(self, loyalty_id: str, phone: str) -> Optional[dict]:
        payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
        r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/customer-lookup", json=payload, timeout=self.REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        raise RuntimeError(f"customer-lookup failed: {r.status_code}")

    def evaluate_promotions(self, items: list) -> list:
        if not items:
            return []

        upc_groups = {}
        for it in items:
            upc = it.get("upc", "")
            if not upc:
                continue
            if upc not in upc_groups:
                upc_groups[upc] = {"upc": upc, "quantity": 0.0, "price": float(it.get("price", 0) or 0)}
            upc_groups[upc]["quantity"] += float(it.get("quantity", 1) or 1)

        if not upc_groups:
            return []

        payload = {"pdiStoreNumber": self.PDI_STORE_NUMBER, "items": list(upc_groups.values())}

        try:
            r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=self.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json().get("promotions", []) or []
            return []
        except Exception:
            return []

    def calculate_redemption(self, customer_id: int, eligible_subtotal: float, line_items: list) -> float:
        try:
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/pos/calculate-redemption",
                json={"customerId": customer_id, "eligibleSubtotal": eligible_subtotal, "lineItems": line_items},
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                return 0.0
            data = r.json()
            return float(data.get("recommendedRedemption") or 0.0)
        except Exception:
            return 0.0

    def finalize_transaction_backend(self, customer_id, eligible_subtotal, transaction_id, line_items, promotions, promotion_discount, points_redeemed):
        try:
            payload = {
                "customerId": customer_id,
                "eligibleSubtotal": eligible_subtotal,
                "pointsRedeemed": points_redeemed,
                "transactionId": transaction_id,
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "lineItems": line_items,
                "promotions": promotions or [],
                "promotionDiscount": float(promotion_discount or 0),
            }
            r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/finalize-transaction", json=payload, timeout=self.REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                self.log(f"Finalize OK: +{data.get('pointsEarned', 0)} pts, Balance: {data.get('newBalance', 0)}")
            else:
                self.log(f"Finalize failed: {r.status_code}")
        except Exception as e:
            self.log(f"Finalize error: {e}")

    def evaluate_punch_cards(self, customer_id: int, line_items: list) -> dict:
        try:
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/punch-cards/evaluate",
                json={"customerId": customer_id, "lineItems": line_items},
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {"punchCards": [], "rewardsReady": []}
        except Exception:
            return {"punchCards": [], "rewardsReady": []}

    def record_punches(self, customer_id: int, line_items: list, transaction_id: str) -> dict:
        try:
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/punch-cards/record-purchase",
                json={
                    "customerId": customer_id,
                    "lineItems": line_items,
                    "pdiStoreNumber": self.PDI_STORE_NUMBER,
                    "transactionId": transaction_id,
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            return {}

    def redeem_punch_reward(self, customer_id: int, punch_card_id: int, transaction_id: str) -> dict:
        try:
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/punch-cards/redeem",
                json={
                    "customerId": customer_id,
                    "punchCardId": punch_card_id,
                    "pdiStoreNumber": self.PDI_STORE_NUMBER,
                    "transactionId": transaction_id,
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            return {}

    # =========================================================================
    # PROMO CONVERSION
    # =========================================================================

    def build_promotion_rewards_xml_eps(self, items: list, promotions: list) -> Tuple[List[str], List[dict], float]:
        if not promotions:
            return [], [], 0.0

        upc_to_lines: Dict[str, List[dict]] = {}
        for it in items:
            upc = (it.get("upc") or "").strip()
            if not upc:
                continue
            upc_to_lines.setdefault(upc, []).append(it)

        best_by_upc: Dict[str, dict] = {}
        for promo in promotions:
            upc = (promo.get("upc") or "").strip()
            if not upc:
                continue

            disc_type = promo.get("discountType", "multipack")
            qty = int(promo.get("quantity", 1) or 1)
            bundles = int(promo.get("bundleCount", 0) or 0)
            if bundles <= 0:
                continue

            if disc_type == "multipack":
                promo_price_total = float(promo.get("promoPrice", 0.0) or 0.0)
                total_units = max(qty * bundles, 1)
                per_unit_new_price = promo_price_total / total_units
            else:
                total_units = max(qty * bundles, 1)
                per_unit_new_price = None

            if upc not in best_by_upc:
                best_by_upc[upc] = {"promo": promo, "per_unit_new_price": per_unit_new_price, "total_units": total_units}
            else:
                existing = best_by_upc[upc]
                if per_unit_new_price is not None and (
                    existing["per_unit_new_price"] is None or per_unit_new_price < existing["per_unit_new_price"]
                ):
                    best_by_upc[upc] = {"promo": promo, "per_unit_new_price": per_unit_new_price, "total_units": total_units}

        add_rewards = []
        applied_promotions = []
        total_discount_all = 0.0

        for upc, data in best_by_upc.items():
            promo = data["promo"]
            disc_type = promo.get("discountType", "multipack")
            qty = int(promo.get("quantity", 1) or 1)
            bundles = int(promo.get("bundleCount", 0) or 0)
            total_units_needed = qty * bundles
            remaining_units = total_units_needed

            matching_lines = upc_to_lines.get(upc, [])
            if not matching_lines or remaining_units <= 0:
                continue

            promo_id = promo.get("promotionId") or upc
            reward_id = f"PROMO-{promo_id}"
            promo_name = promo.get("name") or promo.get("itemGroupName") or "Promo"
            display_name = str(promo_name)[:24]

            total_discount_for_promo = 0.0

            for it in matching_lines:
                if remaining_units <= 0:
                    break

                take_qty = int(min(float(it.get("quantity", 1) or 1), remaining_units))
                if take_qty <= 0:
                    continue

                current_price = self.get_unit_price(it)
                if current_price <= 0:
                    remaining_units -= take_qty
                    continue

                discount_per_unit = 0.0
                if disc_type == "multipack":
                    per_unit_new_price = float(data["per_unit_new_price"] or 0.0)
                    discount_per_unit = max(0.0, current_price - per_unit_new_price)
                else:
                    total_discount = float(promo.get("discount", 0.0) or 0.0)
                    per_unit_discount = total_discount / max(total_units_needed, 1)
                    discount_per_unit = min(per_unit_discount, current_price)

                line_discount = max(0.0, discount_per_unit * take_qty)
                total_discount_for_promo += line_discount
                remaining_units -= take_qty

            total_discount_for_promo = float(f"{total_discount_for_promo:.2f}")
            if total_discount_for_promo <= 0:
                continue

            total_discount_all += total_discount_for_promo

            add_rewards.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{total_discount_for_promo:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PROMO</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{display_name}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())

            applied_promotions.append({
                "promotionId": promo.get("promotionId"),
                "name": promo_name,
                "upc": upc,
                "discountType": disc_type,
                "discount": total_discount_for_promo,
            })
            self.log(f"  PROMO: {display_name} -> ${total_discount_for_promo:.2f} off")

        return add_rewards, applied_promotions, total_discount_all

    # =========================================================================
    # RESPONSE BUILDERS
    # =========================================================================

    def build_online_status_response(self, root: ET.Element, pos_ip: str) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        self.send_backend_heartbeat(pos_ip)
        self.log("Responding to GetLoyaltyOnlineStatus - Loyalty is ONLINE")
        return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

    def build_get_rewards_response(self, root: ET.Element) -> str:
        self.cleanup_sessions()
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)

        loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
        phone = (root.findtext(".//PhoneNumber") or "").strip()

        if self.is_masked(loyalty_id):
            sess = self.SESSIONS.get(loy_seq)
            if sess and sess.customer:
                loyalty_id = sess.customer.get("loyaltyId") or ""
                phone = sess.customer.get("phone") or ""

        digits = "".join(ch for ch in loyalty_id if ch.isdigit())
        if len(digits) == 10:
            phone = digits
            loyalty_id = ""

        items = self.extract_line_items(root)
        if items:
            self.log("=" * 50)
            self.log(f"TRANSACTION ITEMS ({len(items)} items):")
            for idx, it in enumerate(items, 1):
                self.log(f"  {idx}. Line {it['line_no']}: UPC: {it['upc']} | Qty {it['quantity']} | ${it['amount']:.2f}")
            self.log("=" * 50)

        # Evaluate promotions first
        promotions = self.evaluate_promotions(items)
        promo_rewards, applied_promos, promo_discount = self.build_promotion_rewards_xml_eps(items, promotions)

        promo_applied = len(promo_rewards) > 0

        if not loyalty_id and not phone:
            reward_actions = (
                "<ns3:RewardActions>\n" + "\n".join(promo_rewards) + "\n</ns3:RewardActions>"
                if promo_rewards else "<ns3:RewardActions/>"
            )
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

        # Customer lookup
        try:
            customer = self.backend_customer_lookup(loyalty_id, phone)
        except Exception as e:
            self.log(f"Customer lookup error: {e}")
            customer = None

        if not customer:
            self.log(f"Customer not found: {loyalty_id or phone}")
            reward_actions = (
                "<ns3:RewardActions>\n" + "\n".join(promo_rewards) + "\n</ns3:RewardActions>"
                if promo_rewards else "<ns3:RewardActions/>"
            )
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

        customer_id = customer.get("customerId")
        first_name = customer.get("firstName", "")
        last_name = customer.get("lastName", "")
        points_balance = int(customer.get("pointsBalance", 0) or 0)

        self.log(f"Customer: {first_name} {last_name} ({points_balance} pts)")

        # Create/update session
        sess = self.SESSIONS.get(loy_seq)
        if not sess:
            sess = TxnSession(loy_seq=loy_seq, iface_ver=iface_ver, customer=customer)
            self.SESSIONS[loy_seq] = sess
        else:
            sess.customer = customer
            sess.iface_ver = iface_ver
        sess.last_seen_at = time.time()
        sess.promotions_applied = applied_promos
        sess.promo_discount_total = promo_discount
        sess.promo_applied_flag = promo_applied

        loyalty_reward_xmls = []

        # If promos applied and stacking policy disables loyalty discounts, skip punch/points
        if promo_applied and self.PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS:
            self.log("Promos applied - skipping loyalty discounts")
        else:
            # Punch cards
            punch_eval = self.evaluate_punch_cards(customer_id, items)
            punch_cards = punch_eval.get("punchCards", [])

            for pc in punch_cards:
                current = pc.get("currentPunches", 0)
                required = pc.get("punchesRequired", 10)
                basket = pc.get("punchesFromBasket", 0)
                punches_needed = max(0, required - current)
                already_full = current >= required
                buying_extra = basket > punches_needed
                should_trigger = already_full or buying_extra

                status_line = f"  {pc.get('punchCardName')}: {current}/{required}"
                if basket > 0:
                    status_line += f" +{basket} basket"
                if should_trigger:
                    status_line += " -> REWARD!"
                    self.log(status_line)

                    reward_type = pc.get("rewardType", "free_item")
                    reward_value = pc.get("rewardValue", "0")
                    punch_card_id = pc.get("punchCardId")
                    punch_name = pc.get("punchCardName", "Punch Reward")
                    reward_id = f"{self.PUNCH_REWARD_ID}-{punch_card_id}"

                    if reward_type == "free_item":
                        chosen = self.choose_cheapest_eligible_itemline(items)
                        if chosen:
                            line_no = chosen.get("line_no", 0)
                            unit_price = self.get_unit_price(chosen)
                            loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>{line_no}</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{unit_price:.2f}</ns3:RewardValue>
    <ns3:RewardLimit quantity="1"/>
    <ns3:RewardReceiptDescShort>FREE</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{punch_name}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())
                            sess.punch_rewards_sent.append(PunchRewardSent(
                                punch_card_id=punch_card_id,
                                punch_card_name=punch_name,
                                reward_id=reward_id,
                                reward_type="free_item",
                                free_line_no=line_no,
                                free_upc=(chosen.get("upc") or "").strip(),
                                free_units=1,
                            ))
                            self.log(f"    FREE ITEM: ${unit_price:.2f} off line {line_no}")

                    elif reward_type in ("dollar_off", "amount_off"):
                        try:
                            amt = float(reward_value or 0)
                        except Exception:
                            amt = 0.0
                        if amt > 0:
                            loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{punch_name}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())
                            sess.punch_rewards_sent.append(PunchRewardSent(
                                punch_card_id=punch_card_id,
                                punch_card_name=punch_name,
                                reward_id=reward_id,
                                reward_type="amount_off",
                            ))
                            self.log(f"    ${amt:.2f} OFF")

                    elif reward_type == "percent_off":
                        try:
                            pct = float(reward_value or 0)
                        except Exception:
                            pct = 0.0
                        if pct > 0:
                            subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
                            amt = max(0.0, subtotal * (pct / 100.0))
                            if amt > 0:
                                loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{punch_name} {pct:.0f}%</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())
                                sess.punch_rewards_sent.append(PunchRewardSent(
                                    punch_card_id=punch_card_id,
                                    punch_card_name=punch_name,
                                    reward_id=reward_id,
                                    reward_type="percent_off",
                                ))
                                self.log(f"    {pct:.0f}% OFF (${amt:.2f})")
                else:
                    self.log(status_line + f" (need {punches_needed} more)")

            # Points redemption
            eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
            if eligible_subtotal > 0 and points_balance >= self.POINTS_PER_DOLLAR:
                recommended = self.calculate_redemption(customer_id, eligible_subtotal, items)
                if recommended > 0:
                    sess.last_points_recommended = float(f"{recommended:.2f}")
                    loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{self.REWARD_ID}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="no"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{sess.last_points_recommended:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>{self.RECEIPT_SHORT}</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{self.RECEIPT_LONG}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())
                    self.log(f"  POINTS: ${recommended:.2f} redemption available")

        # Combine rewards
        reward_xmls = []
        if promo_rewards:
            reward_xmls.extend(promo_rewards)
        if loyalty_reward_xmls:
            reward_xmls.extend(loyalty_reward_xmls)

        reward_actions = (
            "<ns3:RewardActions>\n" + "\n".join(reward_xmls) + "\n</ns3:RewardActions>"
            if reward_xmls else "<ns3:RewardActions/>"
        )

        display_id = loyalty_id or phone or ""
        masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="yes">{masked}</ns3:LoyaltyIDValidFlag>
  <ns3:PointsBalance>{points_balance}</ns3:PointsBalance>
  {reward_actions}
</ns3:GetRewardsResponse>"""

    def build_finalize_response(self, root: ET.Element) -> str:
        self.cleanup_sessions()
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        txn_id = self.get_pos_transaction_id(root) or f"TXN-{uuid.uuid4().hex[:8].upper()}"

        sess = self.SESSIONS.get(loy_seq)
        if not sess:
            self.log("No session for finalize")
            return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

        sess.last_seen_at = time.time()
        final_items = self.extract_line_items(root)
        eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)

        if not sess.customer:
            if loy_seq in self.SESSIONS:
                del self.SESSIONS[loy_seq]
            return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

        customer_id = int(sess.customer.get("customerId") or 0)
        dollars_off = float(sess.last_points_recommended or 0.0)
        points_redeemed = int(round(dollars_off * self.POINTS_PER_DOLLAR)) if dollars_off > 0 else 0
        promo_discount = float(sess.promo_discount_total or 0.0)
        promo_applied = bool(sess.promo_applied_flag)

        self.log(f"FINALIZE: customer={customer_id} subtotal=${eligible_subtotal:.2f} promo=${promo_discount:.2f} pts_redeemed={points_redeemed}")

        if self.DISABLE_EARNING_WHEN_PROMO and promo_applied:
            self.finalize_transaction_backend(
                customer_id, eligible_subtotal, txn_id, final_items,
                sess.promotions_applied, promo_discount, 0
            )
        else:
            self.finalize_transaction_backend(
                customer_id, eligible_subtotal, txn_id, final_items,
                sess.promotions_applied, promo_discount, points_redeemed
            )

            # Record punches
            punch_result = self.record_punches(customer_id, final_items, txn_id)
            punches_recorded = punch_result.get("punchesRecorded", []) if isinstance(punch_result, dict) else []
            if punches_recorded:
                for p in punches_recorded:
                    self.log(f"  PUNCH: {p.get('punchCardName')}: +{p.get('punchesAdded')} -> {p.get('currentPunches')}/{p.get('punchesRequired')}")

            # Redeem punch rewards
            redeemed_ids = set()
            for pr in sess.punch_rewards_sent:
                if pr.punch_card_id and pr.punch_card_id not in redeemed_ids:
                    rr = self.redeem_punch_reward(customer_id, pr.punch_card_id, txn_id)
                    if isinstance(rr, dict) and rr.get("success"):
                        self.log(f"  REDEEMED: {pr.punch_card_name}")
                    redeemed_ids.add(pr.punch_card_id)

        if loy_seq in self.SESSIONS:
            del self.SESSIONS[loy_seq]

        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

    def build_cancel_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        if loy_seq in self.SESSIONS:
            del self.SESSIONS[loy_seq]
        self.log("Transaction cancelled")
        return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:CancelTransactionResponse>"""

    def build_end_period_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        self.log("End period acknowledged")
        return f"""<ns3:EndPeriodResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns4:Result><Success/></ns4:Result>
</ns3:EndPeriodResponse>"""

    # =========================================================================
    # CLIENT HANDLER
    # =========================================================================

    def handle_client(self, conn: socket.socket, addr):
        peer = f"{addr[0]}:{addr[1]}"
        self.log(f"EPS connected from {peer}")

        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
            except (AttributeError, OSError):
                pass

            conn.settimeout(5.0)
            self.log(f"Persistent connection established: {peer}")
            self.signals.status_changed.emit(f"Connected: {peer}", "green")

            empty_recv_count = 0
            max_empty_retries = 12

            while self.running:
                try:
                    frame = self.recv_frame(conn)

                    if not frame:
                        empty_recv_count += 1
                        if empty_recv_count >= max_empty_retries:
                            self.log(f"EPS connection appears dead: {peer}")
                            break
                        continue

                    empty_recv_count = 0

                    try:
                        root, _raw = self.parse_xml(frame)
                    except Exception as e:
                        self.log(f"XML parse error: {e}")
                        continue

                    tag = (root.tag or "").strip()
                    self.log(f"Request: {tag}")

                    if tag == "GetLoyaltyOnlineStatusRequest":
                        resp = self.build_online_status_response(root, addr[0])
                    elif tag == "GetRewardsRequest":
                        resp = self.build_get_rewards_response(root)
                    elif tag == "FinalizeRewardsRequest":
                        resp = self.build_finalize_response(root)
                    elif tag == "CancelTransactionRequest":
                        resp = self.build_cancel_response(root)
                    elif tag == "EndPeriodRequest":
                        resp = self.build_end_period_response(root)
                    else:
                        self.log(f"Unhandled request: {tag}")
                        pos_seq, loy_seq = self.get_req_ids(root)
                        iface_ver = self.get_iface_ver(root)
                        resp = f"""<ns3:UnknownResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:UnknownResponse>"""

                    self.send_xml(conn, resp)

                except socket.timeout:
                    continue
                except ConnectionResetError:
                    self.log(f"EPS connection reset: {peer}")
                    break
                except BrokenPipeError:
                    self.log(f"EPS broken pipe: {peer}")
                    break
                except OSError as e:
                    if e.errno in (10053, 10054, 10057):
                        self.log(f"EPS connection error: {peer}")
                        break
                    raise

        except Exception as e:
            self.log(f"EPS fatal error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
            self.log(f"EPS session ended: {peer}")
            self.signals.status_changed.emit("Online - Waiting for EPS", "green")

# =============================================================================
# SETUP WIZARD
# =============================================================================

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Birdies Lanham Hybrid - Setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(500, 400)

        self.addPage(self.create_welcome_page())
        self.addPage(self.create_network_page())
        self.addPage(self.create_store_page())
        self.addPage(self.create_finish_page())

    def create_welcome_page(self):
        page = QWizardPage()
        page.setTitle("Welcome")
        page.setSubTitle("Setup the Birdies Lanham Hybrid Edge Agent")

        layout = QVBoxLayout()

        info = QLabel(
            "This wizard will configure the edge agent for your Verifone Commander/Ruby POS.\n\n"
            "Features:\n"
            "  - PROMOTIONS (2-for-$X, Buy X Get Y, Amount Off)\n"
            "  - PUNCH CARDS (Free Item, % Off, $ Off)\n"
            "  - POINTS REDEMPTION (10,000 pts = $1.00)\n\n"
            "Stacking Policy:\n"
            "  - Promos apply first\n"
            "  - If promos apply, punch/points discounts are skipped"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()

        page.setLayout(layout)
        return page

    def create_network_page(self):
        page = QWizardPage()
        page.setTitle("Network Configuration")
        page.setSubTitle("Enter the IP address and port for the edge agent")

        layout = QFormLayout()

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g., 10.96.10.175")
        layout.addRow("Host IP Address:", self.host_input)

        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(9000)
        layout.addRow("Port:", self.port_input)

        note = QLabel(
            "\nThe Host IP should be this computer's IP on the Verifone network.\n"
            "Port 9000 is the standard loyalty port for Verifone EPS."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        layout.addRow(note)

        page.setLayout(layout)
        page.registerField("host_ip*", self.host_input)
        return page

    def create_store_page(self):
        page = QWizardPage()
        page.setTitle("Store Configuration")
        page.setSubTitle("Enter your store's PDI number")

        layout = QFormLayout()

        self.store_input = QLineEdit()
        self.store_input.setPlaceholderText("e.g., 0300")
        layout.addRow("PDI Store Number:", self.store_input)

        note = QLabel(
            "\nThis is your Birdies/PDI store number (e.g., 0300 for Lanham)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        layout.addRow(note)

        page.setLayout(layout)
        page.registerField("store_number*", self.store_input)
        return page

    def create_finish_page(self):
        page = QWizardPage()
        page.setTitle("Ready to Start")
        page.setSubTitle("Configuration complete")

        layout = QVBoxLayout()

        info = QLabel(
            "The edge agent is ready to start.\n\n"
            "Click 'Finish' to save the configuration and launch the agent.\n\n"
            "The agent will:\n"
            "  - Listen for Verifone EPS connections\n"
            "  - Process promotions, punch cards, and points\n"
            "  - Send heartbeats to the backend\n"
            "  - Log all raw XML to a text file"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()

        page.setLayout(layout)
        return page

    def get_config(self):
        return {
            "host_ip": self.host_input.text().strip(),
            "port": self.port_input.value(),
            "store_number": self.store_input.text().strip(),
        }

# =============================================================================
# MAIN WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.worker = None
        self.signals = EdgeAgentSignals()

        self.setWindowTitle("Birdies Lanham Hybrid Agent")
        self.setMinimumSize(750, 550)

        self.setup_ui()
        self.setup_tray()
        self.connect_signals()

        QTimer.singleShot(500, self.start_agent)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header = QHBoxLayout()
        title = QLabel("Birdies Lanham Hybrid Agent")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E3A8A;")
        header.addWidget(title)
        header.addStretch()

        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.status_indicator.setStyleSheet("background-color: gray; border-radius: 10px;")
        header.addWidget(self.status_indicator)

        self.status_label = QLabel("Starting...")
        self.status_label.setStyleSheet("font-size: 14px;")
        header.addWidget(self.status_label)

        layout.addLayout(header)

        info_group = QGroupBox("Configuration")
        info_layout = QFormLayout()
        info_layout.addRow("Host IP:", QLabel(self.config.get("host_ip", "")))
        info_layout.addRow("Port:", QLabel(str(self.config.get("port", 9000))))
        info_layout.addRow("Store:", QLabel(self.config.get("store_number", "")))
        info_layout.addRow("Protocol:", QLabel("Verifone EPS (PCATS)"))
        info_layout.addRow("Mode:", QLabel("Promos + Punch + Points (10K=$1)"))
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)

        buttons = QHBoxLayout()

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_agent)
        self.start_btn.setEnabled(False)
        buttons.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_agent)
        buttons.addWidget(self.stop_btn)

        self.open_log_btn = QPushButton("Open Raw Log")
        self.open_log_btn.clicked.connect(self.open_raw_log)
        buttons.addWidget(self.open_log_btn)

        buttons.addStretch()

        self.heartbeat_label = QLabel("Last heartbeat: --")
        self.heartbeat_label.setStyleSheet("color: #666;")
        buttons.addWidget(self.heartbeat_label)

        layout.addLayout(buttons)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#1E3A8A"))
        painter = QPainter(pixmap)
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 16, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "L")
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Birdies Lanham Hybrid Agent")

        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def connect_signals(self):
        self.signals.log_message.connect(self.append_log)
        self.signals.status_changed.connect(self.update_status)
        self.signals.heartbeat_sent.connect(self.update_heartbeat)

    def append_log(self, msg):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def update_status(self, text, color):
        self.status_label.setText(text)
        color_map = {
            "green": "#22c55e",
            "yellow": "#eab308",
            "red": "#ef4444",
            "gray": "#6b7280",
        }
        self.status_indicator.setStyleSheet(
            f"background-color: {color_map.get(color, '#6b7280')}; border-radius: 10px;"
        )

    def update_heartbeat(self, time_str):
        self.heartbeat_label.setText(f"Last heartbeat: {time_str}")

    def start_agent(self):
        if self.worker and self.worker.isRunning():
            return
        self.worker = EdgeAgentWorker(self.config, self.signals)
        self.worker.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_agent(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def open_raw_log(self):
        log_path = get_log_path()
        if os.path.exists(log_path):
            if sys.platform == "win32":
                os.startfile(log_path)
            elif sys.platform == "darwin":
                os.system(f'open "{log_path}"')
            else:
                os.system(f'xdg-open "{log_path}"')
        else:
            QMessageBox.information(self, "Log File", "No log file exists yet.")

    def show_window(self):
        self.showNormal()
        self.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Birdies Lanham Hybrid",
            "Agent is running in the background.",
            QSystemTrayIcon.Information,
            2000
        )

    def quit_app(self):
        self.stop_agent()
        QApplication.quit()

# =============================================================================
# MAIN
# =============================================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Birdies Lanham Hybrid Agent")
    app.setQuitOnLastWindowClosed(False)

    config = load_config()

    if not config:
        wizard = SetupWizard()
        if wizard.exec() == QWizard.Accepted:
            config = wizard.get_config()
            save_config(config)
        else:
            sys.exit(0)

    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
