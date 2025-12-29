#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - INSTALLER VERSION
===============================================
This version prompts for configuration at startup.
Build as EXE with: pyinstaller --onefile --console passport_edge_installer.py

Version: 1.3
"""

import socket
import threading
import datetime
import binascii
import struct
import uuid
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom
import os
import sys

# =============================================================================
# CONFIGURATION (set at runtime)
# =============================================================================

HOST = ""
PORT = 9000
PDI_STORE_NUMBER = ""
POS_ID = ""
POS_TYPE = "Passport"
EXPECTED_POS_IP = None  # None = accept any POS IP

BACKEND_URL = "https://salmanloyalty.replit.app"

VENDOR_NAME = "DemoLoyalty"
VENDOR_VER = "1.0"
IFACE_VER = "1.0"

POINTS_REWARD_ID = "DEMO-1OFF"
PUNCH_REWARD_ID = "PUNCH-FREE"
PROMO_REWARD_PREFIX = "PROMO"

RECEIPT_SHORT = "$1OFF"
RECEIPT_LONG = "Loyalty $ Off"

POINTS_PER_DOLLAR = 100

SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)

POS_SINGLETON_LOCK = threading.Lock()

current_customer = None
last_promotions_applied = []
last_punch_cards = []
last_punches_to_record = []

SIGNATURE = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE = 1
ACTION_HEARTBEAT = 2

# =============================================================================
# STARTUP CONFIGURATION
# =============================================================================

def get_config_from_user():
    """Prompt user for configuration at startup."""
    global HOST, PORT, PDI_STORE_NUMBER, POS_ID
    
    print("=" * 60)
    print("  Birdies Loyalty Edge Agent - Configuration")
    print("=" * 60)
    print()
    
    # Host IP
    while True:
        host_input = input("Enter this computer's IP address (e.g., 10.96.10.175): ").strip()
        if host_input:
            HOST = host_input
            break
        print("  Error: IP address is required.")
    
    # Port
    while True:
        port_input = input("Enter port number [default: 9000]: ").strip()
        if not port_input:
            PORT = 9000
            break
        try:
            PORT = int(port_input)
            if 1 <= PORT <= 65535:
                break
            print("  Error: Port must be between 1 and 65535.")
        except ValueError:
            print("  Error: Please enter a valid number.")
    
    # PDI Store Number
    while True:
        store_input = input("Enter PDI Store Number (e.g., 1340): ").strip()
        if store_input:
            PDI_STORE_NUMBER = store_input
            break
        print("  Error: Store number is required.")
    
    # POS ID (optional, defaults to store number)
    pos_input = input(f"Enter POS ID [default: {PDI_STORE_NUMBER}]: ").strip()
    POS_ID = pos_input if pos_input else PDI_STORE_NUMBER
    
    print()
    print("-" * 60)
    print(f"  Host IP:      {HOST}")
    print(f"  Port:         {PORT}")
    print(f"  Store Number: {PDI_STORE_NUMBER}")
    print(f"  POS ID:       {POS_ID}")
    print(f"  POS Filter:   Any (accepting all POS connections)")
    print("-" * 60)
    print()
    
    confirm = input("Start the edge agent with these settings? (Y/n): ").strip().lower()
    if confirm == 'n':
        print("Exiting...")
        sys.exit(0)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def crc32(b: bytes) -> int:
    return binascii.crc32(b) & 0xFFFFFFFF


def pack_header(xml_bytes: bytes, action: int = ACTION_MESSAGE) -> bytes:
    data_len = len(xml_bytes)
    chk_data = crc32(xml_bytes)
    head_wo_hdr_crc = SIGNATURE + struct.pack("<III", action, data_len, chk_data)
    chk_hdr = crc32(head_wo_hdr_crc)
    return head_wo_hdr_crc + struct.pack("<I", chk_hdr)


def send_xml(conn: socket.socket, xml_str: str, action: int = ACTION_MESSAGE) -> None:
    xml_bytes = xml_str.encode("utf-8")
    hdr = pack_header(xml_bytes, action)
    conn.sendall(hdr + xml_bytes)
    try:
        pretty = minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        pretty = xml_str
    log("→ Sent to POS:\n" + pretty)


def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


def parse_header(hdr: bytes):
    if len(hdr) != 28:
        raise ValueError("short header")
    if hdr[:12] != SIGNATURE:
        raise ValueError("bad signature")
    action, data_len, chk_data, chk_hdr = struct.unpack("<IIII", hdr[12:28])
    if crc32(hdr[:24]) != chk_hdr:
        raise ValueError("header CRC mismatch")
    return action, data_len, chk_data


def parse_xml(xml_bytes: bytes):
    raw = xml_bytes.decode("utf-8", errors="replace")
    try:
        pretty = minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        pretty = raw
    log("← Received from POS:\n" + pretty)
    root = ET.fromstring(raw)
    return root, raw


def get_req_ids(root: ET.Element):
    pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
    loy_seq = root.findtext(".//LoyaltySequenceID")
    if not loy_seq or not loy_seq.strip():
        loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
    return pos_seq, loy_seq


def resp_header(pos_seq: str, loy_seq: str) -> str:
    return (
        f"<ResponseHeader>"
        f"<POSLoyaltyInterfaceVersion>{IFACE_VER}</POSLoyaltyInterfaceVersion>"
        f"<VendorName>{VENDOR_NAME}</VendorName>"
        f"<VendorModelVersion>{VENDOR_VER}</VendorModelVersion>"
        f"<POSSequenceID>{pos_seq}</POSSequenceID>"
        f"<LoyaltySequenceID>{loy_seq}</LoyaltySequenceID>"
        f"</ResponseHeader>"
    )


def normalize_upc(upc: str) -> str:
    if not upc:
        return ""
    return upc.strip()


def clear_session_state() -> None:
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record
    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []


def receipt_short(s: str) -> str:
    return (s or "").strip()[:8]


def receipt_long(s: str) -> str:
    return (s or "").strip()[:24]


def receipt_line(s: str) -> str:
    clean = "".join(ch for ch in (s or "") if ch.isprintable())
    return clean[:40]


# =============================================================================
# BACKEND COMMUNICATION
# =============================================================================

def send_heartbeat(pos_ip: str) -> None:
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "posId": POS_ID,
            "posType": POS_TYPE,
            "posIpAddress": pos_ip,
            "edgeIpAddress": HOST,
            "edgeVersion": "birdies-combined-rewards-punch-1.3",
        }
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/heartbeat",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            log(f"✓ Heartbeat sent - POS connectivity confirmed (Store {PDI_STORE_NUMBER})")
        else:
            log(f"⚠ Heartbeat failed: {r.status_code}")
    except Exception as e:
        log(f"⚠ Heartbeat error: {e}")


# =============================================================================
# TRANSACTION PARSING
# =============================================================================

def extract_line_items(root: ET.Element) -> list:
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
        upc = normalize_upc(upc_raw)
        desc = (il.findtext("Description") or "").strip()

        qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
        try:
            qty = float(qtxt or "1")
        except Exception:
            qty = 1.0
        qty = max(1.0, qty)

        unit_txt = il.findtext("RegularUnitPrice", "0")
        try:
            unit_price = float(unit_txt)
        except Exception:
            unit_price = 0.0

        amt_txt = il.findtext("ExtendedAmount", il.findtext("Amount", "0"))
        try:
            amount = float(amt_txt)
        except Exception:
            amount = 0.0

        items.append({
            "line_no": line_no,
            "upc": upc,
            "description": desc,
            "quantity": int(qty) if qty == int(qty) else qty,
            "price": unit_price,
            "amount": amount,
        })
    return items


def get_current_unit_price(item: dict) -> float:
    if item["quantity"] > 0:
        return item["amount"] / item["quantity"]
    return item["price"]


def detect_loyalty_tender(root: ET.Element, reward_id: str) -> float:
    for tender in root.findall(".//TenderGroup/LoyaltyRewardTender"):
        tid = (tender.findtext("LoyaltyRewardID") or "").strip()
        if tid == reward_id:
            try:
                return abs(float(tender.findtext("Amount") or 0))
            except Exception:
                pass
    return 0.0


# =============================================================================
# PROMOTION EVALUATION
# =============================================================================

def evaluate_promotions(items: list) -> list:
    if not items:
        return []

    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": [
                {"upc": it["upc"], "quantity": it["quantity"], "price": it["price"], "amount": it["amount"]}
                for it in items
            ],
        }

        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/evaluate-promotions",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code == 200:
            result = r.json()
            promotions = result.get("promotions", [])
            if promotions:
                log(f"✓ Found {len(promotions)} active promotion(s)")
                for promo in promotions:
                    log(f"  • {promo.get('description', 'Promo')}: ${promo.get('discount', 0)}")
            else:
                log("ℹ No matching promotions found")
            return promotions
        else:
            log(f"⚠ Evaluate promotions failed: {r.status_code}")
            return []
    except Exception as e:
        log(f"⚠ Evaluate promotions error: {e}")
        return []


def build_promotion_rewards_xml(items: list, promotions: list) -> tuple:
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

            current_price = get_current_unit_price(item)
            if current_price <= per_unit_new_price:
                continue

            take_qty = min(int(item["quantity"]), remaining_units)
            if take_qty <= 0:
                continue

            reward_id = f"{PROMO_REWARD_PREFIX}-{promo.get('promotionId', promo_counter)}-L{item['line_no']}"
            discount_per_unit = current_price - per_unit_new_price
            line_discount = discount_per_unit * take_qty
            total_discount_for_promo += line_discount

            log(f"  ✓ Promo on line {item['line_no']}: {take_qty} units @ ${per_unit_new_price:.4f}")

            add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{item["line_no"]}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>{per_unit_new_price:.4f}</RewardValue>
      <RewardLimit type="quantity">{take_qty}</RewardLimit>
      <RewardReceiptDescShort>{receipt_short("PROMO")}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{receipt_long(display_name)}</RewardReceiptDescLong>
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


# =============================================================================
# PUNCH CARD EVALUATION
# =============================================================================

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={"customerId": customer_id, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
        else:
            log(f"⚠ Punch evaluate failed: {r.status_code}")
            return {"punchCards": []}
    except Exception as e:
        log(f"⚠ Punch evaluate error: {e}")
        return {"punchCards": []}


def record_punches(customer_id: int, line_items: list, transaction_id: str) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/record-purchase",
            json={
                "customerId": customer_id,
                "lineItems": line_items,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "transactionId": transaction_id,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
        else:
            log(f"⚠ Record punches failed: {r.status_code}")
            return {}
    except Exception as e:
        log(f"⚠ Record punches error: {e}")
        return {}


def redeem_punch_reward(customer_id: int, punch_card_id: int, transaction_id: str) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/redeem",
            json={
                "customerId": customer_id,
                "punchCardId": punch_card_id,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "transactionId": transaction_id,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
        else:
            log(f"⚠ Punch redeem failed: {r.status_code}")
            return {}
    except Exception as e:
        log(f"⚠ Punch redeem error: {e}")
        return {}


def build_punch_rewards_xml(punch_cards: list, eligible_items: list) -> list:
    punch_rewards_xml = []

    if not punch_cards or not eligible_items:
        return punch_rewards_xml

    available_items = list(eligible_items)

    for pc in punch_cards:
        if not available_items:
            log("  ⚠ No eligible items for punch reward")
            continue

        cheapest = min(available_items, key=lambda it: it["price"])
        line_no = cheapest["line_no"]
        punch_card_name = pc.get("punchCardName", "Punch Reward")

        log(f"  🎁 FREE ITEM punch reward on line {line_no} (${cheapest.get('price'):.2f})")

        punch_rewards_xml.append(f"""
    <AddReward>
      <LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>percentOff</RewardDiscountMethod>
      <RewardValue>1.0000</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>{receipt_short("FREE")}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{receipt_long(punch_card_name + " FREE")}</RewardReceiptDescLong>
    </AddReward>""".rstrip())

        pc["rewardApplied"] = True
        available_items = [it for it in available_items if it["line_no"] != line_no]

    return punch_rewards_xml


# =============================================================================
# RESPONSE BUILDERS
# =============================================================================

def build_online_status_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return (
        "<GetLoyaltyOnlineStatusResponse>"
        f"{resp_header(pos_seq, loy_seq)}"
        '<PromptForLoyaltyFlag value="yes"/>'
        "</GetLoyaltyOnlineStatusResponse>"
    )


def build_get_rewards_response(root: ET.Element) -> str:
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record

    pos_seq, loy_seq = get_req_ids(root)

    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone = (root.findtext(".//PhoneNumber") or "").strip()

    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""

    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items):")
        for idx, it in enumerate(items, 1):
            log(f"  {idx}. Line {it['line_no']}: UPC {it['upc']} - {it['description']}")
            log(f"     Qty: {it['quantity']}, Price: ${it['price']:.2f}, Amount: ${it['amount']:.2f}")
        log("=" * 60)

    last_punch_cards = []
    last_punches_to_record = []

    if not loyalty_id and not phone:
        promotions = evaluate_promotions(items)
        promo_rewards, applied_promos, _ = build_promotion_rewards_xml(items, promotions)
        last_promotions_applied = applied_promos

        if promo_rewards:
            rewards_block = "<RewardActions>\n" + "".join(promo_rewards) + "\n  </RewardActions>"
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">Guest</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()
        else:
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

    current_customer = None
    lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/customer-lookup",
            json=lookup_payload,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 404:
            log("ℹ Customer not found")
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer not found</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()
        if r.status_code != 200:
            log(f"⚠ Customer lookup failed: {r.status_code}")
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

        current_customer = r.json()
    except Exception as e:
        log(f"⚠ Customer lookup error: {e}")
        return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

    customer_id = current_customer.get("customerId")
    first_name = current_customer.get("firstName", "")
    last_name = current_customer.get("lastName", "")
    points = current_customer.get("pointsBalance", 0)
    log(f"✓ Customer: {first_name} {last_name} ({points} pts)")

    display_id = loyalty_id or phone or ""
    masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    promotions = evaluate_promotions(items)
    promo_rewards, applied_promos, promo_line_numbers = build_promotion_rewards_xml(items, promotions)
    last_promotions_applied = applied_promos

    if promo_line_numbers:
        log(f"📍 OPTION A: Lines with promo discounts (excluded from punch): {promo_line_numbers}")

    punch_eligible_items = [it for it in items if it.get("line_no") not in promo_line_numbers]

    if punch_eligible_items:
        log(f"🎯 Punch-eligible items (no promo): {len(punch_eligible_items)} of {len(items)}")
    else:
        log("🎯 No punch-eligible items (all got promo discounts)")

    last_punches_to_record = punch_eligible_items
    punch_rewards_xml = []

    if customer_id and punch_eligible_items:
        punch_eval = evaluate_punch_cards(customer_id, punch_eligible_items)
        punch_cards_data = punch_eval.get("punchCards", [])

        if punch_cards_data:
            log("🎯 PUNCH CARD STATUS:")
            for pc in punch_cards_data:
                current = int(pc.get("currentPunches", 0) or 0)
                basket = int(pc.get("punchesFromBasket", 0) or 0)
                required = int(pc.get("punchesRequired", 10) or 10)
                punches_needed = max(0, required - current)

                should_trigger = (current + basket) >= required and required > 0

                status_line = f"  • {pc.get('punchCardName', 'Punch Card')}: {current}/{required}"
                if basket > 0:
                    status_line += f" (+{basket} from basket)"

                if should_trigger:
                    status_line += " 🎁 REWARD TRIGGERED!"
                    pc["rewardTriggered"] = True
                    last_punch_cards.append(pc)
                else:
                    status_line += f" (need {punches_needed} more)"

                log(status_line)

            if last_punch_cards:
                reward_eligible_items = [
                    it for it in punch_eligible_items
                    if it.get("upc") and it.get("price", 0) > 0
                ]
                punch_rewards_xml = build_punch_rewards_xml(last_punch_cards, reward_eligible_items)

    subtotal = sum(it["amount"] for it in items)
    log(f"Subtotal: ${subtotal:.2f}")

    points_reward_xml = ""
    if subtotal > 0 and points >= POINTS_PER_DOLLAR:
        try:
            redemption_req = {
                "customerId": customer_id,
                "eligibleSubtotal": subtotal,
                "lineItems": items,
            }
            rr = SESSION.post(
                f"{BACKEND_URL}/api/pos/calculate-redemption",
                json=redemption_req,
                timeout=REQUEST_TIMEOUT,
            )
            if rr.status_code == 200:
                data = rr.json()
                recommended = float(data.get("recommendedRedemption") or 0.0)
                if recommended > 0:
                    pts_to_use = int(round(recommended * POINTS_PER_DOLLAR))
                    log(f"Points redemption: ${recommended:.2f} ({pts_to_use} pts)")
                    points_reward_xml = f"""
    <AddReward>
      <LoyaltyRewardID>{POINTS_REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{recommended:.2f}</RewardValue>
      <RewardReceiptDescShort>{receipt_short(RECEIPT_SHORT)}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{receipt_long(RECEIPT_LONG)}</RewardReceiptDescLong>
    </AddReward>""".rstrip()
        except Exception as e:
            log(f"⚠ calculate-redemption error: {e}")

    all_rewards = []
    if promo_rewards:
        all_rewards.extend(promo_rewards)
    if punch_rewards_xml:
        all_rewards.extend(punch_rewards_xml)
    if points_reward_xml:
        all_rewards.append(points_reward_xml)

    if all_rewards:
        log(f"📤 Sending {len(all_rewards)} reward(s) to POS")
        rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
    else:
        log("No rewards to apply")
        rewards_block = "<RewardActions/>"

    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()


def build_finalize_response(root: ET.Element) -> str:
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record

    pos_seq, loy_seq = get_req_ids(root)

    items = extract_line_items(root)
    eligible_subtotal = sum(it["amount"] for it in items)
    log(f"Finalize: subtotal ${eligible_subtotal:.2f}")

    applied_dollars = detect_loyalty_tender(root, POINTS_REWARD_ID)
    if applied_dollars > 0:
        log(f"✓ Loyalty tender: ${applied_dollars:.2f}")
        points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR))
    else:
        points_redeemed = 0

    receipt_lines = []

    promo_discount = sum(float(p.get("discount", 0) or 0) for p in last_promotions_applied)

    raw_txn_id = root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or ""
    safe_txn_id = raw_txn_id if raw_txn_id.strip() else f"TXN-{uuid.uuid4().hex[:8].upper()}"

    if current_customer:
        try:
            payload = {
                "customerId": current_customer.get("customerId"),
                "eligibleSubtotal": eligible_subtotal,
                "pointsRedeemed": points_redeemed,
                "transactionId": safe_txn_id,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "lineItems": items,
                "promotions": last_promotions_applied or [],
                "promotionDiscount": promo_discount,
            }

            r = SESSION.post(
                f"{BACKEND_URL}/api/pos/finalize-transaction",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                pts_earned = data.get("pointsEarned", 0)
                new_bal = data.get("newBalance", 0)

                log(f"✓ Finalized: Redeemed {points_redeemed} pts, Earned {pts_earned} pts, Balance {new_bal}")

                if applied_dollars > 0:
                    receipt_lines.append(f"Points Redeemed: {points_redeemed} pts (${applied_dollars:.2f})")

                receipt_lines.append(f"Points Earned: {pts_earned} pts")
                receipt_lines.append(f"New Balance: {new_bal} pts")
            else:
                log(f"⚠ finalize-transaction failed: {r.status_code}")
        except Exception as e:
            log(f"⚠ Finalize error: {e}")

        if last_punches_to_record:
            try:
                punch_result = record_punches(
                    current_customer.get("customerId"),
                    last_punches_to_record,
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
                log(f"⚠ Record punches error: {e}")

        for pc in last_punch_cards or []:
            if pc.get("rewardApplied"):
                try:
                    redeem_result = redeem_punch_reward(
                        current_customer.get("customerId"),
                        pc.get("punchCardId"),
                        safe_txn_id,
                    )
                    if redeem_result.get("redeemed"):
                        receipt_lines.append(f"Punch Reward Redeemed: {pc.get('punchCardName', 'Punch')}")
                except Exception as e:
                    log(f"⚠ Punch redeem error: {e}")

    if not receipt_lines:
        receipt_lines.append("Thank you for shopping at Birdies!")

    clear_session_state()

    receipt_xml = "\n".join(f"      <ReceiptLine>{receipt_line(line)}</ReceiptLine>" for line in receipt_lines)
    return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <ReceiptData>
{receipt_xml}
    </ReceiptData>
  </CustomerMessageData>
</FinalizeRewardsResponse>""".strip()


def build_cancel_txn_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    clear_session_state()
    log("Transaction cancelled, session cleared")
    return f"<CancelTransactionResponse>{resp_header(pos_seq, loy_seq)}</CancelTransactionResponse>"


def build_get_customer_msg_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""
<GetCustomerMessagingResponse>
  {resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <DisplayData>
      <DisplayCommand device="POS-Cashier" sequence="WhenReceived">
        <DisplayLine>Welcome to Birdies Loyalty!</DisplayLine>
      </DisplayCommand>
    </DisplayData>
  </CustomerMessageData>
</GetCustomerMessagingResponse>""".strip()


def build_end_period_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""
<EndPeriodResponse>
  {resp_header(pos_seq, loy_seq)}
  <Result value="success"/>
</EndPeriodResponse>""".strip()


# =============================================================================
# CONNECTION HANDLER
# =============================================================================

def handle_client(conn: socket.socket, addr) -> None:
    peer = f"{addr[0]}:{addr[1]}"

    with POS_SINGLETON_LOCK:
        log(f"POS connected from {peer} (lock acquired)")

        if EXPECTED_POS_IP and addr[0] != EXPECTED_POS_IP:
            log(f"⚠ Rejecting unexpected POS IP: {addr[0]}")
            try:
                conn.close()
            except Exception:
                pass
            return

        try:
            conn.settimeout(180)
            while True:
                hdr = recv_exact(conn, 28)
                if not hdr:
                    log(f"POS disconnected: {peer}")
                    break

                try:
                    action, data_len, chk_data = parse_header(hdr)
                except Exception as e:
                    log(f"Bad header from {peer}: {e}")
                    break

                if action == ACTION_HEARTBEAT:
                    if data_len:
                        _ = recv_exact(conn, data_len)
                    log(f"POS heartbeat from {peer}")
                    continue

                data = recv_exact(conn, data_len)
                if len(data) != data_len or crc32(data) != chk_data:
                    log(f"Payload CRC mismatch from {peer}")
                    break

                try:
                    root, _raw = parse_xml(data)
                except Exception as e:
                    log(f"XML parse error from {peer}: {e}")
                    break

                tag = root.tag.strip()

                if tag == "GetLoyaltyOnlineStatusRequest":
                    send_xml(conn, build_online_status_response(root))
                    send_heartbeat(addr[0])

                elif tag == "GetRewardsRequest":
                    send_xml(conn, build_get_rewards_response(root))

                elif tag == "FinalizeRewardsRequest":
                    send_xml(conn, build_finalize_response(root))

                elif tag == "CancelTransactionRequest":
                    send_xml(conn, build_cancel_txn_response(root))

                elif tag == "GetCustomerMessagingRequest":
                    send_xml(conn, build_get_customer_msg_response(root))

                elif tag == "EndPeriodRequest":
                    send_xml(conn, build_end_period_response(root))

                elif tag in ("BeginCustomerRequest", "EndCustomerRequest", "CancelRedemptionRequest"):
                    log(f"{tag} received (no response required)")

                else:
                    log(f"⚠ Unhandled message type: {tag}")

        except socket.timeout:
            log(f"POS timeout: {peer}")
        except Exception as e:
            log(f"POS error: {peer} - {e}")
        finally:
            clear_session_state()
            try:
                conn.close()
            except Exception:
                pass
            log(f"Connection closed: {peer} (state cleared, lock released)")


# =============================================================================
# SERVER
# =============================================================================

def serve() -> None:
    log("=" * 70)
    log("Birdies Loyalty Edge Agent - COMBINED REWARDS + PUNCH CARDS v1.3")
    log("=" * 70)
    log(f"Store: {PDI_STORE_NUMBER} | POS: {POS_TYPE} | ID: {POS_ID}")
    log(f"Backend: {BACKEND_URL}")
    log(f"Listening on {HOST}:{PORT}")
    log(f"POS Filter: {'Any IP allowed' if not EXPECTED_POS_IP else EXPECTED_POS_IP}")
    log("")
    log("SAFETY FEATURES:")
    log("  - Singleton lock: only one POS connection processed at a time")
    log("  - State cleanup: session cleared on disconnect/error")
    log("  - Consistent transaction IDs: same ID used for all backend calls")
    log("")
    log("HEARTBEAT LOGIC:")
    log("  - Heartbeat sent ONLY on GetLoyaltyOnlineStatusRequest")
    log("  - Proves true end-to-end connectivity (POS -> Edge -> Backend)")
    log("  - Backend shows 'offline' until POS actually communicates")
    log("")
    log("OPTION A LOGIC:")
    log("  - Items with promo discounts do NOT earn punches")
    log("  - Items with promo discounts CANNOT have punch rewards redeemed")
    log("=" * 70)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(64)

    try:
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        log("\nShutting down...")
    finally:
        s.close()


if __name__ == "__main__":
    get_config_from_user()
    serve()
