#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Birdies Loyalty Edge Agent - LANHAM HYBRID GUI (REWRITTEN)
=========================================================

This is a cleaned + corrected rewrite of your GUI version so it behaves like
your working CLI agent in the punch/promo/loyalty parts.

Key fixes vs your old GUI:
  ✅ Honors backend punch-card `rewardReady` (when present).
  ✅ Only redeems punch rewards if the reward actually appears in Finalize XML.
  ✅ Applies FREE-UNIT adjustments before /record-purchase so you don't earn punches on free items.
  ✅ Uses the same reward triggering math as your CLI agent.
  ✅ Keeps promotions evaluation and converts to EPS AddReward (ticket-level amountOff).
  ✅ Keeps 4-byte BE framing, PCATS namespaces, raw XML logging.
  ✅ Keeps stacking policy toggles.

Build EXE (Windows):
  pip install pyside6 requests pyinstaller
  pyinstaller --onefile --windowed --name "Birdies Lanham Hybrid" --collect-all PySide6 birdies_lanham_hybrid_gui.py
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
    QLabel, QPushButton, QTextEdit, QGroupBox, QFormLayout,
    QWizard, QWizardPage, QMessageBox, QSystemTrayIcon, QMenu, QSpinBox, QLineEdit
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont, QAction


# =============================================================================
# CONFIG / FILE PATHS
# =============================================================================

APP_TITLE = "Birdies Lanham Hybrid Agent"

def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_config_path() -> str:
    return os.path.join(get_app_dir(), "birdies_lanham_hybrid_config.json")

def get_log_path() -> str:
    return os.path.join(get_app_dir(), "birdies_lanham_hybrid_raw_log.txt")

CONFIG_FILE = get_config_path()

def load_config() -> Optional[dict]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# =============================================================================
# RAW LOGGER
# =============================================================================

class RawLogger:
    def __init__(self):
        self.log_path = get_log_path()
        self.lock = threading.Lock()

    def log(self, direction: str, content: str) -> None:
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
# SESSION / DATA CLASSES
# =============================================================================

@dataclass
class PunchRewardSent:
    punch_card_id: int
    punch_card_name: str
    reward_id: str
    reward_type: str  # free_item / amount_off / percent_off
    free_line_no: int = 0
    free_upc: str = ""
    free_units: int = 0

@dataclass
class FreeUnitAdjustment:
    punch_card_id: int
    punch_card_name: str
    reward_id: str
    line_no: int
    upc: str
    free_units: int = 1

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
# SIGNALS
# =============================================================================

class EdgeAgentSignals(QObject):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    heartbeat_sent = Signal(str)


# =============================================================================
# CORE LOGIC (shared helpers)
# =============================================================================

def pretty_xml(xml_bytes: bytes) -> str:
    try:
        return minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        try:
            return xml_bytes.decode("utf-8", errors="replace")
        except Exception:
            return str(xml_bytes)

def strip_namespaces(elem: ET.Element) -> ET.Element:
    for e in elem.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return elem

def is_masked(val: str) -> bool:
    return bool(val) and ("*" in val)

def normalize_upc(code: str) -> str:
    return (code or "").strip()

def to_float(x) -> float:
    try:
        return float(x or 0)
    except Exception:
        return 0.0

def get_unit_price(it: dict) -> float:
    for k in ("unit_price", "actual_price", "regular_price", "price"):
        v = to_float(it.get(k, 0))
        if v > 0:
            return v
    return 0.0

def finalize_has_reward_anywhere(root: ET.Element, reward_id: str) -> bool:
    if not reward_id:
        return False
    for node in root.findall(".//LoyaltyRewardID"):
        if (node.text or "").strip() == reward_id:
            return True
    return False

def remap_free_adjustments_to_finalize(final_items: list, adjustments: List[FreeUnitAdjustment]) -> List[FreeUnitAdjustment]:
    existing_lines = {int(it.get("line_no", 0) or 0) for it in final_items}
    by_upc: Dict[str, List[dict]] = {}
    for it in final_items:
        upc = (it.get("upc") or "").strip()
        if upc:
            by_upc.setdefault(upc, []).append(it)

    remapped: List[FreeUnitAdjustment] = []
    for adj in adjustments:
        if adj.line_no in existing_lines:
            remapped.append(adj)
            continue
        cand = by_upc.get((adj.upc or "").strip(), [])
        if not cand:
            continue
        best = min(cand, key=lambda x: to_float(x.get("price", 0)))
        remapped.append(
            FreeUnitAdjustment(
                punch_card_id=adj.punch_card_id,
                punch_card_name=adj.punch_card_name,
                reward_id=adj.reward_id,
                line_no=int(best.get("line_no", 0) or 0),
                upc=adj.upc,
                free_units=adj.free_units,
            )
        )
    return remapped

def adjust_items_for_record_purchase(final_items: list, adjustments: List[FreeUnitAdjustment]) -> list:
    """
    Split a line into paid + free pseudo-line (amount=0) so backend can avoid
    punching for free units.
    """
    free_map: Dict[int, int] = {}
    for adj in adjustments:
        free_map[adj.line_no] = free_map.get(adj.line_no, 0) + int(adj.free_units or 1)

    adjusted = []
    for it in final_items:
        ln = int(it.get("line_no", 0) or 0)
        upc = (it.get("upc") or "").strip()
        if not upc:
            adjusted.append(it)
            continue

        qty_int = int(to_float(it.get("quantity", 1)))
        if qty_int <= 0:
            adjusted.append(it)
            continue

        free_qty = int(free_map.get(ln, 0) or 0)
        if free_qty <= 0:
            adjusted.append(it)
            continue

        free_qty = max(0, min(free_qty, qty_int))
        paid_qty = qty_int - free_qty

        orig_amt = to_float(it.get("amount", 0))
        unit_price = get_unit_price(it)

        if unit_price > 0:
            free_value = unit_price * free_qty
            paid_amt = max(0.0, round(orig_amt - free_value, 2))
        else:
            paid_amt = round(orig_amt * (paid_qty / max(1, qty_int)), 2)

        if paid_qty > 0:
            paid = dict(it)
            paid["quantity"] = float(paid_qty)
            paid["amount"] = paid_amt
            adjusted.append(paid)

        free = dict(it)
        free["quantity"] = float(free_qty)
        free["amount"] = 0.0
        adjusted.append(free)

    return adjusted


# =============================================================================
# WORKER THREAD (TCP server + PCATS handling)
# =============================================================================

class EdgeAgentWorker(QThread):
    def __init__(self, config: dict, signals: EdgeAgentSignals):
        super().__init__()
        self.cfg = config
        self.signals = signals
        self.running = False
        self.server_socket = None

        # ---- Network
        self.HOST = config.get("host_ip", "0.0.0.0")
        self.PORT = int(config.get("port", 9000))
        self.EXPECTED_EPS_IP = config.get("expected_eps_ip") or None

        # ---- Store / IDs
        self.PDI_STORE_NUMBER = str(config.get("store_number", "0300")).strip() or "0300"
        self.POS_ID = str(config.get("pos_id", "24379"))
        self.POS_TYPE = "Verifone-EPS"

        # ---- Backend
        self.BACKEND_URL = config.get("backend_url", "https://salmanloyalty.replit.app")
        self.REQUEST_TIMEOUT = (3, 5)
        self.SESSION_HTTP = requests.Session()
        self.HEARTBEAT_INTERVAL = int(config.get("heartbeat_interval", 15))

        # ---- Vendor / Interface
        self.VENDOR_NAME = "BirdiesLoyalty"
        self.VENDOR_VER = "1.0"
        self.DEFAULT_IFACE_VER = "1.1"

        # ---- Loyalty config
        self.POINTS_PER_DOLLAR = int(config.get("points_per_dollar", 10000))  # 10k = $1.00
        self.REWARD_ID = "DEMO-1OFF"
        self.RECEIPT_SHORT = "$OFF"
        self.RECEIPT_LONG = "Loyalty Discount"
        self.PUNCH_REWARD_ID = "PUNCH-REWARD"

        # ---- Stacking policy
        self.PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS = bool(config.get("promo_first_disable_loyalty_discounts", False))
        self.DISABLE_EARNING_WHEN_PROMO = bool(config.get("disable_earning_when_promo", False))

        # ---- Sessions
        self.SESSIONS: Dict[str, TxnSession] = {}
        self.SESSION_TTL_SECONDS = 10 * 60

    # ------------------ logging ------------------

    def log(self, msg: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.signals.log_message.emit(f"[{ts}] {msg}")

    # ------------------ framing ------------------

    def send_xml(self, conn: socket.socket, xml_str: str) -> None:
        xml_bytes = xml_str.encode("utf-8")
        frame = struct.pack(">I", len(xml_bytes)) + xml_bytes
        conn.sendall(frame)
        RAW_LOGGER.log("SENT TO EPS", pretty_xml(xml_bytes))

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

    def parse_xml(self, xml_bytes: bytes) -> ET.Element:
        RAW_LOGGER.log("RECEIVED FROM EPS", pretty_xml(xml_bytes))
        raw = xml_bytes.decode("utf-8", errors="replace")
        root = ET.fromstring(raw)
        root = strip_namespaces(root)
        return root

    # ------------------ misc helpers ------------------

    def cleanup_sessions(self) -> None:
        now = time.time()
        expired = [k for k, s in self.SESSIONS.items() if (now - s.last_seen_at) > self.SESSION_TTL_SECONDS]
        for k in expired:
            del self.SESSIONS[k]
        if expired:
            self.log(f"Cleaned up {len(expired)} expired session(s)")

    def get_req_ids(self, root: ET.Element) -> Tuple[str, str]:
        pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
        loy_seq = root.findtext(".//LoyaltySequenceID")
        if not loy_seq or not loy_seq.strip():
            loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
        return pos_seq, loy_seq.strip()

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

    # ------------------ backend calls ------------------

    def send_backend_heartbeat(self, pos_ip: Optional[str] = None) -> None:
        try:
            payload = {
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "posId": self.POS_ID,
                "posType": self.POS_TYPE,
                "posIpAddress": pos_ip,
                "edgeIpAddress": self.HOST,
                "edgeVersion": "birdies-lanham-hybrid-gui-rewrite-1.0",
            }
            r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/heartbeat", json=payload, timeout=self.REQUEST_TIMEOUT)
            if r.status_code == 200:
                self.signals.heartbeat_sent.emit(datetime.datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    def backend_customer_lookup(self, loyalty_id: str, phone: str) -> Optional[dict]:
        payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
        r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/customer-lookup", json=payload, timeout=self.REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        raise RuntimeError(f"customer-lookup failed: {r.status_code}")

    def evaluate_promotions_backend(self, items: list) -> list:
        # Match your existing contract: group by "upc" field (which is POSCode/PLU in EPS flows)
        if not items:
            return []

        upc_groups = {}
        for it in items:
            upc = it.get("upc", "")
            if not upc:
                continue
            if upc not in upc_groups:
                upc_groups[upc] = {"upc": upc, "quantity": 0.0, "price": to_float(it.get("price", 0))}
            upc_groups[upc]["quantity"] += to_float(it.get("quantity", 1))

        if not upc_groups:
            return []

        payload = {"pdiStoreNumber": self.PDI_STORE_NUMBER, "items": list(upc_groups.values())}

        try:
            r = self.SESSION_HTTP.post(f"{self.BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=self.REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json().get("promotions", []) or []
        except Exception:
            pass
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

    def finalize_transaction_backend(self, customer_id: int, eligible_subtotal: float, transaction_id: str,
                                     line_items: list, promotions: list, promotion_discount: float, points_redeemed: int) -> None:
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
                self.log(f"Finalize OK: pointsEarned={data.get('pointsEarned', 0)} newBalance={data.get('newBalance', 0)}")
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
        except Exception:
            pass
        return {"punchCards": []}

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
        except Exception:
            pass
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
        except Exception:
            pass
        return {}

    # ------------------ basket parsing ------------------

    def extract_line_items(self, root: ET.Element) -> List[dict]:
        """
        Extract ItemLine and MerchandiseCodeLine (normal status only).
        Keep "upc" field populated with POSCode (PLU/UPC/etc) for promo grouping.
        """
        items: List[dict] = []

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

            line_no = 0
            try:
                line_no = int(tline.findtext("./LineNumber", "0"))
            except Exception:
                line_no = 0

            psc = (il.findtext(".//PaymentSystemsProductCode") or "").strip()

            if is_item_line:
                upc_raw = (
                    il.findtext("./ItemCode/POSCode")
                    or il.findtext(".//POSCode")
                    or il.findtext(".//UPC")
                    or ""
                )
            else:
                # merch lines: store PSC in upc field so promos can still group if your backend expects it
                upc_raw = psc or (il.findtext(".//POSCode") or "")

            upc = normalize_upc(upc_raw)
            desc = (il.findtext("Description") or il.findtext("ItemDescription") or "").strip()

            qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
            atxt = il.findtext("SalesAmount") or il.findtext("ExtendedAmount")

            unit_price_txt = il.findtext("UnitPrice", "0")
            actual_price_txt = il.findtext("ActualSalesPrice", "0")
            regular_price_txt = il.findtext("RegularSellPrice", "0")

            qty = to_float(qtxt or 1.0)

            unit_price = to_float(unit_price_txt)
            actual_price = to_float(actual_price_txt)
            regular_price = to_float(regular_price_txt)

            if atxt and str(atxt).strip():
                amount = to_float(atxt)
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

    def choose_cheapest_eligible_itemline(self, items: List[dict]) -> Optional[dict]:
        eligible = []
        for it in items:
            if not it.get("is_item_line"):
                continue
            if (it.get("psc") or "").strip() == "950":
                continue
            if not (it.get("upc") or "").strip():
                continue
            if to_float(it.get("amount", 0)) <= 0:
                continue
            if get_unit_price(it) <= 0:
                continue
            eligible.append(it)
        if not eligible:
            return None
        return min(eligible, key=lambda x: get_unit_price(x))

    # ------------------ promo conversion ------------------

    def build_promotion_rewards_xml_eps(self, items: list, promotions: list) -> Tuple[List[str], List[dict], float]:
        """
        Convert promotions to EPS ticket-level amountOff AddReward.
        Computes discount based on unit prices in basket and promo terms returned by backend.
        """
        if not promotions:
            return [], [], 0.0

        upc_to_lines: Dict[str, List[dict]] = {}
        for it in items:
            upc = (it.get("upc") or "").strip()
            if upc:
                upc_to_lines.setdefault(upc, []).append(it)

        # Pick best promo per UPC if multiple
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

        add_rewards: List[str] = []
        applied_promotions: List[dict] = []
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

                take_qty = int(min(to_float(it.get("quantity", 1)), remaining_units))
                if take_qty <= 0:
                    continue

                current_price = get_unit_price(it)
                if current_price <= 0:
                    remaining_units -= take_qty
                    continue

                if disc_type == "multipack":
                    per_unit_new_price = float(data["per_unit_new_price"] or 0.0)
                    discount_per_unit = max(0.0, current_price - per_unit_new_price)
                else:
                    total_discount = float(promo.get("discount", 0.0) or 0.0)
                    discount_per_unit = min(total_discount / max(total_units_needed, 1), current_price)

                total_discount_for_promo += max(0.0, discount_per_unit * take_qty)
                remaining_units -= take_qty

            total_discount_for_promo = float(f"{total_discount_for_promo:.2f}")
            if total_discount_for_promo <= 0:
                continue

            total_discount_all += total_discount_for_promo

            add_rewards.append(
                f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{total_discount_for_promo:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PROMO</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{display_name}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip()
            )

            applied = dict(promo)
            applied["discount"] = total_discount_for_promo
            applied["name"] = display_name
            applied_promotions.append(applied)

        return add_rewards, applied_promotions, float(f"{total_discount_all:.2f}")

    # ------------------ response builders ------------------

    def build_online_status_response(self, root: ET.Element, pos_ip: str) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        self.send_backend_heartbeat(pos_ip)
        return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

    def build_end_period_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        return f"""<ns3:EndPeriodResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns4:Result><Success/></ns4:Result>
</ns3:EndPeriodResponse>"""

    def build_cancel_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        if loy_seq in self.SESSIONS:
            del self.SESSIONS[loy_seq]
        return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:CancelTransactionResponse>"""

    def build_get_rewards_response(self, root: ET.Element) -> str:
        self.cleanup_sessions()
        pos_seq, loy_seq = self.get_req_ids(root)
        iface_ver = self.get_iface_ver(root)
        txn_id = self.get_pos_transaction_id(root)

        loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
        phone = (root.findtext(".//PhoneNumber") or "").strip()

        # If masked follow-up and we have a session customer, reuse it
        sess = self.SESSIONS.get(loy_seq)
        if is_masked(loyalty_id) and sess and sess.customer:
            # keep the masked behavior but keep digits safe
            loyalty_id = sess.customer.get("loyaltyId") or ""
            phone = sess.customer.get("phone") or ""

        digits = "".join(ch for ch in loyalty_id if ch.isdigit())
        if len(digits) == 10 and not is_masked(loyalty_id):
            phone = digits
            loyalty_id = ""

        items = self.extract_line_items(root)
        if items:
            self.log(f"🛒 ITEMS ({len(items)}) txn={txn_id} loy={loy_seq}")
            for it in items:
                self.log(f"  Line {it['line_no']} code={it['upc']} qty={it['quantity']} amt=${to_float(it['amount']):.2f}")

        # Ensure session exists
        if not sess:
            sess = TxnSession(loy_seq=loy_seq, iface_ver=iface_ver)
            self.SESSIONS[loy_seq] = sess
        sess.last_seen_at = time.time()
        sess.iface_ver = iface_ver
        sess.last_points_recommended = 0.0
        sess.punch_rewards_sent = []
        sess.promotions_applied = []
        sess.promo_discount_total = 0.0
        sess.promo_applied_flag = False

        # ---- PROMOS FIRST (always evaluate)
        promotions = self.evaluate_promotions_backend(items)
        promo_rewards, applied_promos, promo_discount = self.build_promotion_rewards_xml_eps(items, promotions)
        sess.promotions_applied = applied_promos
        sess.promo_discount_total = promo_discount
        sess.promo_applied_flag = bool(promo_rewards)

        # Guest (no ID) still gets promos
        if not loyalty_id and not phone:
            reward_actions = (
                "<ns3:RewardActions>\n" + "\n".join(promo_rewards) + "\n</ns3:RewardActions>"
                if promo_rewards else "<ns3:RewardActions/>"
            )
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="yes">Guest</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

        # ---- Customer lookup
        try:
            customer = self.backend_customer_lookup(loyalty_id, phone)
        except Exception as e:
            self.log(f"⚠ customer-lookup error: {e}")
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

        if not customer:
            # still return promos (if any)
            reward_actions = (
                "<ns3:RewardActions>\n" + "\n".join(promo_rewards) + "\n</ns3:RewardActions>"
                if promo_rewards else "<ns3:RewardActions/>"
            )
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

        sess.customer = customer
        customer_id = int(customer.get("customerId") or 0)
        points_balance = int(customer.get("pointsBalance", 0) or 0)

        # ---- Decide loyalty discounts allowed
        loyalty_discounts_allowed = True
        if self.PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS and sess.promo_applied_flag:
            loyalty_discounts_allowed = False

        loyalty_reward_xmls: List[str] = []

        if loyalty_discounts_allowed:
            # ---- Punch cards
            punch_eval = self.evaluate_punch_cards(customer_id, items) if (customer_id and items) else {"punchCards": []}
            punch_cards = punch_eval.get("punchCards", []) or []

            for pc in punch_cards:
                # ✅ Match CLI behavior: if backend provides rewardReady and it's false, skip
                if "rewardReady" in pc and not bool(pc.get("rewardReady")):
                    continue

                current = int(pc.get("currentPunches", 0) or 0)
                basket = int(pc.get("punchesFromBasket", 0) or 0)
                required = int(pc.get("punchesRequired", 0) or 0)
                punches_needed = max(0, required - current)

                already_full_before = (required > 0 and current >= required)
                buying_extra = (basket > punches_needed)
                should_apply_now = already_full_before or buying_extra

                if not should_apply_now:
                    continue

                punch_card_id = int(pc.get("punchCardId") or 0)
                punch_name = (pc.get("punchCardName") or "Punch Card").strip()
                reward_type = (pc.get("rewardType") or "free_item").strip()
                reward_value = pc.get("rewardValue") or "0"
                reward_id = f"{self.PUNCH_REWARD_ID}-{punch_card_id}"

                if reward_type == "free_item":
                    chosen = self.choose_cheapest_eligible_itemline(items)
                    if not chosen:
                        continue
                    line_no = int(chosen.get("line_no", 0) or 0)
                    unit_price = get_unit_price(chosen)
                    if line_no <= 0 or unit_price <= 0:
                        continue

                    loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>{line_no}</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{unit_price:.2f}</ns3:RewardValue>
    <ns3:RewardLimit type="quantity">1</ns3:RewardLimit>
    <ns3:RewardReceiptDescShort>FREE</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{punch_name} FREE ITEM</ns3:RewardReceiptDescLong>
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

                elif reward_type in ("dollar_off", "amount_off"):
                    amt = to_float(reward_value)
                    if amt <= 0:
                        continue
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

                elif reward_type == "percent_off":
                    pct = to_float(reward_value)
                    if pct <= 0:
                        continue
                    subtotal = sum(to_float(it.get("amount", 0)) for it in items)
                    amt = max(0.0, subtotal * (pct / 100.0))
                    if amt <= 0:
                        continue

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

            # ---- Points redemption
            eligible_subtotal = sum(to_float(it.get("amount", 0)) for it in items)
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

        # Combine reward actions
        reward_xmls: List[str] = []
        if promo_rewards:
            reward_xmls.extend(promo_rewards)
        if loyalty_reward_xmls:
            reward_xmls.extend(loyalty_reward_xmls)

        reward_actions = (
            "<ns3:RewardActions>\n" + "\n".join(reward_xmls) + "\n</ns3:RewardActions>"
            if reward_xmls else "<ns3:RewardActions/>"
        )

        display_id = phone or loyalty_id or ""
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
            # no state -> respond OK
            return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

        sess.last_seen_at = time.time()

        final_items = self.extract_line_items(root)
        eligible_subtotal = sum(to_float(it.get("amount", 0)) for it in final_items)

        if not sess.customer:
            self.SESSIONS.pop(loy_seq, None)
            return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

        customer_id = int(sess.customer.get("customerId") or 0)

        dollars_off = float(sess.last_points_recommended or 0.0)
        points_redeemed = int(round(dollars_off * self.POINTS_PER_DOLLAR)) if dollars_off > 0 else 0

        promo_discount = float(sess.promo_discount_total or 0.0)
        promo_applied = bool(sess.promo_applied_flag)

        self.log(f"🏁 FINALIZE txn={txn_id} customer={customer_id} subtotal=${eligible_subtotal:.2f} promoApplied={promo_applied} promoDiscount=${promo_discount:.2f}")

        # finalize points/promo accounting
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

            # ✅ Only consider punch rewards that actually appear in Finalize XML
            applied_punch_rewards: List[PunchRewardSent] = []
            for pr in sess.punch_rewards_sent:
                if finalize_has_reward_anywhere(root, pr.reward_id):
                    applied_punch_rewards.append(pr)

            # ✅ Free-unit adjustments for record-purchase
            free_adjustments: List[FreeUnitAdjustment] = []
            for pr in applied_punch_rewards:
                if pr.reward_type == "free_item" and pr.free_line_no > 0 and pr.free_upc:
                    free_adjustments.append(
                        FreeUnitAdjustment(
                            punch_card_id=pr.punch_card_id,
                            punch_card_name=pr.punch_card_name,
                            reward_id=pr.reward_id,
                            line_no=pr.free_line_no,
                            upc=pr.free_upc,
                            free_units=pr.free_units or 1,
                        )
                    )

            if free_adjustments:
                free_adjustments = remap_free_adjustments_to_finalize(final_items, free_adjustments)

            record_items = final_items
            if free_adjustments:
                record_items = adjust_items_for_record_purchase(final_items, free_adjustments)

            punch_result = self.record_punches(customer_id, record_items, txn_id)
            punches_recorded = punch_result.get("punchesRecorded", []) if isinstance(punch_result, dict) else []
            if punches_recorded:
                for p in punches_recorded:
                    self.log(f" 🎯 PUNCH: {p.get('punchCardName')}: +{p.get('punchesAdded')} -> {p.get('currentPunches')}/{p.get('punchesRequired')}")

            # ✅ Redeem only applied rewards
            redeemed_ids = set()
            for pr in applied_punch_rewards:
                if pr.punch_card_id and pr.punch_card_id not in redeemed_ids:
                    rr = self.redeem_punch_reward(customer_id, pr.punch_card_id, txn_id)
                    if isinstance(rr, dict) and rr.get("success"):
                        self.log(f" 🎁 Redeemed: {pr.punch_card_name} (id={pr.punch_card_id})")
                    redeemed_ids.add(pr.punch_card_id)

        self.SESSIONS.pop(loy_seq, None)

        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

    # ------------------ server loop ------------------

    def heartbeat_loop(self):
        while self.running:
            self.send_backend_heartbeat()
            time.sleep(self.HEARTBEAT_INTERVAL)

    def handle_client(self, conn: socket.socket, addr):
        peer = f"{addr[0]}:{addr[1]}"
        self.log(f"🔌 EPS connected from {peer}")

        if self.EXPECTED_EPS_IP and addr[0] != self.EXPECTED_EPS_IP:
            self.log(f"⚠ Rejecting {addr[0]} (expected {self.EXPECTED_EPS_IP})")
            try:
                conn.close()
            except Exception:
                pass
            return

        self.send_backend_heartbeat(addr[0])

        try:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass

        try:
            conn.settimeout(5.0)
            while self.running:
                frame = self.recv_frame(conn)
                if not frame:
                    continue

                try:
                    root = self.parse_xml(frame)
                except Exception as e:
                    self.log(f"⚠ XML parse error: {e}")
                    continue

                tag = (root.tag or "").strip()
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
                    pos_seq, loy_seq = self.get_req_ids(root)
                    iface_ver = self.get_iface_ver(root)
                    resp = f"""<ns3:UnknownResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:UnknownResponse>"""

                self.send_xml(conn, resp)

        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            self.log(f"⚠ Client error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
            self.log(f"🔌 EPS disconnected: {peer}")

    def run(self):
        self.running = True
        self.signals.status_changed.emit("Starting...", "yellow")

        threading.Thread(target=self.heartbeat_loop, daemon=True).start()

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(1.0)
            self.server_socket.bind((self.HOST, self.PORT))
            self.server_socket.listen(64)

            self.log(f"✅ Listening on {self.HOST}:{self.PORT} | Store {self.PDI_STORE_NUMBER}")
            self.log(f"Backend: {self.BACKEND_URL}")
            self.log(f"Policy: promoFirstDisableLoyaltyDiscounts={self.PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS}, disableEarningWhenPromo={self.DISABLE_EARNING_WHEN_PROMO}")
            self.signals.status_changed.emit("Online - Waiting for EPS", "green")

            while self.running:
                try:
                    conn, addr = self.server_socket.accept()
                    threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue

        except Exception as e:
            self.log(f"❌ Server error: {e}")
            self.signals.status_changed.emit(f"Error: {e}", "red")
        finally:
            try:
                if self.server_socket:
                    self.server_socket.close()
            except Exception:
                pass
            self.signals.status_changed.emit("Stopped", "gray")

    def stop(self):
        self.running = False
        try:
            if self.server_socket:
                self.server_socket.close()
        except Exception:
            pass


# =============================================================================
# SETUP WIZARD
# =============================================================================

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_TITLE} - Setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(520, 420)

        self.addPage(self.page_welcome())
        self.addPage(self.page_network())
        self.addPage(self.page_store())
        self.addPage(self.page_finish())

    def page_welcome(self):
        page = QWizardPage()
        page.setTitle("Welcome")
        page.setSubTitle("Configure the Birdies Lanham Hybrid Edge Agent (Rewritten)")

        layout = QVBoxLayout()
        lbl = QLabel(
            "This edge agent provides:\n"
            "• Promotions (ticket-level amountOff)\n"
            "• Punch cards (free item / amount off / percent off)\n"
            "• Points redemption (ticket-level amountOff)\n\n"
            "Important fixes in this rewrite:\n"
            "• Honors rewardReady\n"
            "• Redeems only applied rewards\n"
            "• Avoids giving punches on free items\n"
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        layout.addStretch()
        page.setLayout(layout)
        return page

    def page_network(self):
        page = QWizardPage()
        page.setTitle("Network")
        page.setSubTitle("Host IP and Port")

        layout = QFormLayout()

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g., 10.96.10.175")
        layout.addRow("Host IP:", self.host_input)

        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(9000)
        layout.addRow("Port:", self.port_input)

        page.setLayout(layout)
        return page

    def page_store(self):
        page = QWizardPage()
        page.setTitle("Store")
        page.setSubTitle("Store settings")

        layout = QFormLayout()

        self.store_input = QLineEdit()
        self.store_input.setPlaceholderText("e.g., 0300")
        layout.addRow("PDI Store Number:", self.store_input)

        self.backend_input = QLineEdit()
        self.backend_input.setPlaceholderText("https://salmanloyalty.replit.app")
        self.backend_input.setText("https://salmanloyalty.replit.app")
        layout.addRow("Backend URL:", self.backend_input)

        page.setLayout(layout)
        return page

    def page_finish(self):
        page = QWizardPage()
        page.setTitle("Finish")
        page.setSubTitle("Save config and start")
        layout = QVBoxLayout()
        lbl = QLabel("Click Finish to save configuration and launch the agent.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        layout.addStretch()
        page.setLayout(layout)
        return page

    def get_config(self) -> dict:
        return {
            "host_ip": self.host_input.text().strip() or "0.0.0.0",
            "port": int(self.port_input.value()),
            "store_number": self.store_input.text().strip() or "0300",
            "backend_url": self.backend_input.text().strip() or "https://salmanloyalty.replit.app",
            # Defaults you can change later in JSON:
            "promo_first_disable_loyalty_discounts": False,
            "disable_earning_when_promo": False,
            "points_per_dollar": 10000,
            "heartbeat_interval": 15,
        }


# =============================================================================
# MAIN WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.worker: Optional[EdgeAgentWorker] = None
        self.signals = EdgeAgentSignals()

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(780, 560)

        self._build_ui()
        self._build_tray()
        self._connect_signals()

        QTimer.singleShot(400, self.start_agent)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel(APP_TITLE)
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #1E3A8A;")
        header.addWidget(title)
        header.addStretch()

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(18, 18)
        self.status_dot.setStyleSheet("background-color: #6b7280; border-radius: 9px;")
        header.addWidget(self.status_dot)

        self.status_label = QLabel("Starting...")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        cfg_box = QGroupBox("Configuration")
        cfg_form = QFormLayout()
        cfg_form.addRow("Host IP:", QLabel(self.config.get("host_ip", "")))
        cfg_form.addRow("Port:", QLabel(str(self.config.get("port", 9000))))
        cfg_form.addRow("Store:", QLabel(self.config.get("store_number", "")))
        cfg_form.addRow("Backend:", QLabel(self.config.get("backend_url", "")))
        cfg_form.addRow("Points:", QLabel(f"{self.config.get('points_per_dollar', 10000)} pts = $1.00"))
        cfg_form.addRow("Policy:", QLabel(
            f"promoFirstDisableLoyaltyDiscounts={self.config.get('promo_first_disable_loyalty_discounts', False)}, "
            f"disableEarningWhenPromo={self.config.get('disable_earning_when_promo', False)}"
        ))
        cfg_box.setLayout(cfg_form)
        layout.addWidget(cfg_box)

        log_box = QGroupBox("Activity Log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas, monospace; font-size: 12px;")
        log_layout.addWidget(self.log_text)
        log_box.setLayout(log_layout)
        layout.addWidget(log_box, 1)

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
        self.hb_label = QLabel("Last heartbeat: --")
        self.hb_label.setStyleSheet("color:#666;")
        buttons.addWidget(self.hb_label)
        layout.addLayout(buttons)

    def _build_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#1E3A8A"))
        painter = QPainter(pixmap)
        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "B")
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip(APP_TITLE)

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

    def _connect_signals(self):
        self.signals.log_message.connect(self.append_log)
        self.signals.status_changed.connect(self.update_status)
        self.signals.heartbeat_sent.connect(self.update_heartbeat)

    def append_log(self, msg: str):
        self.log_text.append(msg)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_status(self, text: str, color: str):
        self.status_label.setText(text)
        colors = {"green":"#22c55e", "yellow":"#eab308", "red":"#ef4444", "gray":"#6b7280"}
        self.status_dot.setStyleSheet(f"background-color: {colors.get(color, '#6b7280')}; border-radius: 9px;")

    def update_heartbeat(self, time_str: str):
        self.hb_label.setText(f"Last heartbeat: {time_str}")

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
        path = get_log_path()
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        else:
            QMessageBox.information(self, "Raw Log", "No raw log exists yet.")

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
            APP_TITLE,
            "Agent is running in the background.",
            QSystemTrayIcon.Information,
            2000
        )

    def quit_app(self):
        self.stop_agent()
        QApplication.quit()


# =============================================================================
# ENTRYPOINT
# =============================================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setQuitOnLastWindowClosed(False)

    config = load_config()
    if not config:
        wiz = SetupWizard()
        if wiz.exec() == QWizard.Accepted:
            config = wiz.get_config()
            save_config(config)
        else:
            sys.exit(0)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
