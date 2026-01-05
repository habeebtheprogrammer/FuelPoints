#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - VERIFONE PUNCH CARD GUI
=====================================================
GUI wrapper for the Verifone EPS Punch Card Edge Agent.
Features:
  - Setup wizard for IP, Port, PDI Store Number
  - Real-time status dashboard
  - System tray support
  - Raw interaction logging to text file

PUNCH CARDS ONLY - No promotions.

EPS / PCATS REQUIREMENTS:
  - TCP framing: 4-byte BIG-ENDIAN length prefix + UTF-8 XML payload
  - ResponseHeader overallResult="success" on success
  - RewardDiscountMethod: amountOff ONLY
  - PCATS namespaces required

Build EXE on Windows with:
  pip install pyside6 requests pyinstaller
  pyinstaller --onefile --windowed --name "Birdies Verifone Punch" --collect-all PySide6 verifone_punch_gui.py

Version: 1.0
"""

import sys
import os
import json
import socket
import threading
import datetime
import struct
import uuid
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

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
    return os.path.join(get_app_dir(), "birdies_verifone_punch_config.json")

def get_log_path():
    return os.path.join(get_app_dir(), "birdies_verifone_punch_raw_log.txt")

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
# EDGE AGENT SIGNALS
# =============================================================================

class EdgeAgentSignals(QObject):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    heartbeat_sent = Signal(str)

# =============================================================================
# SESSION STATE
# =============================================================================

class SessionState:
    def __init__(self):
        self.current_customer = None
        self.last_punch_cards = []
        self.last_punches_to_record = []
        self.last_points_recommended = 0.0

    def reset(self):
        self.__init__()

# =============================================================================
# EDGE AGENT WORKER
# =============================================================================

class EdgeAgentWorker(QThread):
    def __init__(self, config, signals):
        super().__init__()
        self.config = config
        self.signals = signals
        self.running = False
        self.server_socket = None
        self.session_lock = threading.Lock()
        
        self.SESSION = requests.Session()
        self.REQUEST_TIMEOUT = (3, 5)
        
        self.HOST = config.get("host_ip", "0.0.0.0")
        self.PORT = int(config.get("port", 9000))
        self.PDI_STORE_NUMBER = config.get("store_number", "")
        self.POS_TYPE = "Verifone-EPS"
        self.BACKEND_URL = "https://salmanloyalty.replit.app"
        
        self.VENDOR_NAME = "BirdiesLoyalty"
        self.VENDOR_VER = "1.0"
        self.IFACE_VER = "1.0"
        
        self.PUNCH_REWARD_PREFIX = "PUNCH"
        self.POINTS_REWARD_ID = "DEMO-1OFF"
        self.POINTS_PER_DOLLAR = 999999  # High to disable points during testing

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.signals.log_message.emit(f"[{ts}] {msg}")

    def run(self):
        self.running = True
        self.signals.status_changed.emit("Starting...", "yellow")
        
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(1.0)
            self.server_socket.bind((self.HOST, self.PORT))
            self.server_socket.listen(64)
            
            self.log(f"Listening on {self.HOST}:{self.PORT}")
            self.log(f"Store: {self.PDI_STORE_NUMBER}")
            self.log("Mode: PUNCH CARDS ONLY (No Promotions)")
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

    # =========================================================================
    # EPS FRAMING: 4-byte BIG-ENDIAN length + UTF-8 XML
    # =========================================================================

    def send_xml(self, conn: socket.socket, xml_str: str):
        xml_bytes = xml_str.encode("utf-8")
        frame = struct.pack(">I", len(xml_bytes)) + xml_bytes
        conn.sendall(frame)
        try:
            pretty = minidom.parseString(xml_bytes).toprettyxml()
        except Exception:
            pretty = xml_str
        self.log("-> Sent to EPS")
        RAW_LOGGER.log("SENT TO EPS", pretty)

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
        try:
            pretty = minidom.parseString(xml_bytes).toprettyxml()
        except Exception:
            pretty = raw
        RAW_LOGGER.log("RECEIVED FROM EPS", pretty)
        root = ET.fromstring(raw)
        return self.strip_namespaces(root), raw

    def strip_namespaces(self, elem: ET.Element) -> ET.Element:
        for e in elem.iter():
            if isinstance(e.tag, str) and "}" in e.tag:
                e.tag = e.tag.split("}", 1)[1]
        return elem

    # =========================================================================
    # HELPERS
    # =========================================================================

    def get_req_ids(self, root: ET.Element):
        pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
        loy_seq = root.findtext(".//LoyaltySequenceID")
        if not loy_seq or not loy_seq.strip():
            loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
        return pos_seq, loy_seq

    def resp_header(self, pos_seq: str, loy_seq: str, overall: str = "success") -> str:
        result_child = "<Success/>" if overall == "success" else "<Failure/>"
        return (
            f'<ns3:ResponseHeader overallResult="{overall}">'
            f'<ns3:POSLoyaltyInterfaceVersion>{self.IFACE_VER}</ns3:POSLoyaltyInterfaceVersion>'
            f'<ns2:VendorName>{self.VENDOR_NAME}</ns2:VendorName>'
            f'<ns2:VendorModelVersion>{self.VENDOR_VER}</ns2:VendorModelVersion>'
            f'<ns3:POSSequenceID>{pos_seq}</ns3:POSSequenceID>'
            f'<ns3:LoyaltySequenceID>{loy_seq}</ns3:LoyaltySequenceID>'
            f'<ns4:Result>{result_child}</ns4:Result>'
            f'</ns3:ResponseHeader>'
        )

    def receipt_short(self, s: str) -> str:
        return (s or "").strip()[:8]

    def receipt_long(self, s: str) -> str:
        return (s or "").strip()[:24]

    def receipt_line(self, s: str) -> str:
        clean = "".join(ch for ch in (s or "") if ch.isprintable())
        return clean[:40]

    def cap_amount_off(self, value: float, subtotal: float) -> float:
        if subtotal <= 0:
            return 0.0
        if value < 0:
            return 0.0
        return min(float(value), float(subtotal))

    # =========================================================================
    # LINE ITEM EXTRACTION
    # =========================================================================

    def extract_line_items(self, root: ET.Element):
        items = []
        for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
            status = (tline.get("status") or "").strip().lower()
            if status and status != "normal":
                continue

            il = tline.find("./ItemLine")
            if il is None:
                il = tline.find("./MerchandiseCodeLine")
            if il is None:
                continue

            try:
                line_no = int(tline.findtext("./LineNumber", "0"))
            except Exception:
                line_no = 0

            upc_raw = (
                il.findtext("./ItemCode/POSCode")
                or il.findtext(".//POSCode")
                or il.findtext(".//UPC")
                or il.findtext(".//PaymentSystemsProductCode")
                or ""
            ).strip()

            desc = (il.findtext("Description") or il.findtext("ItemDescription") or "").strip()
            qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
            atxt = il.findtext("SalesAmount") or il.findtext("ExtendedAmount")
            unit_price_txt = il.findtext("UnitPrice", "0")
            actual_price_txt = il.findtext("ActualSalesPrice", "0")
            regular_price_txt = il.findtext("RegularSellPrice", "0")

            def _f(x):
                try:
                    return float(x or 0)
                except Exception:
                    return 0.0

            try:
                qty = float(qtxt or 1.0)
            except Exception:
                qty = 1.0

            unit_price = _f(unit_price_txt)
            actual_price = _f(actual_price_txt)
            regular_price = _f(regular_price_txt)

            if atxt and atxt.strip():
                amount = _f(atxt)
            else:
                amount = actual_price * qty

            price = unit_price or actual_price or regular_price or 0.0

            items.append({
                "line_no": line_no,
                "upc": upc_raw,
                "description": desc,
                "quantity": qty,
                "amount": amount,
                "price": price,
            })
        return items

    def unit_amount(self, item: dict) -> float:
        qty = float(item.get("quantity", 0) or 0)
        amt = float(item.get("amount", 0) or 0)
        if qty > 0:
            return amt / qty
        return float(item.get("price", 0) or 0)

    # =========================================================================
    # BACKEND API CALLS
    # =========================================================================

    def send_heartbeat(self, pos_ip: str):
        try:
            payload = {
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "posId": "24379",
                "posType": self.POS_TYPE,
                "posIpAddress": pos_ip,
                "edgeIpAddress": self.HOST,
                "edgeVersion": "birdies-verifone-punch-gui-1.0",
            }
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/heartbeat",
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                self.signals.heartbeat_sent.emit(datetime.datetime.now().strftime("%H:%M:%S"))
        except Exception:
            pass

    def customer_lookup(self, loyalty_id: str, phone: str):
        lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/customer-lookup",
                json=lookup_payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 404:
                return None, "not_found"
            if r.status_code != 200:
                return None, "error"
            return r.json(), "ok"
        except Exception as e:
            self.log(f"Customer lookup error: {e}")
            return None, "error"

    def evaluate_punch_cards(self, customer_id: int, line_items: list) -> dict:
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/punch-cards/evaluate",
                json={"customerId": customer_id, "lineItems": line_items},
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {"punchCards": []}
        except Exception:
            return {"punchCards": []}

    def record_punches(self, customer_id: int, line_items: list, txn_id: str) -> dict:
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/punch-cards/record-purchase",
                json={
                    "customerId": customer_id,
                    "lineItems": line_items,
                    "pdiStoreNumber": self.PDI_STORE_NUMBER,
                    "transactionId": txn_id,
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            return {}

    def redeem_punch_reward(self, customer_id: int, punch_card_id: int, txn_id: str) -> dict:
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/punch-cards/redeem",
                json={
                    "customerId": customer_id,
                    "punchCardId": punch_card_id,
                    "pdiStoreNumber": self.PDI_STORE_NUMBER,
                    "transactionId": txn_id,
                },
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            return {}

    def finalize_transaction(self, customer_id: int, subtotal: float, points_redeemed: int, txn_id: str, items: list):
        payload = {
            "customerId": customer_id,
            "eligibleSubtotal": subtotal,
            "pointsRedeemed": points_redeemed,
            "transactionId": txn_id,
            "pdiStoreNumber": self.PDI_STORE_NUMBER,
            "lineItems": items,
            "promotions": [],
            "promotionDiscount": 0,
        }
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/finalize-transaction",
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            return None
        except Exception as e:
            self.log(f"Finalize error: {e}")
            return None

    # =========================================================================
    # PUNCH REWARD BUILDER
    # =========================================================================

    def build_punch_rewards_xml(self, triggered_cards: list, eligible_items: list, remaining_subtotal: float):
        if not triggered_cards or not eligible_items or remaining_subtotal <= 0:
            return [], 0.0

        rewards = []
        available = list(eligible_items)
        total_punch_discount = 0.0
        budget = float(remaining_subtotal)

        for pc in triggered_cards:
            if not available or budget <= 0:
                break

            cheapest = min(available, key=lambda it: self.unit_amount(it))
            raw_free_amt = self.unit_amount(cheapest)
            capped_free_amt = self.cap_amount_off(raw_free_amt, budget)
            
            if capped_free_amt <= 0:
                line_no = int(cheapest.get("line_no", 0) or 0)
                available = [it for it in available if int(it.get("line_no", 0) or 0) != line_no]
                continue

            name = pc.get("punchCardName", "Punch Reward")

            rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{self.PUNCH_REWARD_PREFIX}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{capped_free_amt:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>{self.receipt_short("FREE")}</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{self.receipt_long(f"{name} FREE")}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())

            pc["rewardApplied"] = True
            pc["rewardAmount"] = capped_free_amt
            budget -= capped_free_amt
            total_punch_discount += capped_free_amt
            
            line_no = int(cheapest.get("line_no", 0) or 0)
            available = [it for it in available if int(it.get("line_no", 0) or 0) != line_no]

        return rewards, total_punch_discount

    # =========================================================================
    # RESPONSE BUILDERS
    # =========================================================================

    def build_online_status_response(self, root: ET.Element, pos_ip: str) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        self.send_heartbeat(pos_ip)
        return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

    def build_get_rewards_response(self, root: ET.Element, st: SessionState) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)

        loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
        phone = (root.findtext(".//PhoneNumber") or "").strip()
        digits = "".join(ch for ch in loyalty_id if ch.isdigit())
        if len(digits) == 10:
            phone = digits
            loyalty_id = ""

        items = self.extract_line_items(root)
        subtotal = sum(float(it.get("amount", 0) or 0) for it in items)

        if items:
            self.log(f"Transaction: {len(items)} items, subtotal ${subtotal:.2f}")

        st.last_punch_cards = []
        st.last_punches_to_record = items
        st.last_points_recommended = 0.0

        if not loyalty_id and not phone:
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

        cust, status = self.customer_lookup(loyalty_id, phone)
        if status == "not_found":
            self.log(f"Customer not found: {loyalty_id or phone}")
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
        if status != "ok" or not cust:
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

        st.current_customer = cust
        customer_id = int(cust.get("customerId") or 0)
        points = int(cust.get("pointsBalance", 0) or 0)
        first_name = cust.get("firstName", "")
        last_name = cust.get("lastName", "")
        self.log(f"Customer: {first_name} {last_name} ({points} pts)")

        display_id = loyalty_id or phone or ""
        masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

        remaining_subtotal = float(subtotal)

        punch_rewards = []
        punch_discount = 0.0
        if customer_id and items and remaining_subtotal > 0:
            pe = self.evaluate_punch_cards(customer_id, items)
            cards = pe.get("punchCards", []) or []
            triggered = []

            if cards:
                self.log("PUNCH CARD STATUS:")
                for pc in cards:
                    current = int(pc.get("currentPunches", 0) or 0)
                    basket = int(pc.get("punchesFromBasket", 0) or 0)
                    required = int(pc.get("punchesRequired", 10) or 10)
                    punches_needed = max(0, required - current)

                    status_line = f"  {pc.get('punchCardName', 'Punch Card')}: {current}/{required}"
                    if basket > 0:
                        status_line += f" (+{basket} from basket)"

                    if required > 0 and (current + basket) >= required:
                        status_line += " - REWARD TRIGGERED!"
                        pc["rewardTriggered"] = True
                        triggered.append(pc)
                    else:
                        status_line += f" (need {punches_needed} more)"

                    self.log(status_line)

            st.last_punch_cards = triggered

            reward_eligible = [
                it for it in items
                if (it.get("upc") or "").strip() and float(it.get("amount", 0) or 0) > 0 and float(it.get("price", 0) or 0) > 0
            ]
            if triggered and reward_eligible:
                punch_rewards, punch_discount = self.build_punch_rewards_xml(triggered, reward_eligible, remaining_subtotal)
                if punch_discount > 0:
                    remaining_subtotal -= punch_discount
                    self.log(f"Punch discount: ${punch_discount:.2f}")

        rewards = punch_rewards or []
        if rewards:
            self.log(f"Sending {len(rewards)} reward(s) to EPS")

        reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>" if rewards else "<ns3:RewardActions/>"

        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:LoyaltyIDValidFlag value="yes">{masked}</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

    def build_finalize_response(self, root: ET.Element, st: SessionState) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)

        raw_txn_id = (root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or "").strip()
        safe_txn_id = raw_txn_id if raw_txn_id else f"TXN-{uuid.uuid4().hex[:8].upper()}"

        items = self.extract_line_items(root)
        subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
        self.log(f"Finalize: subtotal ${subtotal:.2f}")

        receipt_lines = []

        if not st.current_customer:
            receipt_lines.append("Thank you for shopping at Birdies!")
            rec_xml = "\n".join(f"      <ns3:ReceiptLine>{self.receipt_line(line)}</ns3:ReceiptLine>" for line in receipt_lines)
            st.reset()
            return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
{rec_xml}
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:FinalizeRewardsResponse>"""

        customer_id = int(st.current_customer.get("customerId") or 0)

        data = self.finalize_transaction(
            customer_id=customer_id,
            subtotal=subtotal,
            points_redeemed=0,
            txn_id=safe_txn_id,
            items=items,
        )

        overall = "success"
        if data is None:
            overall = "timeout"
            receipt_lines.append("Loyalty finalize error")
        else:
            pts_earned = int(data.get("pointsEarned", 0) or 0)
            new_bal = int(data.get("newBalance", 0) or 0)
            self.log(f"Finalized: Earned {pts_earned} pts, Balance {new_bal}")

        if st.last_punches_to_record:
            pr = self.record_punches(customer_id, st.last_punches_to_record, safe_txn_id) or {}
            punches_recorded = pr.get("punchesRecorded", []) or []
            if punches_recorded:
                receipt_lines.append("Punches Recorded:")
                for p in punches_recorded:
                    line = f"  {p.get('punchCardName','Punch')}: +{p.get('punchesAdded',0)} ({p.get('currentPunches',0)}/{p.get('punchesRequired',0)})"
                    receipt_lines.append(line)

        for pc in (st.last_punch_cards or []):
            if pc.get("rewardApplied"):
                rr = self.redeem_punch_reward(customer_id, int(pc.get("punchCardId") or 0), safe_txn_id) or {}
                if rr.get("redeemed") or rr.get("success"):
                    receipt_lines.append(f"Punch Reward Redeemed: {pc.get('punchCardName','Punch')}")

        if not receipt_lines:
            receipt_lines.append("Thank you for shopping at Birdies!")

        rec_xml = "\n".join(f"      <ns3:ReceiptLine>{self.receipt_line(line)}</ns3:ReceiptLine>" for line in receipt_lines)
        st.reset()

        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall=overall)}
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
{rec_xml}
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:FinalizeRewardsResponse>"""

    def build_cancel_response(self, root: ET.Element, st: SessionState) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        st.reset()
        self.log("Transaction cancelled")
        return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
</ns3:CancelTransactionResponse>"""

    def build_reverse_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        self.log("Transaction reversal acknowledged")
        return f"""<ns3:ReverseTransactionResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
</ns3:ReverseTransactionResponse>"""

    def build_end_period_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        self.log("End period acknowledged")
        return f"""<ns3:EndPeriodResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
  <ns4:Result><Success/></ns4:Result>
</ns3:EndPeriodResponse>"""

    def build_customer_msg_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        return f"""<ns3:GetCustomerMessagingResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:CustomerMessageData>
    <ns3:DisplayData>
      <ns3:DisplayCommand device="POS-Cashier" sequence="WhenReceived" duration="3">
        <ns3:DisplayLine>Welcome to Birdies Loyalty!</ns3:DisplayLine>
      </ns3:DisplayCommand>
    </ns3:DisplayData>
  </ns3:CustomerMessageData>
</ns3:GetCustomerMessagingResponse>"""

    # =========================================================================
    # CLIENT HANDLER
    # =========================================================================

    def handle_client(self, conn: socket.socket, addr):
        peer = f"{addr[0]}:{addr[1]}"
        self.log(f"EPS connected from {peer}")

        if not self.session_lock.acquire(blocking=False):
            self.log(f"Another EPS session active; rejecting {peer}")
            try:
                conn.close()
            except Exception:
                pass
            return

        st = SessionState()

        try:
            conn.settimeout(180)
            while self.running:
                frame = self.recv_frame(conn)
                if not frame:
                    self.log(f"EPS disconnected: {peer}")
                    break

                try:
                    root, _raw = self.parse_xml(frame)
                except Exception as e:
                    self.log(f"XML parse error: {e}")
                    break

                tag = (root.tag or "").strip()
                self.log(f"Request: {tag}")

                if tag == "GetLoyaltyOnlineStatusRequest":
                    resp = self.build_online_status_response(root, addr[0])
                elif tag == "GetRewardsRequest":
                    resp = self.build_get_rewards_response(root, st)
                elif tag == "FinalizeRewardsRequest":
                    resp = self.build_finalize_response(root, st)
                elif tag == "CancelTransactionRequest":
                    resp = self.build_cancel_response(root, st)
                elif tag == "ReverseTransactionRequest":
                    resp = self.build_reverse_response(root)
                elif tag == "EndPeriodRequest":
                    resp = self.build_end_period_response(root)
                elif tag == "GetCustomerMessagingRequest":
                    resp = self.build_customer_msg_response(root)
                else:
                    self.log(f"Unhandled request: {tag}")
                    pos_seq, loy_seq = self.get_req_ids(root)
                    resp = f"""<ns3:UnknownResponse {NS_DECLS}>
  {self.resp_header(pos_seq, loy_seq, overall="failure")}
</ns3:UnknownResponse>"""

                self.send_xml(conn, resp)

        except socket.timeout:
            self.log(f"EPS timeout: {peer}")
        except ConnectionResetError:
            self.log(f"EPS connection reset: {peer}")
        except Exception as e:
            self.log(f"EPS error: {e}")
        finally:
            st.reset()
            self.session_lock.release()
            try:
                conn.close()
            except Exception:
                pass
            self.log(f"EPS session ended: {peer}")

# =============================================================================
# SETUP WIZARD
# =============================================================================

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Birdies Verifone Punch - Setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(500, 400)
        
        self.addPage(self.create_welcome_page())
        self.addPage(self.create_network_page())
        self.addPage(self.create_store_page())
        self.addPage(self.create_finish_page())
    
    def create_welcome_page(self):
        page = QWizardPage()
        page.setTitle("Welcome")
        page.setSubTitle("Setup the Birdies Verifone Punch Card Edge Agent")
        
        layout = QVBoxLayout()
        
        info = QLabel(
            "This wizard will configure the edge agent for your Verifone Commander/Ruby POS.\n\n"
            "Features:\n"
            "  - Punch Card Rewards (Buy 10, Get 1 Free)\n"
            "  - Verifone EPS Protocol (PCATS over TCP)\n\n"
            "Note: This version does NOT include price promotions."
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
        self.store_input.setPlaceholderText("e.g., 1340")
        layout.addRow("PDI Store Number:", self.store_input)
        
        note = QLabel(
            "\nThis is your Birdies/PDI store number."
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
            "  - Process punch card rewards\n"
            "  - Log all raw XML interactions to a text file"
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
        
        self.setWindowTitle("Birdies Verifone Punch Agent")
        self.setMinimumSize(700, 500)
        
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
        title = QLabel("Birdies Verifone Punch Agent")
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
        info_layout.addRow("Mode:", QLabel("Punch Cards Only (No Promos)"))
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
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "V")
        painter.end()
        
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Birdies Verifone Punch Agent")
        
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
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def update_status(self, text, color):
        self.status_label.setText(text)
        self.status_indicator.setStyleSheet(f"background-color: {color}; border-radius: 10px;")
    
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
            self.worker.wait(3000)
            self.worker = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def open_raw_log(self):
        log_path = get_log_path()
        if os.path.exists(log_path):
            os.startfile(log_path) if sys.platform == "win32" else os.system(f"open '{log_path}'")
        else:
            QMessageBox.information(self, "Log File", f"Log file will be created at:\n{log_path}")
    
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
            "Birdies Verifone Punch",
            "Agent minimized to tray. Right-click to quit.",
            QSystemTrayIcon.Information,
            2000
        )
    
    def quit_app(self):
        self.stop_agent()
        self.tray_icon.hide()
        QApplication.quit()

# =============================================================================
# MAIN
# =============================================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
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
