#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - Windows GUI Application (FULL VERSION)
====================================================================
Complete edge agent with GUI wrapper including:
  - Multi-Pack Promotions (e.g., "2 for $5")
  - Amount-Off Promotions (e.g., "$1.80 off when you buy 2")
  - Points Redemption (100 pts = $1.00)
  - Punch Card System (buy 10, get 1 free)
  - OPTION A Logic (promo and punch are mutually exclusive per line item)

Build EXE on Windows with:
  pip install pyside6 requests pyinstaller
  pyinstaller --onefile --windowed --name "Birdies Edge Agent" --collect-all PySide6 passport_edge_gui.py

Version: 1.3
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
# CONFIG FILE
# =============================================================================

def get_config_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), "birdies_edge_config.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "birdies_edge_config.json")

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
# EDGE AGENT SIGNALS
# =============================================================================

class EdgeAgentSignals(QObject):
    log_message = Signal(str)
    status_changed = Signal(str, str)
    heartbeat_sent = Signal(str)

# =============================================================================
# EDGE AGENT WORKER (FULL LOGIC FROM COMBINED FILE)
# =============================================================================

class EdgeAgentWorker(QThread):
    def __init__(self, config, signals):
        super().__init__()
        self.config = config
        self.signals = signals
        self.running = False
        self.server_socket = None
        
        # Session state
        self.current_customer = None
        self.last_promotions_applied = []
        self.last_punch_cards = []
        self.last_punches_to_record = []
        self.pos_lock = threading.Lock()
        
        # Protocol constants
        self.SIGNATURE = b"POSLOYALTY\x00\x00"
        self.ACTION_MESSAGE = 1
        self.ACTION_HEARTBEAT = 2
        
        # HTTP session
        self.SESSION = requests.Session()
        self.REQUEST_TIMEOUT = (3, 5)
        
        # Config values
        self.HOST = config.get("host_ip", "")
        self.PORT = int(config.get("port", 9000))
        self.PDI_STORE_NUMBER = config.get("store_number", "")
        self.POS_ID = config.get("pos_id", "") or self.PDI_STORE_NUMBER
        self.POS_TYPE = "Passport"
        self.BACKEND_URL = "https://salmanloyalty.replit.app"
        
        # Passport settings
        self.VENDOR_NAME = "DemoLoyalty"
        self.VENDOR_VER = "1.0"
        self.IFACE_VER = "1.0"
        
        # Reward IDs
        self.POINTS_REWARD_ID = "DEMO-1OFF"
        self.PUNCH_REWARD_ID = "PUNCH-FREE"
        self.PROMO_REWARD_PREFIX = "PROMO"
        
        # Receipt labels
        self.RECEIPT_SHORT = "$1OFF"
        self.RECEIPT_LONG = "Loyalty $ Off"
        
        # Points config
        self.POINTS_PER_DOLLAR = 100

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
            self.log(f"Store: {self.PDI_STORE_NUMBER} | POS ID: {self.POS_ID}")
            self.log("OPTION A: Promo and punch are mutually exclusive per line item")
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

    # =========================================================================
    # PROTOCOL HELPERS
    # =========================================================================
    
    def crc32(self, b):
        return binascii.crc32(b) & 0xFFFFFFFF

    def pack_header(self, xml_bytes, action=1):
        data_len = len(xml_bytes)
        chk_data = self.crc32(xml_bytes)
        head_wo_hdr_crc = self.SIGNATURE + struct.pack("<III", action, data_len, chk_data)
        chk_hdr = self.crc32(head_wo_hdr_crc)
        return head_wo_hdr_crc + struct.pack("<I", chk_hdr)

    def send_xml(self, conn, xml_str):
        xml_bytes = xml_str.encode("utf-8")
        hdr = self.pack_header(xml_bytes)
        conn.sendall(hdr + xml_bytes)
        self.log("Sent response to POS")

    def recv_exact(self, conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return b""
            buf += chunk
        return buf

    def parse_header(self, hdr):
        if len(hdr) != 28:
            raise ValueError("short header")
        if hdr[:12] != self.SIGNATURE:
            raise ValueError("bad signature")
        action, data_len, chk_data, chk_hdr = struct.unpack("<IIII", hdr[12:28])
        if self.crc32(hdr[:24]) != chk_hdr:
            raise ValueError("header CRC mismatch")
        return action, data_len, chk_data

    def get_req_ids(self, root):
        pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
        loy_seq = root.findtext(".//LoyaltySequenceID")
        if not loy_seq or not loy_seq.strip():
            loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
        return pos_seq, loy_seq

    def resp_header(self, pos_seq, loy_seq):
        return (
            f"<ResponseHeader>"
            f"<POSLoyaltyInterfaceVersion>{self.IFACE_VER}</POSLoyaltyInterfaceVersion>"
            f"<VendorName>{self.VENDOR_NAME}</VendorName>"
            f"<VendorModelVersion>{self.VENDOR_VER}</VendorModelVersion>"
            f"<POSSequenceID>{pos_seq}</POSSequenceID>"
            f"<LoyaltySequenceID>{loy_seq}</LoyaltySequenceID>"
            f"</ResponseHeader>"
        )

    def clear_session_state(self):
        self.current_customer = None
        self.last_promotions_applied = []
        self.last_punch_cards = []
        self.last_punches_to_record = []

    def receipt_short(self, s):
        return (s or "").strip()[:8]

    def receipt_long(self, s):
        return (s or "").strip()[:24]

    def receipt_line(self, s):
        clean = "".join(ch for ch in (s or "") if ch.isprintable())
        return clean[:40]

    # =========================================================================
    # BACKEND COMMUNICATION
    # =========================================================================
    
    def send_heartbeat(self, pos_ip):
        try:
            payload = {
                "pdiStoreNumber": self.PDI_STORE_NUMBER,
                "posId": self.POS_ID,
                "posType": self.POS_TYPE,
                "posIpAddress": pos_ip,
                "edgeIpAddress": self.HOST,
                "edgeVersion": "birdies-gui-1.3",
            }
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/heartbeat",
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                self.signals.heartbeat_sent.emit(ts)
                self.log("Heartbeat sent - POS connectivity confirmed")
            else:
                self.log(f"Heartbeat failed: {r.status_code}")
        except Exception as e:
            self.log(f"Heartbeat error: {e}")

    # =========================================================================
    # TRANSACTION PARSING
    # =========================================================================
    
    def extract_line_items(self, root):
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
            upc = upc_raw.strip()
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

            try:
                if atxt and atxt.strip():
                    amount = float(atxt)
                else:
                    amount = float(actual_price_txt or 0) * qty
            except Exception:
                amount = 0.0

            try:
                unit_price = float(unit_price_txt or 0)
            except Exception:
                unit_price = 0.0

            try:
                actual_price = float(actual_price_txt or 0)
            except Exception:
                actual_price = 0.0

            try:
                regular_price = float(regular_price_txt or 0)
            except Exception:
                regular_price = 0.0

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
            })
        return items

    def detect_loyalty_tender(self, root, reward_id):
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

    def get_current_unit_price(self, item):
        for key in ("unit_price", "actual_price", "regular_price"):
            val = item.get(key, 0.0)
            if val and val > 0:
                return float(val)
        return 0.0

    # =========================================================================
    # PROMOTION EVALUATION
    # =========================================================================
    
    def evaluate_promotions(self, items):
        if not items:
            return []

        self.log(f"Evaluating promotions for {len(items)} item(s)...")

        try:
            upc_groups = {}
            for item in items:
                upc = item["upc"]
                if upc not in upc_groups:
                    upc_groups[upc] = {"upc": upc, "quantity": 0, "price": item["price"]}
                upc_groups[upc]["quantity"] += item["quantity"]

            api_items = list(upc_groups.values())
            payload = {"pdiStoreNumber": self.PDI_STORE_NUMBER, "items": api_items}

            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/evaluate-promotions",
                json=payload,
                timeout=self.REQUEST_TIMEOUT,
            )

            if r.status_code == 200:
                result = r.json()
                promotions = result.get("promotions", [])
                if promotions:
                    self.log(f"Found {len(promotions)} active promotion(s)")
                    for promo in promotions:
                        self.log(f"  - {promo.get('description', 'Promo')}: ${promo.get('discount', 0)}")
                else:
                    self.log("No matching promotions found")
                return promotions
            else:
                self.log(f"Evaluate promotions failed: {r.status_code}")
                return []
        except Exception as e:
            self.log(f"Evaluate promotions error: {e}")
            return []

    def build_promotion_rewards_xml(self, items, promotions):
        if not promotions:
            return [], [], set()

        upc_to_lines = {}
        for item in items:
            upc = item["upc"]
            if upc not in upc_to_lines:
                upc_to_lines[upc] = []
            upc_to_lines[upc].append(item)

        upc_promo_groups = {}
        for promo in promotions:
            upc = promo.get("upc", "")
            promo_id = promo.get("promotionId", "")
            if not upc:
                continue

            promo_qty = int(promo.get("quantity", 2))
            bundle_count = int(promo.get("bundleCount", 0))
            promo_price = float(promo.get("promoPrice", 0))

            if bundle_count <= 0:
                continue

            total_promo_units = bundle_count * promo_qty
            per_unit_new_price = promo_price / total_promo_units if total_promo_units > 0 else 0

            group_key = (upc, promo_id)
            if group_key not in upc_promo_groups:
                upc_promo_groups[group_key] = {
                    "promo": promo,
                    "per_unit_price": per_unit_new_price,
                    "total_bundle_count": bundle_count
                }
            else:
                upc_promo_groups[group_key]["total_bundle_count"] += bundle_count

        upc_to_best_promo = {}
        for (upc, promo_id), group_data in upc_promo_groups.items():
            per_unit_price = group_data["per_unit_price"]
            if upc not in upc_to_best_promo or per_unit_price < upc_to_best_promo[upc]["per_unit_price"]:
                upc_to_best_promo[upc] = group_data

        add_rewards = []
        applied_promotions = []
        promo_line_numbers = set()
        promo_counter = 1

        for upc, best_data in upc_to_best_promo.items():
            promo = best_data["promo"]
            per_unit_new_price = best_data["per_unit_price"]
            total_bundle_count = best_data["total_bundle_count"]

            promo_qty = int(promo.get("quantity", 2))
            promo_name = promo.get("name") or promo.get("itemGroupName") or "Promo"
            display_name = promo_name[:24]

            matching_lines = upc_to_lines.get(upc, [])
            if not matching_lines:
                continue

            total_promo_units = total_bundle_count * promo_qty
            remaining_units = total_promo_units
            total_discount_for_promo = 0.0

            for item in matching_lines:
                if remaining_units <= 0:
                    break

                current_price = self.get_current_unit_price(item)
                if current_price <= per_unit_new_price:
                    continue

                take_qty = min(int(item["quantity"]), remaining_units)
                if take_qty <= 0:
                    continue

                reward_id = f"{self.PROMO_REWARD_PREFIX}-{promo.get('promotionId', promo_counter)}-L{item['line_no']}"
                discount_per_unit = current_price - per_unit_new_price
                line_discount = discount_per_unit * take_qty
                total_discount_for_promo += line_discount

                self.log(f"  Promo on line {item['line_no']}: {take_qty} units @ ${per_unit_new_price:.4f}")

                add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="no"/>
      <RewardTargetLineNumber>{item["line_no"]}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>{per_unit_new_price:.4f}</RewardValue>
      <RewardLimit type="quantity">{take_qty}</RewardLimit>
      <RewardReceiptDescShort>{self.receipt_short("PROMO")}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{self.receipt_long(display_name)}</RewardReceiptDescLong>
    </AddReward>""".rstrip())

                promo_line_numbers.add(item["line_no"])
                remaining_units -= take_qty

            if total_discount_for_promo > 0:
                applied_promo = promo.copy()
                applied_promo["discount"] = total_discount_for_promo
                applied_promo["name"] = display_name
                applied_promotions.append(applied_promo)

            promo_counter += 1

        return add_rewards, applied_promotions, promo_line_numbers

    # =========================================================================
    # PUNCH CARD EVALUATION
    # =========================================================================
    
    def evaluate_punch_cards(self, customer_id, line_items):
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/punch-cards/evaluate",
                json={"customerId": customer_id, "lineItems": line_items},
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                return r.json()
            else:
                self.log(f"Punch evaluate failed: {r.status_code}")
                return {"punchCards": []}
        except Exception as e:
            self.log(f"Punch evaluate error: {e}")
            return {"punchCards": []}

    def record_punches(self, customer_id, line_items, transaction_id):
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
            else:
                self.log(f"Record punches failed: {r.status_code}")
                return {}
        except Exception as e:
            self.log(f"Record punches error: {e}")
            return {}

    def redeem_punch_reward(self, customer_id, punch_card_id, transaction_id):
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
            else:
                self.log(f"Punch redeem failed: {r.status_code}")
                return {}
        except Exception as e:
            self.log(f"Punch redeem error: {e}")
            return {}

    def build_punch_rewards_xml(self, punch_cards, eligible_items):
        punch_rewards_xml = []

        if not punch_cards or not eligible_items:
            return punch_rewards_xml

        available_items = list(eligible_items)

        for pc in punch_cards:
            if not available_items:
                self.log("  No eligible items for punch reward")
                continue

            cheapest = min(available_items, key=lambda it: it["price"])
            line_no = cheapest["line_no"]
            punch_card_name = pc.get("punchCardName", "Punch Reward")

            self.log(f"  FREE ITEM punch reward on line {line_no} (${cheapest.get('price'):.2f})")

            punch_rewards_xml.append(f"""
    <AddReward>
      <LoyaltyRewardID>{self.PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>percentOff</RewardDiscountMethod>
      <RewardValue>1.0000</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>{self.receipt_short("FREE")}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{self.receipt_long(punch_card_name + " FREE")}</RewardReceiptDescLong>
    </AddReward>""".rstrip())

            pc["rewardApplied"] = True
            available_items = [it for it in available_items if it["line_no"] != line_no]

        return punch_rewards_xml

    # =========================================================================
    # RESPONSE BUILDERS
    # =========================================================================
    
    def build_online_status_response(self, root):
        pos_seq, loy_seq = self.get_req_ids(root)
        return (
            "<GetLoyaltyOnlineStatusResponse>"
            f"{self.resp_header(pos_seq, loy_seq)}"
            '<PromptForLoyaltyFlag value="yes"/>'
            "</GetLoyaltyOnlineStatusResponse>"
        )

    def build_get_rewards_response(self, root):
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
            for idx, it in enumerate(items, 1):
                self.log(f"  {idx}. Line {it['line_no']}: {it['upc']} - ${it['amount']:.2f}")

        self.last_punch_cards = []
        self.last_punches_to_record = []

        # Guest mode
        if not loyalty_id and not phone:
            promotions = self.evaluate_promotions(items)
            promo_rewards, applied_promos, _ = self.build_promotion_rewards_xml(items, promotions)
            self.last_promotions_applied = applied_promos

            if promo_rewards:
                rewards_block = "<RewardActions>\n" + "".join(promo_rewards) + "\n  </RewardActions>"
                return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">Guest</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()
            else:
                return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

        # Customer lookup
        self.current_customer = None
        lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
        try:
            r = self.SESSION.post(
                f"{self.BACKEND_URL}/api/pos/customer-lookup",
                json=lookup_payload,
                timeout=self.REQUEST_TIMEOUT,
            )
            if r.status_code == 404:
                self.log("Customer not found")
                return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer not found</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()
            if r.status_code != 200:
                self.log(f"Customer lookup failed: {r.status_code}")
                return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

            self.current_customer = r.json()
        except Exception as e:
            self.log(f"Customer lookup error: {e}")
            return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

        customer_id = self.current_customer.get("customerId")
        first_name = self.current_customer.get("firstName", "")
        last_name = self.current_customer.get("lastName", "")
        points = self.current_customer.get("pointsBalance", 0)
        self.log(f"Customer: {first_name} {last_name} ({points} pts)")

        display_id = loyalty_id or phone or ""
        masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

        # STEP 1: Evaluate promotions
        promotions = self.evaluate_promotions(items)
        promo_rewards, applied_promos, promo_line_numbers = self.build_promotion_rewards_xml(items, promotions)
        self.last_promotions_applied = applied_promos

        if promo_line_numbers:
            self.log(f"OPTION A: Lines with promo (excluded from punch): {promo_line_numbers}")

        # STEP 2: Filter items for punch cards (OPTION A)
        punch_eligible_items = [it for it in items if it.get("line_no") not in promo_line_numbers]

        if punch_eligible_items:
            self.log(f"Punch-eligible items: {len(punch_eligible_items)} of {len(items)}")
        else:
            self.log("No punch-eligible items (all got promo)")

        self.last_punches_to_record = punch_eligible_items
        punch_rewards_xml = []

        # STEP 3: Evaluate punch cards
        if customer_id and punch_eligible_items:
            punch_eval = self.evaluate_punch_cards(customer_id, punch_eligible_items)
            punch_cards_data = punch_eval.get("punchCards", [])

            if punch_cards_data:
                self.log("PUNCH CARD STATUS:")
                for pc in punch_cards_data:
                    current = int(pc.get("currentPunches", 0) or 0)
                    basket = int(pc.get("punchesFromBasket", 0) or 0)
                    required = int(pc.get("punchesRequired", 10) or 10)
                    punches_needed = max(0, required - current)

                    should_trigger = (current + basket) >= required and required > 0

                    status_line = f"  {pc.get('punchCardName', 'Punch Card')}: {current}/{required}"
                    if basket > 0:
                        status_line += f" (+{basket} from basket)"

                    if should_trigger:
                        status_line += " - REWARD TRIGGERED!"
                        pc["rewardTriggered"] = True
                        self.last_punch_cards.append(pc)
                    else:
                        status_line += f" (need {punches_needed} more)"

                    self.log(status_line)

                if self.last_punch_cards:
                    reward_eligible_items = [
                        it for it in punch_eligible_items
                        if it.get("upc") and it.get("price", 0) > 0
                    ]
                    punch_rewards_xml = self.build_punch_rewards_xml(self.last_punch_cards, reward_eligible_items)

        # STEP 4: Calculate points redemption
        subtotal = sum(it["amount"] for it in items)
        self.log(f"Subtotal: ${subtotal:.2f}")

        points_reward_xml = ""
        if subtotal > 0 and points >= self.POINTS_PER_DOLLAR:
            try:
                redemption_req = {
                    "customerId": customer_id,
                    "eligibleSubtotal": subtotal,
                    "lineItems": items,
                }
                rr = self.SESSION.post(
                    f"{self.BACKEND_URL}/api/pos/calculate-redemption",
                    json=redemption_req,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if rr.status_code == 200:
                    data = rr.json()
                    recommended = float(data.get("recommendedRedemption") or 0.0)
                    if recommended > 0:
                        pts_to_use = int(round(recommended * self.POINTS_PER_DOLLAR))
                        self.log(f"Points redemption: ${recommended:.2f} ({pts_to_use} pts)")
                        points_reward_xml = f"""
    <AddReward>
      <LoyaltyRewardID>{self.POINTS_REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{recommended:.2f}</RewardValue>
      <RewardReceiptDescShort>{self.receipt_short(self.RECEIPT_SHORT)}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{self.receipt_long(self.RECEIPT_LONG)}</RewardReceiptDescLong>
    </AddReward>""".rstrip()
            except Exception as e:
                self.log(f"calculate-redemption error: {e}")

        # STEP 5: Combine all rewards
        all_rewards = []
        if promo_rewards:
            all_rewards.extend(promo_rewards)
        if punch_rewards_xml:
            all_rewards.extend(punch_rewards_xml)
        if points_reward_xml:
            all_rewards.append(points_reward_xml)

        if all_rewards:
            self.log(f"Sending {len(all_rewards)} reward(s) to POS")
            rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
        else:
            self.log("No rewards to apply")
            rewards_block = "<RewardActions/>"

        return f"""
<GetRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()

    def build_finalize_response(self, root):
        pos_seq, loy_seq = self.get_req_ids(root)

        items = self.extract_line_items(root)
        eligible_subtotal = sum(it["amount"] for it in items)
        self.log(f"Finalize: subtotal ${eligible_subtotal:.2f}")

        applied_dollars = self.detect_loyalty_tender(root, self.POINTS_REWARD_ID)
        if applied_dollars > 0:
            self.log(f"Loyalty tender: ${applied_dollars:.2f}")
            points_redeemed = int(round(applied_dollars * self.POINTS_PER_DOLLAR))
        else:
            points_redeemed = 0

        receipt_lines = []

        promo_discount = sum(float(p.get("discount", 0) or 0) for p in self.last_promotions_applied)

        raw_txn_id = root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or ""
        safe_txn_id = raw_txn_id if raw_txn_id.strip() else f"TXN-{uuid.uuid4().hex[:8].upper()}"

        if self.current_customer:
            try:
                payload = {
                    "customerId": self.current_customer.get("customerId"),
                    "eligibleSubtotal": eligible_subtotal,
                    "pointsRedeemed": points_redeemed,
                    "transactionId": safe_txn_id,
                    "pdiStoreNumber": self.PDI_STORE_NUMBER,
                    "lineItems": items,
                    "promotions": self.last_promotions_applied or [],
                    "promotionDiscount": promo_discount,
                }

                r = self.SESSION.post(
                    f"{self.BACKEND_URL}/api/pos/finalize-transaction",
                    json=payload,
                    timeout=self.REQUEST_TIMEOUT,
                )
                if r.status_code == 200:
                    data = r.json()
                    pts_earned = data.get("pointsEarned", 0)
                    new_bal = data.get("newBalance", 0)

                    self.log(f"Finalized: Redeemed {points_redeemed} pts, Earned {pts_earned} pts, Balance {new_bal}")

                    if applied_dollars > 0:
                        receipt_lines.append(f"Points Redeemed: {points_redeemed} pts (${applied_dollars:.2f})")

                    receipt_lines.append(f"Points Earned: {pts_earned} pts")
                    receipt_lines.append(f"New Balance: {new_bal} pts")
                else:
                    self.log(f"finalize-transaction failed: {r.status_code}")
            except Exception as e:
                self.log(f"Finalize error: {e}")

            # Record punches (OPTION A enforced)
            if self.last_punches_to_record:
                try:
                    punch_result = self.record_punches(
                        self.current_customer.get("customerId"),
                        self.last_punches_to_record,
                        safe_txn_id,
                    )
                    punches_recorded = punch_result.get("punchesRecorded", [])
                    if punches_recorded:
                        receipt_lines.append("Punches Recorded:")
                        for p in punches_recorded:
                            receipt_lines.append(
                                f"  {p.get('punchCardName')}: +{p.get('punchesAdded')} "
                                f"({p.get('currentPunches')}/{p.get('punchesRequired')})"
                            )
                except Exception as e:
                    self.log(f"Record punches error: {e}")

            # Redeem punch rewards
            for pc in self.last_punch_cards or []:
                if pc.get("rewardApplied"):
                    try:
                        redeem_result = self.redeem_punch_reward(
                            self.current_customer.get("customerId"),
                            pc.get("punchCardId"),
                            safe_txn_id,
                        )
                        if redeem_result.get("redeemed"):
                            receipt_lines.append(f"Punch Reward Redeemed: {pc.get('punchCardName', 'Punch')}")
                    except Exception as e:
                        self.log(f"Punch redeem error: {e}")

        if not receipt_lines:
            receipt_lines.append("Thank you for shopping at Birdies!")

        self.clear_session_state()

        receipt_xml = "\n".join(f"      <ReceiptLine>{self.receipt_line(line)}</ReceiptLine>" for line in receipt_lines)
        return f"""
<FinalizeRewardsResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <ReceiptData>
{receipt_xml}
    </ReceiptData>
  </CustomerMessageData>
</FinalizeRewardsResponse>""".strip()

    def build_cancel_response(self, root):
        pos_seq, loy_seq = self.get_req_ids(root)
        self.clear_session_state()
        self.log("Transaction cancelled")
        return f"<CancelTransactionResponse>{self.resp_header(pos_seq, loy_seq)}</CancelTransactionResponse>"

    def build_customer_msg_response(self, root):
        pos_seq, loy_seq = self.get_req_ids(root)
        return f"""
<GetCustomerMessagingResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <DisplayData>
      <DisplayCommand device="POS-Cashier" sequence="WhenReceived">
        <DisplayLine>Welcome to Birdies Loyalty!</DisplayLine>
      </DisplayCommand>
    </DisplayData>
  </CustomerMessageData>
</GetCustomerMessagingResponse>""".strip()

    def build_end_period_response(self, root):
        pos_seq, loy_seq = self.get_req_ids(root)
        return f"""
<EndPeriodResponse>
  {self.resp_header(pos_seq, loy_seq)}
  <Result value="success"/>
</EndPeriodResponse>""".strip()

    # =========================================================================
    # CLIENT HANDLER
    # =========================================================================
    
    def handle_client(self, conn, addr):
        peer = f"{addr[0]}:{addr[1]}"
        
        with self.pos_lock:
            self.log(f"POS connected: {peer}")
            self.signals.status_changed.emit("Online - POS Connected", "green")
            
            try:
                conn.settimeout(180)
                while self.running:
                    hdr = self.recv_exact(conn, 28)
                    if not hdr:
                        break
                    
                    try:
                        action, data_len, chk_data = self.parse_header(hdr)
                    except Exception as e:
                        self.log(f"Bad header: {e}")
                        break
                    
                    if action == self.ACTION_HEARTBEAT:
                        if data_len:
                            self.recv_exact(conn, data_len)
                        continue
                    
                    data = self.recv_exact(conn, data_len)
                    if len(data) != data_len or self.crc32(data) != chk_data:
                        self.log("CRC mismatch")
                        break
                    
                    try:
                        root = ET.fromstring(data.decode("utf-8", errors="replace"))
                    except Exception as e:
                        self.log(f"XML error: {e}")
                        break
                    
                    tag = root.tag.strip()
                    self.log(f"Request: {tag}")
                    
                    if tag == "GetLoyaltyOnlineStatusRequest":
                        self.send_xml(conn, self.build_online_status_response(root))
                        self.send_heartbeat(addr[0])
                    elif tag == "GetRewardsRequest":
                        self.send_xml(conn, self.build_get_rewards_response(root))
                    elif tag == "FinalizeRewardsRequest":
                        self.send_xml(conn, self.build_finalize_response(root))
                    elif tag == "CancelTransactionRequest":
                        self.send_xml(conn, self.build_cancel_response(root))
                    elif tag == "GetCustomerMessagingRequest":
                        self.send_xml(conn, self.build_customer_msg_response(root))
                    elif tag == "EndPeriodRequest":
                        self.send_xml(conn, self.build_end_period_response(root))
                    else:
                        self.log(f"Unhandled: {tag}")
                        
            except socket.timeout:
                self.log(f"POS timeout: {peer}")
            except Exception as e:
                self.log(f"POS error: {e}")
            finally:
                self.clear_session_state()
                try:
                    conn.close()
                except Exception:
                    pass
                self.log(f"POS disconnected: {peer}")
                self.signals.status_changed.emit("Online - Waiting for POS", "green")


# =============================================================================
# SETUP WIZARD
# =============================================================================

class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Welcome to Birdies Loyalty Edge Agent")
        
        layout = QVBoxLayout()
        
        welcome_text = QLabel(
            "This wizard will help you configure the Edge Agent to connect "
            "your Passport POS to the Birdies Loyalty system.\n\n"
            "You will need:\n"
            "  - This computer's IP address on the store network\n"
            "  - Your PDI Store Number\n"
            "  - The port number configured in Passport MWS (default: 9000)\n\n"
            "Click Next to continue."
        )
        welcome_text.setWordWrap(True)
        layout.addWidget(welcome_text)
        
        self.setLayout(layout)

class ConfigPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Configuration")
        self.setSubTitle("Enter your store connection settings")
        
        layout = QFormLayout()
        
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g., 10.96.10.175")
        layout.addRow("This Computer's IP:", self.host_input)
        
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(9000)
        layout.addRow("Port Number:", self.port_input)
        
        self.store_input = QLineEdit()
        self.store_input.setPlaceholderText("e.g., 1340")
        layout.addRow("PDI Store Number:", self.store_input)
        
        self.pos_id_input = QLineEdit()
        self.pos_id_input.setPlaceholderText("(optional, defaults to store number)")
        layout.addRow("POS ID:", self.pos_id_input)
        
        self.registerField("host_ip*", self.host_input)
        self.registerField("port", self.port_input)
        self.registerField("store_number*", self.store_input)
        self.registerField("pos_id", self.pos_id_input)
        
        self.setLayout(layout)

class ConfirmPage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("Confirm Settings")
        self.setSubTitle("Review your configuration before starting")
        
        layout = QVBoxLayout()
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.setLayout(layout)
    
    def initializePage(self):
        host = self.field("host_ip")
        port = self.field("port")
        store = self.field("store_number")
        pos_id = self.field("pos_id") or store
        
        self.summary_label.setText(
            f"<b>Configuration Summary:</b><br><br>"
            f"<b>Host IP:</b> {host}<br>"
            f"<b>Port:</b> {port}<br>"
            f"<b>Store Number:</b> {store}<br>"
            f"<b>POS ID:</b> {pos_id}<br><br>"
            f"Click Finish to start the Edge Agent."
        )

class SetupWizard(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Birdies Edge Agent Setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(500, 400)
        
        self.addPage(WelcomePage())
        self.addPage(ConfigPage())
        self.addPage(ConfirmPage())
    
    def get_config(self):
        return {
            "host_ip": self.field("host_ip"),
            "port": self.field("port"),
            "store_number": self.field("store_number"),
            "pos_id": self.field("pos_id") or self.field("store_number"),
        }


# =============================================================================
# MAIN DASHBOARD WINDOW
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.worker = None
        self.signals = EdgeAgentSignals()
        
        self.setWindowTitle("Birdies Loyalty Edge Agent")
        self.setMinimumSize(700, 500)
        
        self.setup_tray()
        self.setup_ui()
        self.connect_signals()
        
        QTimer.singleShot(500, self.start_agent)
    
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Status section
        status_group = QGroupBox("Status")
        status_layout = QHBoxLayout(status_group)
        
        self.status_indicator = QLabel()
        self.status_indicator.setFixedSize(20, 20)
        self.update_status_indicator("gray")
        status_layout.addWidget(self.status_indicator)
        
        self.status_label = QLabel("Stopped")
        self.status_label.setFont(QFont("Arial", 12, QFont.Bold))
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        self.heartbeat_label = QLabel("Last Heartbeat: --")
        status_layout.addWidget(self.heartbeat_label)
        
        layout.addWidget(status_group)
        
        # Store info section
        info_group = QGroupBox("Configuration")
        info_layout = QFormLayout(info_group)
        info_layout.addRow("Host IP:", QLabel(self.config.get("host_ip", "")))
        info_layout.addRow("Port:", QLabel(str(self.config.get("port", 9000))))
        info_layout.addRow("Store Number:", QLabel(self.config.get("store_number", "")))
        info_layout.addRow("POS ID:", QLabel(self.config.get("pos_id", "")))
        layout.addWidget(info_group)
        
        # Log viewer
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_group)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_agent)
        button_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_agent)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)
        
        button_layout.addStretch()
        
        reconfigure_btn = QPushButton("Reconfigure")
        reconfigure_btn.clicked.connect(self.reconfigure)
        button_layout.addWidget(reconfigure_btn)
        
        layout.addLayout(button_layout)
    
    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.create_icon("gray"))
        
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
    
    def create_icon(self, color):
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = {
            "green": QColor(0, 200, 0),
            "red": QColor(200, 0, 0),
            "yellow": QColor(200, 200, 0),
            "gray": QColor(128, 128, 128),
        }
        painter.setBrush(colors.get(color, colors["gray"]))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()
        return QIcon(pixmap)
    
    def update_status_indicator(self, color):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = {
            "green": QColor(0, 200, 0),
            "red": QColor(200, 0, 0),
            "yellow": QColor(200, 200, 0),
            "gray": QColor(128, 128, 128),
        }
        painter.setBrush(colors.get(color, colors["gray"]))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 16, 16)
        painter.end()
        self.status_indicator.setPixmap(pixmap)
        self.tray_icon.setIcon(self.create_icon(color))
    
    def connect_signals(self):
        self.signals.log_message.connect(self.append_log)
        self.signals.status_changed.connect(self.update_status)
        self.signals.heartbeat_sent.connect(self.update_heartbeat)
    
    def append_log(self, msg):
        self.log_view.append(msg)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )
    
    def update_status(self, status, color):
        self.status_label.setText(status)
        self.update_status_indicator(color)
    
    def update_heartbeat(self, time_str):
        self.heartbeat_label.setText(f"Last Heartbeat: {time_str}")
    
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
        self.update_status("Stopped", "gray")
    
    def reconfigure(self):
        self.stop_agent()
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        QMessageBox.information(
            self, 
            "Reconfigure", 
            "Please restart the application to run the setup wizard again."
        )
        self.close()
    
    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()
    
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Birdies Edge Agent",
            "Running in background. Double-click tray icon to open.",
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
    app.setApplicationName("Birdies Edge Agent")
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
