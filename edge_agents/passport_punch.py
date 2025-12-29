#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PUNCH CARD SUPPORT (Passport POSLOYALTY)
----------------------------------------------------------------------
• Speaks Gilbarco Passport POSLOYALTY protocol over TCP
• Full punch card loyalty system:
    - Records punches when customers buy items from punch card groups
    - Shows punch status during customer lookup
    - Applies punch card rewards when earned (free item, % off, $ off)
• Maintains compatibility with existing promotions and points redemption

PUNCH CARD FLOW:
1. GetLoyaltyOnlineStatus → Returns success (POS is online)
2. GetRewards → Lookup customer + check punch status + apply rewards if earned
3. FinalizeRewards → Record punches + redeem rewards + finalize transaction
"""

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

# =========================
# Configuration - EDIT THESE
# =========================

HOST = "0.0.0.0"          # Bind to all interfaces (or specific IP like "10.96.10.175")
PORT = 9000               # Loyalty port configured on Passport MWS
EXPECTED_POS_IP = None    # Set to Passport IP to restrict (e.g., "10.5.50.2")

PDI_STORE_NUMBER = "1340" # Birdies / PDI store number
POS_ID = "24379"
POS_TYPE = "Passport"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15   # seconds

VENDOR_NAME = "DemoLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

REWARD_ID         = "DEMO-1OFF"
PUNCH_REWARD_ID   = "PUNCH-REWARD"
RECEIPT_SHORT     = "$1OFF"
RECEIPT_LONG      = "Loyalty $ Off"
POINTS_PER_DOLLAR = 100

SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read)

current_customer = None
last_promotions_applied = []
last_punch_cards = []
last_punches_to_record = []

SIGNATURE      = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE = 1
ACTION_HEARTBEAT = 2

# =========================
# Utilities
# =========================

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

# =========================
# Backend heartbeat
# =========================

def send_heartbeat(pos_ip: str = None) -> None:
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "posId": POS_ID,
            "posType": POS_TYPE,
            "posIpAddress": pos_ip or EXPECTED_POS_IP,
            "edgeIpAddress": HOST,
            "edgeVersion": "birdies-edge-punchcard-1.0",
        }
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/heartbeat",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            log(f"✓ Heartbeat sent to backend (Store {PDI_STORE_NUMBER})")
        else:
            log(f"⚠ Heartbeat failed: {r.status_code}")
    except Exception as e:
        log(f"⚠ Heartbeat error: {e}")

def heartbeat_loop() -> None:
    while True:
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)

# =========================
# Basket parsing helpers
# =========================

def normalize_upc(upc: str) -> str:
    return (upc or "").strip()

def extract_line_items(root: ET.Element):
    """
    Extract discountable item lines from POSLOYALTY XML.
    Ignore TransactionTax-only lines.
    """
    items = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        status = (tline.get("status") or "").strip().lower()
        if status and status != "normal":
            continue

        il = tline.find("./ItemLine")
        if il is None:
            continue  # skip tax / tender lines

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
        atxt = il.findtext("SalesAmount")
        unit_price_txt    = il.findtext("UnitPrice", "0")
        actual_price_txt  = il.findtext("ActualSalesPrice", "0")
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

# =========================
# Punch Card API Calls
# =========================

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    """Evaluate punch card status including current basket."""
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={
                "customerId": customer_id,
                "lineItems": line_items,
            },
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        else:
            log(f"⚠ Punch evaluate failed: {r.status_code}")
            return {"punchCards": [], "rewardsReady": []}
    except Exception as e:
        log(f"⚠ Punch evaluate error: {e}")
        return {"punchCards": [], "rewardsReady": []}

def record_punches(customer_id: int, line_items: list, transaction_id: str) -> dict:
    """Record punches after transaction is finalized."""
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/record-purchase",
            json={
                "customerId": customer_id,
                "lineItems": line_items,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "transactionId": transaction_id,
            },
            timeout=REQUEST_TIMEOUT
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
    """Redeem a punch card reward."""
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/redeem",
            json={
                "customerId": customer_id,
                "punchCardId": punch_card_id,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "transactionId": transaction_id,
            },
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        else:
            log(f"⚠ Punch redeem failed: {r.status_code}")
            return {}
    except Exception as e:
        log(f"⚠ Punch redeem error: {e}")
        return {}

# =========================
# Promotions (stub)
# =========================

def evaluate_promotions(items: list) -> list:
    """Call backend to evaluate promos (currently just logs)."""
    if not items:
        return []

    log(f"🔍 Evaluating promotions for {len(items)} item(s)...")
    try:
        upc_groups = {}
        for item in items:
            upc = item["upc"]
            if not upc:
                continue
            if upc not in upc_groups:
                upc_groups[upc] = {"upc": upc, "quantity": 0, "price": item["price"]}
            upc_groups[upc]["quantity"] += int(item["quantity"])

        if not upc_groups:
            log("  ℹ No UPC items to evaluate for promotions")
            return []

        payload = {"pdiStoreNumber": PDI_STORE_NUMBER, "items": list(upc_groups.values())}
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/evaluate-promotions",
            json=payload,
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            promotions = r.json().get("promotions", [])
            log(f"  ✓ Backend returned {len(promotions)} promotion(s)")
            return promotions
        else:
            log(f"  ⚠ Promotion evaluation failed: {r.status_code}")
            return []
    except Exception as e:
        log(f"  ⚠ Promotion evaluation error: {e}")
        return []

# =========================
# Response Builders
# =========================

def build_online_status_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    log("✓ Responding to GetLoyaltyOnlineStatus - Loyalty is ONLINE")
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
    phone      = (root.findtext(".//PhoneNumber") or "").strip()

    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""

    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items):")
        for idx, it in enumerate(items, 1):
            log(f"  {idx}. Line {it['line_no']}: UPC: {it['upc']}")
            log(f"     Desc: {it['description']}")
            log(f"     Qty: {it['quantity']}, Price: ${it['price']:.2f}, Amount: ${it['amount']:.2f}")
        log("=" * 60)

    last_punches_to_record = items
    last_punch_cards = []
    last_promotions_applied = []

    if not loyalty_id and not phone:
        _ = evaluate_promotions(items)
        return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions>
  </RewardActions>
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
            log(f"⚠ Customer not found: {loyalty_id or phone}")
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer not found</LoyaltyIDValidFlag>
  <RewardActions>
  </RewardActions>
</GetRewardsResponse>""".strip()
        if r.status_code != 200:
            log(f"⚠ Customer lookup failed: {r.status_code}")
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions>
  </RewardActions>
</GetRewardsResponse>""".strip()
        current_customer = r.json()
    except Exception as e:
        log(f"⚠ Customer lookup error: {e}")
        return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions>
  </RewardActions>
</GetRewardsResponse>""".strip()

    customer_id = current_customer.get("customerId")
    first_name  = current_customer.get("firstName", "")
    last_name   = current_customer.get("lastName", "")
    points      = current_customer.get("pointsBalance", 0)

    log(f"✓ Customer found: {first_name} {last_name} ({points} pts)")

    punch_eval = evaluate_punch_cards(customer_id, items)
    punch_cards_data = punch_eval.get("punchCards", [])

    if punch_cards_data:
        log("🎯 PUNCH CARD STATUS (hybrid reward logic):")
        for pc in punch_cards_data:
            current  = pc.get('currentPunches', 0)
            basket   = pc.get('punchesFromBasket', 0)
            required = pc.get('punchesRequired', 10)
            punches_needed = max(0, required - current)

            already_full = current >= required
            buying_extra = basket > punches_needed
            should_trigger = already_full or buying_extra

            status_line = f"  • {pc.get('punchCardName')}: {current}/{required} stored"
            if basket > 0:
                status_line += f" + {basket} basket"
            if already_full:
                status_line += " [FULL CARD]"
            elif buying_extra:
                status_line += f" [BUYING {basket} > {punches_needed} NEEDED]"

            if should_trigger:
                status_line += " 🎁 REWARD TRIGGERED!"
                pc['rewardTriggered'] = True
                last_punch_cards.append(pc)
            else:
                status_line += f" (need {punches_needed} more to trigger)"
            log(status_line)

    add_rewards = []

    for pc in last_punch_cards:
        reward_type  = pc.get('rewardType', 'free_item')
        reward_value = pc.get('rewardValue', '0')
        punch_card_name = pc.get('punchCardName', 'Punch Reward')

        if reward_type in ('dollar_off', 'amount_off'):
            try:
                dollar_off = float(reward_value)
                add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{dollar_off:.2f}</RewardValue>
      <RewardReceiptDescShort>PUNCH</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_card_name}</RewardReceiptDescLong>
    </AddReward>""")
                pc['rewardApplied'] = True
                log(f"  🎁 Applying punch reward: ${dollar_off:.2f} off")
            except Exception as e:
                log(f"  ⚠ Error applying dollar_off punch reward: {e}")

        elif reward_type == 'percent_off':
            subtotal = sum(it["amount"] for it in items)
            try:
                pct = float(reward_value)
                dollar_off = subtotal * (pct / 100)
                add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{dollar_off:.2f}</RewardValue>
      <RewardReceiptDescShort>PUNCH</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_card_name} {pct:.0f}% Off</RewardReceiptDescLong>
    </AddReward>""")
                pc['rewardApplied'] = True
                log(f"  🎁 Applying punch reward: {pct}% off (${dollar_off:.2f})")
            except Exception as e:
                log(f"  ⚠ Error applying percent_off punch reward: {e}")

        elif reward_type == 'free_item':
            # ✅ Use line-level newPrice on cheapest UPC item (Passport-friendly)
            eligible_items = [
                it for it in items
                if it.get("upc") and it.get("amount", 0) > 0
            ]
            if eligible_items:
                free_item = min(eligible_items, key=lambda it: it["amount"])
                line_no = free_item["line_no"]
                unit_price = free_item["price"]
                add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>0.00</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>FREE</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_card_name} FREE ITEM</RewardReceiptDescLong>
    </AddReward>""")
                pc['rewardApplied'] = True
                log(f"  🎁 Applying FREE ITEM punch reward: line {line_no} 1 unit @ $0.00 (was ${unit_price:.2f})")
            else:
                log("  ⚠ Cannot apply FREE ITEM reward – no eligible UPC items in basket")

    # Log promos (optionally used later for reporting)
    last_promotions_applied = evaluate_promotions(items)

    masked = (loyalty_id[-4:].rjust(10, "*")) if loyalty_id else "****"
    rewards_block = "\n".join(add_rewards) if add_rewards else ""

    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{first_name} {last_name}</LoyaltyIDValidFlag>
  <LoyaltyMemberID>{masked}</LoyaltyMemberID>
  <PointsBalance>{points}</PointsBalance>
  <RewardActions>
{rewards_block}
  </RewardActions>
</GetRewardsResponse>""".strip()

def build_finalize_response(root: ET.Element) -> str:
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record

    pos_seq, loy_seq = get_req_ids(root)

    if not current_customer:
        log("⚠ No customer in session for finalize")
        return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
</FinalizeRewardsResponse>""".strip()

    customer_id = current_customer.get("customerId")
    transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"

    subtotal = 0.0
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        il = tline.find("./ItemLine")
        if il is not None:
            try:
                subtotal += float(il.findtext("SalesAmount") or 0)
            except Exception:
                pass

    log(f"🏁 Finalizing transaction: Customer {customer_id}, Subtotal ${subtotal:.2f}")

    try:
        finalize_payload = {
            "customerId": customer_id,
            "eligibleSubtotal": subtotal,
            "transactionId": transaction_id,
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": last_punches_to_record,
            "promotions": last_promotions_applied,
            "promotionDiscount": 0,
        }
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/finalize-transaction",
            json=finalize_payload,
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            result = r.json()
            log(f"  ✓ Points: earned {result.get('pointsEarned', 0)}, balance {result.get('newBalance', 0)}")
        else:
            log(f"  ⚠ Finalize-transaction failed: {r.status_code}")
    except Exception as e:
        log(f"  ⚠ Finalize error: {e}")

    if last_punches_to_record:
        punch_result = record_punches(customer_id, last_punches_to_record, transaction_id)
        punches_recorded = punch_result.get('punchesRecorded', [])
        if punches_recorded:
            log("  🎯 PUNCHES RECORDED:")
            for p in punches_recorded:
                log(
                    f"     • {p.get('punchCardName')}: "
                    f"+{p.get('punchesAdded')} → "
                    f"{p.get('currentPunches')}/{p.get('punchesRequired')}"
                )

    for pc in last_punch_cards:
        if pc.get('rewardApplied'):
            redeem_result = redeem_punch_reward(customer_id, pc.get('punchCardId'), transaction_id)
            if redeem_result.get('success'):
                log(f"  🎁 Redeemed punch reward: {pc.get('punchCardName')}")
        elif pc.get('rewardTriggered'):
            log(f"  ⚠ Reward was triggered but not applied (no discount sent): {pc.get('punchCardName')}")

    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []

    return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
</FinalizeRewardsResponse>""".strip()

def build_cancel_response(root: ET.Element) -> str:
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record

    pos_seq, loy_seq = get_req_ids(root)
    log("Transaction cancelled by POS")

    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []

    return f"""
<CancelTransactionResponse>
  {resp_header(pos_seq, loy_seq)}
</CancelTransactionResponse>""".strip()

# =========================
# TCP Server
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    log(f"🔌 Connection from {addr}")

    if EXPECTED_POS_IP and addr[0] != EXPECTED_POS_IP:
        log(f"⚠ Rejecting connection from {addr[0]} (expected {EXPECTED_POS_IP})")
        conn.close()
        return

    try:
        while True:
            hdr = recv_exact(conn, 28)
            if not hdr:
                log(f"Connection closed by {addr}")
                break

            try:
                action, data_len, chk_data = parse_header(hdr)
            except Exception as e:
                log(f"⚠ Header parse error: {e}")
                break

            if action == ACTION_HEARTBEAT:
                log("↔ Heartbeat ping from POS")
                continue

            xml_bytes = recv_exact(conn, data_len)
            if not xml_bytes:
                log("Connection closed during payload read")
                break

            if crc32(xml_bytes) != chk_data:
                log("⚠ Data CRC mismatch")
                continue

            try:
                root, raw = parse_xml(xml_bytes)
            except Exception as e:
                log(f"⚠ XML parse error: {e}")
                continue

            tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

            if tag == "GetLoyaltyOnlineStatusRequest":
                resp = build_online_status_response(root)
            elif tag == "GetRewardsRequest":
                resp = build_get_rewards_response(root)
            elif tag == "FinalizeRewardsRequest":
                resp = build_finalize_response(root)
            elif tag == "CancelTransactionRequest":
                resp = build_cancel_response(root)
            else:
                log(f"⚠ Unknown request type: {tag}")
                continue

            send_xml(conn, resp)

    except Exception as e:
        log(f"⚠ Client handler error: {e}")
    finally:
        conn.close()
        log(f"Connection closed: {addr}")

def main():
    log("=" * 60)
    log("🐦 BIRDIES LOYALTY EDGE AGENT - PUNCH CARD SUPPORT")
    log("=" * 60)
    log(f"  Store: {PDI_STORE_NUMBER}")
    log(f"  Backend: {BACKEND_URL}")
    log(f"  Listening on: {HOST}:{PORT}")
    log("=" * 60)

    threading.Thread(target=heartbeat_loop, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)

    log(f"✓ TCP server listening on {HOST}:{PORT}")
    log("Waiting for Passport POS connections...")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()
