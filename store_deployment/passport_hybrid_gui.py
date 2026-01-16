#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PASSPORT HYBRID GUI
=================================================
GUI wrapper for the Passport PROMOS + PUNCH + POINTS Edge Agent.
Based on: working_edgecodes/passport_hybrid_promos_punch_points.py

Features:
  - Setup wizard for IP, Port, PDI Store Number
  - Real-time status dashboard
  - System tray support
  - Raw interaction logging to text file
  - PROMOTIONS (2-for-$X, buy X get Y free, amount off)
  - PUNCH CARDS (free item)
  - POINTS REDEMPTION (10,000 pts = $1.00)

Passport POSLOYALTY protocol:
  - TCP framing: 12-byte POSLOYALTY signature + header + CRC checksums
  - XML payloads with ResponseHeader
  - Uses newPrice for promos and punch free items
  - Uses amountOff for points redemption

Build EXE on Windows with:
  pip install pyside6 requests pyinstaller
  pyinstaller --onefile --windowed --name "Birdies Passport Hybrid" --collect-all PySide6 passport_hybrid_gui.py

Version: 1.0 (based on passport_hybrid_promos_punch_points.py)
"""

import sys
import os
import json
import socket
import threading
import datetime
import binascii
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
    return os.path.join(get_app_dir(), "birdies_passport_hybrid_config.json")

def get_log_path():
    return os.path.join(get_app_dir(), "birdies_passport_hybrid_raw_log.txt")

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
# POSLOYALTY PROTOCOL CONSTANTS
# =============================================================================

SIGNATURE = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE = 1
ACTION_HEARTBEAT = 2

# =============================================================================
# SESSION DATA CLASSES
# =============================================================================

@dataclass
class PromoLineApplied:
    reward_id: str
    promo_id: str
    upc: str
    discount: float

@dataclass
class FreePunchLine:
    punch_card_id: int
    punch_card_name: str
    line_no: int
    upc: str
    free_units: int
    loyalty_reward_id: str

@dataclass
class TxnSession:
    loyalty_sequence_id: str
    customer: Optional[dict] = None
    last_seen_at: float = field(default_factory=time.time)
    promo_lines_sent: List[PromoLineApplied] = field(default_factory=list)
    promo_meta_by_id: Dict[str, dict] = field(default_factory=dict)
    applied_free_lines: List[FreePunchLine] = field(default_factory=list)
    last_points_recommended: float = 0.0
    cancelled_reward_ids: set = field(default_factory=set)

# =============================================================================
# EDGE AGENT SIGNALS
# =============================================================================

class EdgeAgentSignals(QObject):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    heartbeat_sent = Signal(str)

# =============================================================================
# EDGE AGENT WORKER (Passport POSLOYALTY Protocol)
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
        self.PORT = config.get("port", 9000)
        self.PDI_STORE_NUMBER = config.get("pdi_store_number", "1340")
        self.POS_ID = self.PDI_STORE_NUMBER
        self.BACKEND_URL = "https://salmanloyalty.replit.app"
        self.EXPECTED_POS_IP = None
        
        self.VENDOR_NAME = "DemoLoyalty"
        self.VENDOR_VER = "1.0"
        self.IFACE_VER = "1.0"
        
        self.REWARD_ID = "DEMO-1OFF"
        self.RECEIPT_SHORT = "$1OFF"
        self.RECEIPT_LONG = "Loyalty $ Off"
        self.POINTS_PER_DOLLAR = 10000
        self.PUNCH_REWARD_ID = "PUNCH-REWARD"
        
        self.SESSIONS: Dict[str, TxnSession] = {}
        self.SESSION_TTL = 10 * 60
        self.HEARTBEAT_INTERVAL = 15
    
    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full = f"[{ts}] {msg}"
        self.signals.log_message.emit(full)
        print(full, flush=True)
    
    def pretty_xml(self, xml_bytes: bytes) -> str:
        try:
            return minidom.parseString(xml_bytes).toprettyxml()
        except Exception:
            try:
                return xml_bytes.decode("utf-8", errors="replace")
            except Exception:
                return str(xml_bytes)
    
    def crc32(self, b: bytes) -> int:
        return binascii.crc32(b) & 0xFFFFFFFF
    
    def pack_header(self, xml_bytes: bytes, action: int = ACTION_MESSAGE) -> bytes:
        data_len = len(xml_bytes)
        chk_data = self.crc32(xml_bytes)
        head_wo_hdr_crc = SIGNATURE + struct.pack("<III", action, data_len, chk_data)
        chk_hdr = self.crc32(head_wo_hdr_crc)
        return head_wo_hdr_crc + struct.pack("<I", chk_hdr)
    
    def parse_header(self, hdr: bytes):
        if len(hdr) != 28:
            raise ValueError("short header")
        if hdr[:12] != SIGNATURE:
            raise ValueError("bad signature")
        action, data_len, chk_data, chk_hdr = struct.unpack("<IIII", hdr[12:28])
        if self.crc32(hdr[:24]) != chk_hdr:
            raise ValueError("header CRC mismatch")
        return action, data_len, chk_data
    
    def recv_exact(self, conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return b""
            buf += chunk
        return buf
    
    def send_xml(self, conn: socket.socket, xml_str: str, action: int = ACTION_MESSAGE):
        xml_bytes = xml_str.encode("utf-8")
        hdr = self.pack_header(xml_bytes, action)
        conn.sendall(hdr + xml_bytes)
        RAW_LOGGER.log("SENT TO POS", self.pretty_xml(xml_bytes))
        self.log("→ Sent response to POS")
    
    def get_req_ids(self, root: ET.Element):
        pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
        loy_seq = root.findtext(".//LoyaltySequenceID")
        if not loy_seq or not loy_seq.strip():
            loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
        return pos_seq, loy_seq
    
    def resp_header(self, pos_seq: str, loy_seq: str) -> str:
        return (
            f"<ResponseHeader>"
            f"<POSLoyaltyInterfaceVersion>{self.IFACE_VER}</POSLoyaltyInterfaceVersion>"
            f"<VendorName>{self.VENDOR_NAME}</VendorName>"
            f"<VendorModelVersion>{self.VENDOR_VER}</VendorModelVersion>"
            f"<POSSequenceID>{pos_seq}</POSSequenceID>"
            f"<LoyaltySequenceID>{loy_seq}</LoyaltySequenceID>"
            f"</ResponseHeader>"
        )
    
    def is_masked(self, val: str) -> bool:
        return bool(val) and ("*" in val)
    
    def normalize_upc(self, upc: str) -> str:
        return (upc or "").strip()
    
    def get_pos_transaction_id(self, root: ET.Element) -> str:
        return (root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or "").strip()
    
    def cleanup_sessions(self):
        now = time.time()
        expired = [k for k, s in self.SESSIONS.items() if (now - s.last_seen_at) > self.SESSION_TTL]
        for k in expired:
            del self.SESSIONS[k]
    
    def send_heartbeat(self, pos_ip: str = None):
        try:
            payload = {
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "posId": self.POS_ID,
                "posType": "Passport",
                "posIpAddress": pos_ip or self.EXPECTED_POS_IP or "",
                "edgeIpAddress": self.HOST,
                "edgeVersion": "birdies-passport-hybrid-gui-1.0",
            }
            r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/heartbeat", json=payload, timeout=self.REQUEST_TIMEOUT)
            if r.status_code == 200:
                self.log(f"✓ Heartbeat sent (Store {self.PDI_STORE_NUMBER})")
                self.signals.heartbeat_sent.emit(datetime.datetime.now().strftime("%H:%M:%S"))
        except Exception as e:
            self.log(f"⚠ Heartbeat error: {e}")
    
    def heartbeat_loop(self):
        while self.running:
            self.send_heartbeat()
            time.sleep(self.HEARTBEAT_INTERVAL)
    
    def extract_line_items(self, root: ET.Element) -> List[dict]:
        items = []
        for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
            status = (tline.get("status") or "").strip().lower()
            if status and status != "normal":
                continue
            il = tline.find("./ItemLine")
            if il is None:
                continue
            try:
                line_no = int(tline.findtext("./LineNumber", "0"))
            except:
                line_no = 0
            upc_raw = (il.findtext("./ItemCode/POSCode") or il.findtext(".//POSCode") or il.findtext(".//UPC") or "").strip()
            upc = self.normalize_upc(upc_raw)
            desc = (il.findtext("Description") or "").strip()
            qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
            atxt = il.findtext("SalesAmount")
            unit_price_txt = il.findtext("UnitPrice", "0")
            actual_price_txt = il.findtext("ActualSalesPrice", "0")
            regular_price_txt = il.findtext("RegularSellPrice", "0")
            def to_f(x):
                try:
                    return float(x or 0)
                except:
                    return 0.0
            try:
                qty = float(qtxt or 1.0)
            except:
                qty = 1.0
            unit_price = to_f(unit_price_txt)
            actual_price = to_f(actual_price_txt)
            regular_price = to_f(regular_price_txt)
            price = unit_price or actual_price or regular_price or 0.0
            if atxt and atxt.strip():
                amount = to_f(atxt)
            else:
                amount = actual_price * qty
            promo_reward_ids = []
            for promo in il.findall("./Promotion"):
                lrid = (promo.findtext("LoyaltyRewardID") or "").strip()
                if lrid:
                    promo_reward_ids.append(lrid)
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
                "promo_reward_ids": promo_reward_ids,
            })
        return items
    
    def get_current_unit_price(self, item: dict) -> float:
        for key in ("unit_price", "actual_price", "regular_price"):
            val = item.get(key, 0.0)
            if val and float(val) > 0:
                return float(val)
        try:
            return float(item.get("price", 0) or 0)
        except:
            return 0.0
    
    def detect_loyalty_tender(self, root: ET.Element, reward_id: str) -> float:
        dollars = 0.0
        for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
            ti = tline.find("./TenderInfo")
            if ti is None:
                continue
            lrid = (ti.findtext("LoyaltyRewardID") or "").strip()
            if lrid == reward_id:
                try:
                    dollars += float(ti.findtext("TenderAmount", "0") or 0)
                except:
                    pass
        return round(dollars, 2)
    
    def finalize_has_reward_anywhere(self, root: ET.Element, reward_id: str) -> bool:
        if not reward_id:
            return False
        for node in root.findall(".//LoyaltyRewardID"):
            if (node.text or "").strip() == reward_id:
                return True
        return False
    
    def confirmed_free_lines_from_finalize(self, final_items: list) -> set:
        confirmed = set()
        for it in final_items:
            ln = int(it.get("line_no", 0) or 0)
            for lrid in it.get("promo_reward_ids", []) or []:
                if lrid.startswith(self.PUNCH_REWARD_ID):
                    confirmed.add(ln)
                    break
        return confirmed
    
    def backend_customer_lookup(self, loyalty_id: str, phone: str):
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
        for item in items:
            upc = (item.get("upc") or "").strip()
            if not upc:
                continue
            if upc not in upc_groups:
                upc_groups[upc] = {"upc": upc, "quantity": 0.0, "price": float(item.get("price", 0) or 0)}
            upc_groups[upc]["quantity"] += float(item.get("quantity", 1) or 1)
        if not upc_groups:
            return []
        payload = {"pdiStoreNumber": self.PDI_STORE_NUMBER, "items": list(upc_groups.values())}
        try:
            r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=self.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json().get("promotions", []) or []
            return []
        except:
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
            return float(r.json().get("recommendedRedemption") or 0.0)
        except:
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
                self.log(f" ✓ Finalize OK: earned={data.get('pointsEarned', 0)} balance={data.get('newBalance', 0)}")
        except Exception as e:
            self.log(f" ⚠ finalize error: {e}")
    
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
        except:
            return {"punchCards": [], "rewardsReady": []}
    
    def record_punches(self, customer_id: int, line_items: list, transaction_id: str) -> dict:
        try:
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/punch-cards/record-purchase",
                json={"customerId": customer_id, "lineItems": line_items, "pdiStoreNumber": self.PDI_STORE_NUMBER, "transactionId": transaction_id},
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {}
        except:
            return {}
    
    def redeem_punch_reward(self, customer_id: int, punch_card_id: int, transaction_id: str) -> dict:
        try:
            r = self.SESSION_HTTP.post(
                f"{self.BACKEND_URL}/api/punch-cards/redeem",
                json={"customerId": customer_id, "punchCardId": punch_card_id, "pdiStoreNumber": self.PDI_STORE_NUMBER, "transactionId": transaction_id},
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {}
        except:
            return {}
    
    def build_promotion_rewards_xml(self, items: list, promotions: list):
        if not promotions:
            return [], [], {}
        upc_to_lines: Dict[str, List[dict]] = {}
        for it in items:
            upc = (it.get("upc") or "").strip()
            if upc:
                upc_to_lines.setdefault(upc, []).append(it)
        grouped: Dict[Tuple[str, str], dict] = {}
        for promo in promotions:
            upc = (promo.get("upc") or "").strip()
            promo_id = str(promo.get("promotionId") or "").strip()
            if not upc or not promo_id:
                continue
            promo_qty = int(promo.get("quantity", 2) or 2)
            bundle_count = int(promo.get("bundleCount", 0) or 0)
            promo_price = float(promo.get("promoPrice", 0) or 0)
            if bundle_count <= 0:
                continue
            total_units = max(bundle_count * promo_qty, 1)
            per_unit_new_price = promo_price / total_units if total_units else 0.0
            key = (upc, promo_id)
            if key not in grouped:
                grouped[key] = {"promo": promo, "per_unit_price": per_unit_new_price, "total_bundle_count": bundle_count}
            else:
                grouped[key]["total_bundle_count"] += bundle_count
        best_by_upc: Dict[str, dict] = {}
        for (upc, _pid), data in grouped.items():
            if upc not in best_by_upc or data["per_unit_price"] < best_by_upc[upc]["per_unit_price"]:
                best_by_upc[upc] = data
        add_rewards: List[str] = []
        promo_lines: List[PromoLineApplied] = []
        promo_meta_by_id: Dict[str, dict] = {}
        for upc, best_data in best_by_upc.items():
            promo = best_data["promo"]
            promo_id = str(promo.get("promotionId") or "").strip()
            if not promo_id:
                continue
            promo_qty = int(promo.get("quantity", 2) or 2)
            bundle_count = int(best_data["total_bundle_count"] or 0)
            per_unit_new_price = float(best_data["per_unit_price"] or 0.0)
            promo_name = promo.get("name") or promo.get("itemGroupName") or "Promo"
            display_name = str(promo_name)[:24]
            matching_lines = upc_to_lines.get(upc, [])
            if not matching_lines:
                continue
            total_units_needed = bundle_count * promo_qty
            remaining_units = total_units_needed
            meta = dict(promo)
            meta["name"] = display_name
            promo_meta_by_id[promo_id] = meta
            for it in matching_lines:
                if remaining_units <= 0:
                    break
                current_price = self.get_current_unit_price(it)
                if current_price <= 0 or current_price <= per_unit_new_price:
                    continue
                take_qty = min(int(float(it.get("quantity", 1) or 1)), remaining_units)
                if take_qty <= 0:
                    continue
                line_no = int(it.get("line_no", 0) or 0)
                if line_no <= 0:
                    continue
                reward_id = f"PROMO-{promo_id}-L{line_no}"
                discount_per_unit = current_price - per_unit_new_price
                line_discount = round(discount_per_unit * take_qty, 2)
                if line_discount <= 0:
                    remaining_units -= take_qty
                    continue
                add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>{per_unit_new_price:.4f}</RewardValue>
      <RewardLimit type="quantity">{take_qty}</RewardLimit>
      <RewardReceiptDescShort>PROMO</RewardReceiptDescShort>
      <RewardReceiptDescLong>{display_name}</RewardReceiptDescLong>
    </AddReward>""".rstrip())
                promo_lines.append(PromoLineApplied(reward_id=reward_id, promo_id=promo_id, upc=upc, discount=float(f"{line_discount:.2f}")))
                remaining_units -= take_qty
        return add_rewards, promo_lines, promo_meta_by_id
    
    def adjust_items_for_record_purchase(self, final_items: list, free_lines: List[FreePunchLine]) -> list:
        free_map: Dict[int, int] = {}
        for f in free_lines:
            free_map[f.line_no] = free_map.get(f.line_no, 0) + int(f.free_units or 1)
        adjusted = []
        for it in final_items:
            ln = int(it.get("line_no", 0) or 0)
            upc = (it.get("upc") or "").strip()
            try:
                qty_int = int(float(it.get("quantity", 1) or 1))
            except:
                qty_int = 1
            if not upc or qty_int <= 0:
                adjusted.append(it)
                continue
            free_units = int(free_map.get(ln, 0) or 0)
            if free_units <= 0:
                adjusted.append(it)
                continue
            free_units = max(0, min(free_units, qty_int))
            paid_units = qty_int - free_units
            unit_price = float(it.get("price", 0) or 0.0)
            orig_amt = float(it.get("amount", 0) or 0.0)
            if paid_units > 0:
                paid = dict(it)
                paid["quantity"] = float(paid_units)
                if unit_price > 0:
                    paid["amount"] = round(unit_price * paid_units, 2)
                else:
                    paid["amount"] = round(max(0.01, orig_amt * (paid_units / max(1, qty_int))), 2)
                adjusted.append(paid)
            if free_units > 0:
                free = dict(it)
                free["quantity"] = float(free_units)
                free["amount"] = 0.0
                adjusted.append(free)
        return adjusted
    
    def build_online_status_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        return (
            "<GetLoyaltyOnlineStatusResponse>"
            f"{self.resp_header(pos_seq, loy_seq)}"
            '<PromptForLoyaltyFlag value="yes"/>'
            "</GetLoyaltyOnlineStatusResponse>"
        )
    
    def build_get_rewards_response(self, root: ET.Element) -> str:
        self.cleanup_sessions()
        pos_seq, loy_seq = self.get_req_ids(root)
        txn_id = self.get_pos_transaction_id(root)
        sess = self.SESSIONS.get(loy_seq)
        if not sess:
            sess = TxnSession(loyalty_sequence_id=loy_seq)
            self.SESSIONS[loy_seq] = sess
        sess.last_seen_at = time.time()
        loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
        phone = (root.findtext(".//PhoneNumber") or "").strip()
        digits = "".join(ch for ch in loyalty_id if ch.isdigit())
        if len(digits) == 10 and not self.is_masked(loyalty_id):
            phone = digits
            loyalty_id = ""
        items = self.extract_line_items(root)
        if items:
            self.log(f"🛒 {len(items)} items [txn={txn_id}]")
        sess.promo_lines_sent = []
        sess.promo_meta_by_id = {}
        sess.applied_free_lines = []
        sess.last_points_recommended = 0.0
        promos = self.evaluate_promotions(items)
        promo_rewards_xml, promo_lines, promo_meta_by_id = self.build_promotion_rewards_xml(items, promos)
        sess.promo_lines_sent = promo_lines
        sess.promo_meta_by_id = promo_meta_by_id
        customer = None
        if self.is_masked(loyalty_id):
            if sess.customer:
                customer = sess.customer
        else:
            if sess.customer:
                customer = sess.customer
            elif loyalty_id or phone:
                try:
                    customer = self.backend_customer_lookup(loyalty_id, phone)
                except Exception as e:
                    self.log(f"⚠ customer-lookup error: {e}")
                    return f'<GetRewardsResponse>{self.resp_header(pos_seq, loy_seq)}<LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag><RewardActions/></GetRewardsResponse>'
                if not customer:
                    return f'<GetRewardsResponse>{self.resp_header(pos_seq, loy_seq)}<LoyaltyIDValidFlag value="no">Customer not found</LoyaltyIDValidFlag><RewardActions/></GetRewardsResponse>'
                sess.customer = customer
        points_balance = 0
        customer_id = 0
        masked_display = "Guest"
        if customer:
            points_balance = int(customer.get("pointsBalance", 0) or 0)
            customer_id = int(customer.get("customerId") or 0)
            display_id = phone or loyalty_id or ""
            if self.is_masked(loyalty_id):
                masked_display = loyalty_id
            else:
                masked_display = (display_id[-4:].rjust(10, "*")) if display_id else "****"
            self.log(f"✓ Customer: {customer.get('firstName','')} {customer.get('lastName','')} ({points_balance} pts)")
        punch_rewards_xml: List[str] = []
        if customer_id and items:
            punch_eval = self.evaluate_punch_cards(customer_id, items)
            punch_cards = punch_eval.get("punchCards", []) or []
            for pc in punch_cards:
                if "rewardReady" in pc and not bool(pc.get("rewardReady")):
                    continue
                current = int(pc.get("currentPunches", 0) or 0)
                basket = int(pc.get("punchesFromBasket", 0) or 0)
                required = int(pc.get("punchesRequired", 10) or 10)
                punches_needed = max(0, required - current)
                already_full = current >= required
                buying_extra = basket > punches_needed
                if not (already_full or buying_extra):
                    continue
                eligible = [it for it in items if it.get("upc") and float(it.get("amount", 0) or 0) > 0 and float(it.get("price", 0) or 0) > 0]
                if not eligible:
                    continue
                cheapest = min(eligible, key=lambda it: float(it.get("price", 0) or 0))
                line_no = int(cheapest.get("line_no", 0) or 0)
                if line_no <= 0:
                    continue
                punch_card_id = int(pc.get("punchCardId") or 0)
                punch_name = (pc.get("punchCardName") or "Punch Reward").strip()
                reward_id = f"{self.PUNCH_REWARD_ID}-{punch_card_id}"
                punch_rewards_xml.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>0.0000</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>FREE</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_name} FREE ITEM</RewardReceiptDescLong>
    </AddReward>""".rstrip())
                sess.applied_free_lines.append(FreePunchLine(punch_card_id=punch_card_id, punch_card_name=punch_name, line_no=line_no, upc=(cheapest.get("upc") or "").strip(), free_units=1, loyalty_reward_id=reward_id))
                self.log(f"🎁 Punch reward ready: {punch_name}")
        points_reward_xml = ""
        if customer_id and items:
            eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
            if eligible_subtotal > 0 and points_balance >= self.POINTS_PER_DOLLAR:
                recommended = self.calculate_redemption(customer_id, eligible_subtotal, items)
                if recommended > 0:
                    sess.last_points_recommended = float(f"{recommended:.2f}")
                    points_reward_xml = f"""
    <AddReward>
      <LoyaltyRewardID>{self.REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="no"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{sess.last_points_recommended:.2f}</RewardValue>
      <RewardReceiptDescShort>{self.RECEIPT_SHORT}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{self.RECEIPT_LONG}</RewardReceiptDescLong>
    </AddReward>""".rstrip()
                    self.log(f"💰 Points redemption: ${recommended:.2f}")
        all_rewards: List[str] = []
        if promo_rewards_xml:
            all_rewards.extend(promo_rewards_xml)
        if punch_rewards_xml:
            all_rewards.extend(punch_rewards_xml)
        if points_reward_xml:
            all_rewards.append(points_reward_xml)
        rewards_block = "<RewardActions/>"
        if all_rewards:
            rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
        if customer_id or promo_rewards_xml:
            return f'<GetRewardsResponse>{self.resp_header(pos_seq, loy_seq)}<LoyaltyIDValidFlag value="yes">{masked_display}</LoyaltyIDValidFlag>{rewards_block}</GetRewardsResponse>'
        return f'<GetRewardsResponse>{self.resp_header(pos_seq, loy_seq)}<LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag><RewardActions/></GetRewardsResponse>'
    
    def build_finalize_response(self, root: ET.Element) -> str:
        self.cleanup_sessions()
        pos_seq, loy_seq = self.get_req_ids(root)
        txn_id = self.get_pos_transaction_id(root) or f"TXN-{uuid.uuid4().hex[:8].upper()}"
        sess = self.SESSIONS.get(loy_seq)
        if not sess:
            return f'<FinalizeRewardsResponse>{self.resp_header(pos_seq, loy_seq)}</FinalizeRewardsResponse>'
        sess.last_seen_at = time.time()
        final_items = self.extract_line_items(root)
        eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)
        applied_dollars = self.detect_loyalty_tender(root, self.REWARD_ID)
        points_redeemed = int(round(applied_dollars * self.POINTS_PER_DOLLAR)) if applied_dollars > 0 else 0
        promo_discount_total = 0.0
        promo_discount_by_promo_id: Dict[str, float] = {}
        for pl in sess.promo_lines_sent:
            if pl.reward_id in sess.cancelled_reward_ids:
                continue
            if self.finalize_has_reward_anywhere(root, pl.reward_id):
                promo_discount_total += float(pl.discount or 0)
                promo_discount_by_promo_id[pl.promo_id] = promo_discount_by_promo_id.get(pl.promo_id, 0.0) + float(pl.discount or 0)
        promo_discount_total = float(f"{promo_discount_total:.2f}")
        promotions_for_backend: List[dict] = []
        for promo_id, disc in promo_discount_by_promo_id.items():
            meta = sess.promo_meta_by_id.get(promo_id, {})
            out = dict(meta) if isinstance(meta, dict) else {}
            out["promotionId"] = promo_id
            out["discount"] = float(f"{disc:.2f}")
            promotions_for_backend.append(out)
        self.log(f"🏁 Finalize: subtotal=${eligible_subtotal:.2f} promoDisc=${promo_discount_total:.2f} ptsRedeemed={points_redeemed}")
        if sess.customer:
            customer_id = int(sess.customer.get("customerId") or 0)
            self.finalize_transaction_backend(customer_id, eligible_subtotal, txn_id, final_items, promotions_for_backend, promo_discount_total, points_redeemed)
            confirmed_lines = self.confirmed_free_lines_from_finalize(final_items)
            intended_confirmed = [f for f in sess.applied_free_lines if int(f.line_no) in confirmed_lines]
            record_items = self.adjust_items_for_record_purchase(final_items, intended_confirmed) if intended_confirmed else final_items
            punch_result = self.record_punches(customer_id, record_items, txn_id)
            punches_recorded = punch_result.get("punchesRecorded", []) if isinstance(punch_result, dict) else []
            if punches_recorded:
                for p in punches_recorded:
                    self.log(f" 🎯 {p.get('punchCardName')}: +{p.get('punchesAdded')} → {p.get('currentPunches')}/{p.get('punchesRequired')}")
            redeemed_ids = set()
            for f in intended_confirmed:
                if f.punch_card_id and f.punch_card_id not in redeemed_ids:
                    try:
                        redeem_result = self.redeem_punch_reward(customer_id, f.punch_card_id, txn_id)
                        if redeem_result.get("success"):
                            self.log(f" 🎁 Redeemed: {f.punch_card_name}")
                            redeemed_ids.add(f.punch_card_id)
                    except Exception as e:
                        self.log(f" ⚠ Punch redeem error: {e}")
        del self.SESSIONS[loy_seq]
        return f'<FinalizeRewardsResponse>{self.resp_header(pos_seq, loy_seq)}</FinalizeRewardsResponse>'
    
    def build_cancel_txn_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        if loy_seq in self.SESSIONS:
            del self.SESSIONS[loy_seq]
        return f"<CancelTransactionResponse>{self.resp_header(pos_seq, loy_seq)}</CancelTransactionResponse>"
    
    def build_cancel_redemption_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        reward_id = (root.findtext(".//LoyaltyRewardID") or "").strip()
        sess = self.SESSIONS.get(loy_seq)
        if sess and reward_id:
            sess.cancelled_reward_ids.add(reward_id)
        return f"<CancelRedemptionResponse>{self.resp_header(pos_seq, loy_seq)}</CancelRedemptionResponse>"
    
    def build_get_customer_msg_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        return f'<GetCustomerMessagingResponse>{self.resp_header(pos_seq, loy_seq)}<CustomerMessageData><DisplayData><DisplayCommand device="POS-Cashier" sequence="WhenReceived"><DisplayLine>Welcome to Birdies Loyalty!</DisplayLine></DisplayCommand></DisplayData></CustomerMessageData></GetCustomerMessagingResponse>'
    
    def build_end_period_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        return f'<EndPeriodResponse>{self.resp_header(pos_seq, loy_seq)}<Result value="success"/></EndPeriodResponse>'
    
    def handle_client(self, conn: socket.socket, addr):
        peer = f"{addr[0]}:{addr[1]}"
        self.log(f"POS connected: {peer}")
        self.signals.status_changed.emit("connected", peer)
        if self.EXPECTED_POS_IP and addr[0] != self.EXPECTED_POS_IP:
            self.log(f"⚠ Rejecting unexpected IP: {addr[0]}")
            try:
                conn.close()
            except:
                pass
            return
        self.send_heartbeat(addr[0])
        try:
            conn.settimeout(180)
            while self.running:
                hdr = self.recv_exact(conn, 28)
                if not hdr:
                    break
                action, data_len, chk_data = self.parse_header(hdr)
                if action == ACTION_HEARTBEAT:
                    if data_len:
                        _ = self.recv_exact(conn, data_len)
                    continue
                data = self.recv_exact(conn, data_len)
                if len(data) != data_len or self.crc32(data) != chk_data:
                    self.log("Payload CRC/length mismatch")
                    break
                RAW_LOGGER.log("RECEIVED FROM POS", self.pretty_xml(data))
                root = ET.fromstring(data.decode("utf-8", errors="replace"))
                tag = root.tag.strip()
                if tag == "GetLoyaltyOnlineStatusRequest":
                    self.send_xml(conn, self.build_online_status_response(root))
                    self.send_heartbeat(addr[0])
                elif tag == "GetRewardsRequest":
                    self.send_xml(conn, self.build_get_rewards_response(root))
                elif tag == "FinalizeRewardsRequest":
                    self.send_xml(conn, self.build_finalize_response(root))
                elif tag == "CancelTransactionRequest":
                    self.send_xml(conn, self.build_cancel_txn_response(root))
                elif tag == "CancelRedemptionRequest":
                    self.send_xml(conn, self.build_cancel_redemption_response(root))
                elif tag == "GetCustomerMessagingRequest":
                    self.send_xml(conn, self.build_get_customer_msg_response(root))
                elif tag == "EndPeriodRequest":
                    self.send_xml(conn, self.build_end_period_response(root))
                elif tag in ("BeginCustomerRequest", "EndCustomerRequest"):
                    pass
                else:
                    self.log(f"⚠ Unhandled: {tag}")
        except socket.timeout:
            self.log(f"POS timeout: {peer}")
        except Exception as e:
            self.log(f"POS error: {peer} - {e}")
        finally:
            try:
                conn.close()
            except:
                pass
            self.log(f"Connection closed: {peer}")
            self.signals.status_changed.emit("listening", "")
    
    def run(self):
        self.running = True
        self.log("Starting Birdies Passport Hybrid Edge Agent")
        self.log(f"Store: {self.PDI_STORE_NUMBER} | Port: {self.PORT}")
        self.log(f"Backend: {self.BACKEND_URL}")
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        self.signals.status_changed.emit("listening", "")
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.HOST, self.PORT))
            self.server_socket.listen(64)
            self.server_socket.settimeout(1.0)
            self.log(f"✓ Listening on {self.HOST}:{self.PORT}")
            while self.running:
                try:
                    conn, addr = self.server_socket.accept()
                    threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue
        except Exception as e:
            self.log(f"Server error: {e}")
            self.signals.status_changed.emit("error", str(e))
        finally:
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass
    
    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        self.wait(2000)

# =============================================================================
# SETUP WIZARD
# =============================================================================

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Birdies Passport Hybrid - Setup")
        self.setFixedSize(500, 400)
        self.addPage(self.create_welcome_page())
        self.addPage(self.create_config_page())
        self.addPage(self.create_finish_page())
    
    def create_welcome_page(self):
        page = QWizardPage()
        page.setTitle("Welcome to Birdies Passport Hybrid")
        layout = QVBoxLayout()
        label = QLabel("This wizard will help you configure the Passport edge agent for your store.\n\nFeatures:\n  - Promotions (2-for-$X, Buy X Get Y Free, Amount Off)\n  - Punch Cards (Buy N, Get 1 Free)\n  - Points Redemption (10,000 pts = $1.00)\n\nClick Next to continue.")
        label.setWordWrap(True)
        layout.addWidget(label)
        page.setLayout(layout)
        return page
    
    def create_config_page(self):
        page = QWizardPage()
        page.setTitle("Configuration")
        layout = QFormLayout()
        self.store_number_edit = QLineEdit("")
        self.store_number_edit.setPlaceholderText("e.g. 1340")
        layout.addRow("PDI Store Number:", self.store_number_edit)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(9000)
        layout.addRow("TCP Port:", self.port_spin)
        self.host_ip_edit = QLineEdit("0.0.0.0")
        layout.addRow("Host IP:", self.host_ip_edit)
        page.setLayout(layout)
        return page
    
    def create_finish_page(self):
        page = QWizardPage()
        page.setTitle("Setup Complete")
        layout = QVBoxLayout()
        label = QLabel("Configuration saved!\n\nThe edge agent will start automatically.\nYou can access it from the system tray.")
        label.setWordWrap(True)
        layout.addWidget(label)
        page.setLayout(layout)
        return page
    
    def get_config(self):
        return {
            "host_ip": self.host_ip_edit.text().strip() or "0.0.0.0",
            "port": self.port_spin.value(),
            "pdi_store_number": self.store_number_edit.text().strip() or "1340",
        }

# =============================================================================
# MAIN WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(f"Birdies Passport Hybrid - Store {config.get('pdi_store_number', '1340')}")
        self.setMinimumSize(700, 500)
        self.signals = EdgeAgentSignals()
        self.worker = None
        self.setup_ui()
        self.setup_tray()
        self.signals.log_message.connect(self.append_log)
        self.signals.status_changed.connect(self.update_status)
        self.signals.heartbeat_sent.connect(self.update_heartbeat)
        self.start_worker()
    
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        status_group = QGroupBox("Status")
        status_layout = QHBoxLayout()
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.update_indicator("gray")
        status_layout.addWidget(self.status_indicator)
        self.status_label = QLabel("Starting...")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        self.heartbeat_label = QLabel("Last heartbeat: --")
        status_layout.addWidget(self.heartbeat_label)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        config_group = QGroupBox("Configuration")
        config_layout = QFormLayout()
        config_layout.addRow("Store:", QLabel(self.config.get("pdi_store_number", "1340")))
        config_layout.addRow("Port:", QLabel(str(self.config.get("port", 9000))))
        config_layout.addRow("Host:", QLabel(self.config.get("host_ip", "0.0.0.0")))
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        btn_layout = QHBoxLayout()
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.clicked.connect(self.restart_worker)
        btn_layout.addWidget(self.restart_btn)
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(lambda: self.log_text.clear())
        btn_layout.addWidget(self.clear_log_btn)
        btn_layout.addStretch()
        self.hide_btn = QPushButton("Hide to Tray")
        self.hide_btn.clicked.connect(self.hide)
        btn_layout.addWidget(self.hide_btn)
        layout.addLayout(btn_layout)
    
    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#1E3A8A"))
        painter = QPainter(pixmap)
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 16, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "B")
        painter.end()
        self.tray_icon.setIcon(QIcon(pixmap))
        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()
    
    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.activateWindow()
    
    def update_indicator(self, color):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 16, 16)
        painter.end()
        self.status_indicator.setPixmap(pixmap)
    
    def append_log(self, msg):
        self.log_text.append(msg)
    
    def update_status(self, status, detail):
        if status == "listening":
            self.status_label.setText("Listening for POS connections...")
            self.update_indicator("green")
        elif status == "connected":
            self.status_label.setText(f"Connected: {detail}")
            self.update_indicator("blue")
        elif status == "error":
            self.status_label.setText(f"Error: {detail}")
            self.update_indicator("red")
        else:
            self.status_label.setText(status)
            self.update_indicator("gray")
    
    def update_heartbeat(self, time_str):
        self.heartbeat_label.setText(f"Last heartbeat: {time_str}")
    
    def start_worker(self):
        self.worker = EdgeAgentWorker(self.config, self.signals)
        self.worker.start()
    
    def restart_worker(self):
        if self.worker:
            self.worker.stop()
        self.start_worker()
    
    def quit_app(self):
        if self.worker:
            self.worker.stop()
        self.tray_icon.hide()
        QApplication.quit()
    
    def closeEvent(self, event):
        event.ignore()
        self.hide()

# =============================================================================
# MAIN
# =============================================================================

def main():
    app = QApplication(sys.argv)
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
