#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PASSPORT PUNCH CARD GUI
=====================================================
GUI wrapper for the Passport Punch Card Edge Agent.
Features:
  - Setup wizard for IP, Port, PDI Store Number
  - Real-time status dashboard
  - System tray support
  - Raw interaction logging to text file

NO PROMOTIONS - Just punch cards and points redemption.

Build EXE on Windows with:
  pip install pyside6 requests pyinstaller
  pyinstaller --onefile --windowed --name "Birdies Passport Punch" --collect-all PySide6 passport_punch_gui.py

Version: 1.0
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
    return os.path.join(get_app_dir(), "birdies_punch_config.json")

def get_log_path():
    return os.path.join(get_app_dir(), "birdies_punch_raw_log.txt")

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
# EDGE AGENT SIGNALS
# =============================================================================

class EdgeAgentSignals(QObject):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    heartbeat_sent = Signal(str)

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
        
        self.current_customer = None
        self.last_punch_cards = []
        self.last_punches_to_record = []
        
        self.SIGNATURE = b"POSLOYALTY\x00\x00"
        self.ACTION_MESSAGE = 1
        self.ACTION_HEARTBEAT = 2
        
        self.SESSION = requests.Session()
        self.REQUEST_TIMEOUT = (3, 5)
        
        self.HOST = config.get("host_ip", "")
        self.PORT = int(config.get("port", 9000))
        self.PDI_STORE_NUMBER = config.get("store_number", "")
        self.POS_ID = "24379"
        self.POS_TYPE = "Passport"
        self.BACKEND_URL = "https://salmanloyalty.replit.app"
        
        self.VENDOR_NAME = "DemoLoyalty"
        self.VENDOR_VER = "1.0"
        self.IFACE_VER = "1.0"
        
        self.POINTS_REWARD_ID = "DEMO-1OFF"
        self.PUNCH_REWARD_ID = "PUNCH-REWARD"
        self.RECEIPT_SHORT = "$1OFF"
        self.RECEIPT_LONG = "Loyalty $ Off"
        self.POINTS_PER_DOLLAR = 100
        self.HEARTBEAT_INTERVAL = 15

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
            self.log(f"Store: {self.PDI_STORE_NUMBER} | POS ID: {self.POS_ID}")
            self.log("Mode: PUNCH CARDS + POINTS (No Promotions)")
            self.signals.status_changed.emit("Online - Waiting for POS", "green")
            
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
            self.send_heartbeat()
            time.sleep(self.HEARTBEAT_INTERVAL)

    def send_heartbeat(self):
        try:
            payload = {
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "posId": self.POS_ID,
                "posType": self.POS_TYPE,
                "posIpAddress": "",
                "edgeIpAddress": self.HOST,
                "edgeVersion": "birdies-passport-punch-gui-1.0",
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

    # =========================================================================
    # PROTOCOL HELPERS
    # =========================================================================
    
    def crc32(self, b: bytes) -> int:
        return binascii.crc32(b) & 0xFFFFFFFF

    def pack_header(self, xml_bytes: bytes, action: int = 1) -> bytes:
        data_len = len(xml_bytes)
        chk_data = self.crc32(xml_bytes)
        head_wo_hdr_crc = self.SIGNATURE + struct.pack("<III", action, data_len, chk_data)
        chk_hdr = self.crc32(head_wo_hdr_crc)
        return head_wo_hdr_crc + struct.pack("<I", chk_hdr)

    def send_xml(self, conn: socket.socket, xml_str: str, action: int = 1):
        xml_bytes = xml_str.encode("utf-8")
        hdr = self.pack_header(xml_bytes, action)
        conn.sendall(hdr + xml_bytes)
        try:
            pretty = minidom.parseString(xml_bytes).toprettyxml()
        except Exception:
            pretty = xml_str
        self.log("-> Sent to POS")
        RAW_LOGGER.log("SENT TO POS", pretty)

    def recv_exact(self, conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return b""
            buf += chunk
        return buf

    def parse_header(self, hdr: bytes):
        if len(hdr) != 28:
            raise ValueError("short header")
        if hdr[:12] != self.SIGNATURE:
            raise ValueError("bad signature")
        action, data_len, chk_data, chk_hdr = struct.unpack("<IIII", hdr[12:28])
        if self.crc32(hdr[:24]) != chk_hdr:
            raise ValueError("header CRC mismatch")
        return action, data_len, chk_data

    def parse_xml(self, xml_bytes: bytes):
        raw = xml_bytes.decode("utf-8", errors="replace")
        try:
            pretty = minidom.parseString(xml_bytes).toprettyxml()
        except Exception:
            pretty = raw
        RAW_LOGGER.log("RECEIVED FROM POS", pretty)
        root = ET.fromstring(raw)
        return root, raw

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
                continue

            try:
                line_no = int(tline.findtext("./LineNumber", "0"))
            except Exception:
                line_no = 0

            upc_raw = (
                il.findtext("./ItemCode/POSCode")
                or il.findtext(".//POSCode")
                or il.findtext(".//UPC")
                or ""
            ).strip()

            desc = (il.findtext("Description") or "").strip()
            qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
            atxt = il.findtext("SalesAmount")
            unit_price_txt = il.findtext("UnitPrice", "0")
            actual_price_txt = il.findtext("ActualSalesPrice", "0")
            regular_price_txt = il.findtext("RegularSellPrice", "0")

            try:
                qty = float(qtxt or 1.0)
            except Exception:
                qty = 1.0

            def to_f(txt):
                try:
                    return float(txt or 0)
                except Exception:
                    return 0.0

            try:
                if atxt and atxt.strip():
                    amount = float(atxt)
                else:
                    amount = to_f(actual_price_txt) * qty
            except Exception:
                amount = 0.0

            unit_price = to_f(unit_price_txt)
            actual_price = to_f(actual_price_txt)
            regular_price = to_f(regular_price_txt)
            price = unit_price or actual_price or regular_price or 0.0

            items.append({
                "line_no": line_no,
                "upc": upc_raw,
                "description": desc,
                "quantity": qty,
                "amount": amount,
                "price": price,
                "unit_price": unit_price,
                "actual_price": actual_price,
                "regular_price": regular_price,
            })
        return items

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
                except Exception:
                    pass
        return round(dollars, 2)

    # =========================================================================
    # PUNCH CARD API CALLS
    # =========================================================================
    
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

    def record_punches(self, customer_id: int, line_items: list, transaction_id: str) -> dict:
        try:
            r = self.SESSION.post(
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
            r = self.SESSION.post(
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
    # RESPONSE BUILDERS
    # =========================================================================
    
    def build_online_status_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        return (
            "<GetLoyaltyOnlineStatusResponse>"
            f"{self.resp_header(pos_seq, loy_seq)}"
            '<PromptForLoyaltyFlag value="yes"/>'
            "</GetLoyaltyOnlineStatusResponse>"
        )

    def build_get_rewards_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)

        loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
        phone = (root.findtext(".//PhoneNumber") or "").strip()
        digits = "".join(ch for ch in loyalty_id if ch.isdigit())
        if len(digits) == 10:
            phone = digits
            loyalty_id = ""

        items = self.extract_line_items(root)
        if items:
            self.log(f"Transaction: {len(items)} items")

        self.current_customer = None
        self.last_punch_cards = []
        self.last_punches_to_record = []

        if not loyalty_id and not phone:
            return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

        lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/customer-lookup",
                json=lookup_payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 404:
                self.log(f"Customer not found: {loyalty_id or phone}")
                return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer not found</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()
            if r.status_code != 200:
                return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

            self.current_customer = r.json()
            first_name = self.current_customer.get("firstName", "")
            last_name = self.current_customer.get("lastName", "")
            points = int(self.current_customer.get("pointsBalance", 0) or 0)
            customer_id = self.current_customer.get("customerId")
            self.log(f"Customer: {first_name} {last_name} ({points} pts)")
        except Exception as e:
            self.log(f"Customer lookup error: {e}")
            return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

        display_id = loyalty_id or phone or ""
        masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"
        self.last_punches_to_record = items

        punch_rewards_xml = []
        self.last_punch_cards = []

        if customer_id and items:
            punch_eval = self.evaluate_punch_cards(customer_id, items)
            punch_cards_data = punch_eval.get("punchCards", [])

            if punch_cards_data:
                self.log("PUNCH CARD STATUS:")
                for pc in punch_cards_data:
                    current = int(pc.get("currentPunches", 0) or 0)
                    basket = int(pc.get("punchesFromBasket", 0) or 0)
                    required = int(pc.get("punchesRequired", 10) or 10)
                    punches_needed = max(0, required - current)

                    already_full = current >= required
                    buying_extra = basket > punches_needed
                    should_trigger = already_full or buying_extra

                    status_line = f"  {pc.get('punchCardName', 'Punch Card')}: {current}/{required}"
                    if basket > 0:
                        status_line += f" +{basket}"
                    if should_trigger:
                        status_line += " -> REWARD!"
                        pc["rewardTriggered"] = True
                        self.last_punch_cards.append(pc)
                    else:
                        status_line += f" (need {punches_needed})"
                    self.log(status_line)

                if self.last_punch_cards:
                    eligible_items = [
                        it for it in items
                        if it.get("upc") and it.get("amount", 0) > 0 and it.get("price", 0) > 0
                    ]

                    for pc in self.last_punch_cards:
                        if not eligible_items:
                            continue

                        cheapest = min(eligible_items, key=lambda it: it["price"])
                        line_no = cheapest["line_no"]
                        unit_price = float(cheapest["price"] or 0.0)
                        punch_card_name = pc.get("punchCardName", "Punch Reward")

                        self.log(f"  FREE ITEM on line {line_no} (${unit_price:.2f})")

                        punch_rewards_xml.append(f"""
    <AddReward>
      <LoyaltyRewardID>{self.PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>0.0000</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>FREE</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_card_name} FREE ITEM</RewardReceiptDescLong>
    </AddReward>""".rstrip())
                        pc["rewardApplied"] = True

        subtotal = sum(it["amount"] for it in items)
        points_reward_xml = ""
        if subtotal > 0 and points >= self.POINTS_PER_DOLLAR:
            try:
                rr = self.SESSION.post(
                    f"{self.BACKEND_URL}/api/pos/calculate-redemption",
                    json={
                        "customerId": customer_id,
                        "eligibleSubtotal": subtotal,
                        "lineItems": items,
                    },
                    timeout=self.REQUEST_TIMEOUT,
                )
                if rr.status_code == 200:
                    data = rr.json()
                    recommended = float(data.get("recommendedRedemption") or 0.0)
                    if recommended > 0:
                        pts_to_use = int(round(recommended * self.POINTS_PER_DOLLAR))
                        self.log(f"Points: ${recommended:.2f} ({pts_to_use} pts)")
                        points_reward_xml = f"""
    <AddReward>
      <LoyaltyRewardID>{self.POINTS_REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="no"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{recommended:.2f}</RewardValue>
      <RewardReceiptDescShort>{self.RECEIPT_SHORT}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{self.RECEIPT_LONG}</RewardReceiptDescLong>
    </AddReward>""".rstrip()
            except Exception:
                pass

        all_rewards = []
        if punch_rewards_xml:
            all_rewards.extend(punch_rewards_xml)
        if points_reward_xml:
            all_rewards.append(points_reward_xml)

        if all_rewards:
            self.log(f"Sending {len(all_rewards)} reward(s)")
            rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
        else:
            rewards_block = "<RewardActions/>"

        return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()

    def build_finalize_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        raw_txn_id = (root.findtext(".//TransactionID") or root.findtext(".//POSTransactionID") or "").strip()
        safe_txn_id = raw_txn_id if raw_txn_id else f"TXN-{uuid.uuid4().hex[:8].upper()}"

        items = self.extract_line_items(root)
        subtotal = sum(it["amount"] for it in items)

        receipt_lines = []

        if self.current_customer:
            customer_id = self.current_customer.get("customerId")
            first_name = self.current_customer.get("firstName", "")
            points = int(self.current_customer.get("pointsBalance", 0) or 0)

            points_used_dollars = self.detect_loyalty_tender(root, self.POINTS_REWARD_ID)
            pts_used = int(round(points_used_dollars * self.POINTS_PER_DOLLAR)) if points_used_dollars > 0 else 0

            if self.last_punch_cards:
                for pc in self.last_punch_cards:
                    if pc.get("rewardApplied"):
                        result = self.redeem_punch_reward(customer_id, pc.get("punchCardId"), safe_txn_id)
                        self.log(f"Redeemed punch card: {pc.get('punchCardName')}")

            if self.last_punches_to_record:
                result = self.record_punches(customer_id, self.last_punches_to_record, safe_txn_id)
                punches_added = result.get("totalPunchesRecorded", 0)
                if punches_added > 0:
                    self.log(f"Recorded {punches_added} punch(es)")

            try:
                payload = {
                    "pdiStoreNumber": self.PDI_STORE_NUMBER,
                    "posId": self.POS_ID,
                    "customerId": customer_id,
                    "transactionId": safe_txn_id,
                    "transactionTotal": subtotal,
                    "lineItems": items,
                    "pointsRedeemed": pts_used,
                    "promotions": [],
                }
                r = self.SESSION.post(
                    f"{self.BACKEND_URL}/api/pos/finalize-transaction",
                    json=payload,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if r.status_code == 200:
                    data = r.json()
                    new_pts = data.get("newPointsBalance", points)
                    earned = data.get("pointsEarned", 0)
                    self.log(f"Finalized: earned {earned} pts, balance {new_pts}")
                    receipt_lines.append(f"Thanks {first_name}!")
                    receipt_lines.append(f"Points Balance: {new_pts}")
                    if earned > 0:
                        receipt_lines.append(f"Points Earned: +{earned}")
                    if pts_used > 0:
                        receipt_lines.append(f"Points Used: -{pts_used}")
            except Exception as e:
                self.log(f"Finalize error: {e}")
        else:
            receipt_lines.append("Thank you for shopping at Birdies!")

        rec_xml = "\n".join(f"      <ReceiptLine>{line[:40]}</ReceiptLine>" for line in receipt_lines)

        self.current_customer = None
        self.last_punch_cards = []
        self.last_punches_to_record = []

        return f"""
<FinalizeRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <ReceiptData>
{rec_xml}
    </ReceiptData>
  </CustomerMessageData>
</FinalizeRewardsResponse>""".strip()

    def build_cancel_response(self, root: ET.Element) -> str:
        pos_seq, loy_seq = self.get_req_ids(root)
        self.log("Transaction cancelled")
        self.current_customer = None
        self.last_punch_cards = []
        self.last_punches_to_record = []
        return f"""
<CancelTransactionResponse>
  {self.resp_header(pos_seq, loy_seq)}
</CancelTransactionResponse>""".strip()

    # =========================================================================
    # CLIENT HANDLER
    # =========================================================================
    
    def handle_client(self, conn: socket.socket, addr):
        self.log(f"POS connected: {addr[0]}")
        self.signals.status_changed.emit(f"Connected: {addr[0]}", "green")
        
        try:
            conn.settimeout(120)
            while self.running:
                hdr = self.recv_exact(conn, 28)
                if not hdr:
                    break
                    
                action, data_len, chk_data = self.parse_header(hdr)
                
                if action == self.ACTION_HEARTBEAT:
                    hb_resp = self.pack_header(b"", self.ACTION_HEARTBEAT)
                    conn.sendall(hb_resp)
                    continue
                    
                xml_bytes = self.recv_exact(conn, data_len)
                if not xml_bytes:
                    break
                    
                root, raw = self.parse_xml(xml_bytes)
                tag = root.tag
                
                if "GetLoyaltyOnlineStatus" in tag:
                    resp = self.build_online_status_response(root)
                elif "GetRewards" in tag:
                    resp = self.build_get_rewards_response(root)
                elif "FinalizeRewards" in tag:
                    resp = self.build_finalize_response(root)
                elif "CancelTransaction" in tag:
                    resp = self.build_cancel_response(root)
                else:
                    pos_seq, loy_seq = self.get_req_ids(root)
                    resp = f"<UnknownResponse>{self.resp_header(pos_seq, loy_seq)}</UnknownResponse>"
                
                self.send_xml(conn, resp)
                
        except Exception as e:
            self.log(f"Connection error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
            self.signals.status_changed.emit("Online - Waiting for POS", "green")

# =============================================================================
# SETUP WIZARD
# =============================================================================

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Birdies Passport Punch - Setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(500, 400)
        
        self.addPage(self.create_welcome_page())
        self.addPage(self.create_network_page())
        self.addPage(self.create_store_page())
        self.addPage(self.create_finish_page())
    
    def create_welcome_page(self):
        page = QWizardPage()
        page.setTitle("Welcome")
        page.setSubTitle("Setup the Birdies Passport Punch Card Edge Agent")
        
        layout = QVBoxLayout()
        
        info = QLabel(
            "This wizard will configure the edge agent for your Gilbarco Passport POS.\n\n"
            "Features:\n"
            "  - Punch Card Rewards (Buy 10, Get 1 Free)\n"
            "  - Points Redemption (100 pts = $1.00)\n\n"
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
            "\nThe Host IP should be this computer's IP on the Passport network.\n"
            "Port 9000 is the standard loyalty port for Passport MWS."
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
            "\nThis is your Birdies/PDI store number.\n"
            "POS ID is automatically set to 24379 for all stores."
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
            "  - Listen for POS connections\n"
            "  - Send heartbeats to the backend\n"
            "  - Process punch card rewards\n"
            "  - Log all raw interactions to a text file"
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
            "pos_id": "24379",
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
        
        self.setWindowTitle("Birdies Passport Punch Agent")
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
        title = QLabel("Birdies Passport Punch Agent")
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
        info_layout.addRow("POS ID:", QLabel("24379"))
        info_layout.addRow("Mode:", QLabel("Punch Cards + Points (No Promos)"))
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
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "B")
        painter.end()
        
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Birdies Passport Punch Agent")
        
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
            "Birdies Passport Punch",
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
