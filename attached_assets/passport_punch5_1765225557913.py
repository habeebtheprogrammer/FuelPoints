#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PASSPORT PUNCH CARD SUPPORT
--------------------------------------------------------
• Speaks Gilbarco Passport POSLOYALTY on 10.96.10.175:9000
• Looks up the customer in your Birdies backend and tracks points
• Applies punch-card rewards as FREE ITEM discounts
• Offers a basket discount for points redemption exactly like the working Demo server
  (DEMO-1OFF), so the discount really shows up on the POS and receipts.

BEHAVIOR:
- NO price promos (no 2-for-$5, no $1.80 off 2, etc.)
- Punch card rewards:
    - If a reward is ready and customer buys 1 eligible item → that item is free.
    - If customer needs 1 more punch, and buys 2 → one of the 2 is free.
- Points redemption still works (DEMO-1OFF amountOff at basket level).
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
# Configuration
# =========================

# Network
HOST = "10.96.10.175"          # Your PC's Passport NIC IP
PORT = 9000                    # Loyalty port configured on Passport MWS
EXPECTED_POS_IP = "10.5.50.2"  # Restrict to the Passport IP; set None to allow all

# Store / backend identity
PDI_STORE_NUMBER = "1340"      # Your Birdies / PDI store number
POS_ID = "24379"               # POS ID from your config
POS_TYPE = "Passport"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15  # seconds between heartbeats

# These must match the working demo server so Passport applies the reward
VENDOR_NAME = "DemoLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

# Reward config – same shape as loyalty (1).py demo
REWARD_ID      = "DEMO-1OFF"         # points basket coupon
RECEIPT_SHORT  = "$1OFF"             # <= 8 chars (label on receipt/till)
RECEIPT_LONG   = "Loyalty $ Off"     # <= 24 chars (generic text)
POINTS_PER_DOLLAR = 100              # 100 points = $1.00

# Punch reward IDs
PUNCH_REWARD_ID = "PUNCH-REWARD"

# HTTP session & timeout
SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read) seconds

# Live session state (per-connection)
current_customer = None             # dict from backend for the active customer
last_promotions_applied = []        # kept for finalize payload shape (always empty here)
last_punch_cards = []               # punch cards that triggered a reward this txn
last_punches_to_record = []         # line items for recording punches

# POSLOYALTY framing
SIGNATURE = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE   = 1
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
    """
    EXACTLY like the working amount-off script.
    """
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
    """Tell the Birdies backend that this edge agent is alive."""
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "posId": POS_ID,
            "posType": POS_TYPE,
            "posIpAddress": pos_ip or EXPECTED_POS_IP,
            "edgeIpAddress": HOST,
            "edgeVersion": "birdies-edge-passport-punch-1.0",
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
# Helpers to read the POS XML
# =========================

def normalize_upc(upc: str) -> str:
    """
    Preserve UPC exactly as it appears - no padding, no modification.
    Just strips whitespace and keeps the barcode as-is.
    """
    if not upc:
        return ""
    return upc.strip()

def extract_line_items(root: ET.Element):
    """
    Extract item lines from TransactionDetailGroup.
    Only looks at status="normal" item lines.
    Preserves UPCs exactly as they appear and includes line numbers for targeting.
    Accepts ANY item, even if not in the pricebook.
    """
    items = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        status = (tline.get("status") or "").strip().lower()
        if status and status != "normal":
            continue
        il = tline.find("./ItemLine")
        if il is None:
            continue

        # Get line number for targeting rewards
        try:
            line_no = int(tline.findtext("./LineNumber", "0"))
        except Exception:
            line_no = 0

        # Extract and normalize UPC
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

        # Get unit prices for reference
        def to_f(txt):
            try:
                return float(txt or 0)
            except Exception:
                return 0.0

        unit_price = to_f(unit_price_txt)
        actual_price = to_f(actual_price_txt)
        regular_price = to_f(regular_price_txt)

        # Use best available price
        price = unit_price or actual_price or regular_price or 0.0

        items.append(
            {
                "line_no": line_no,
                "upc": upc,
                "description": desc,
                "quantity": qty,
                "amount": amount,
                "price": price,            # per-unit
                "unit_price": unit_price,
                "actual_price": actual_price,
                "regular_price": regular_price,
            }
        )
    return items

def detect_loyalty_tender(root: ET.Element, reward_id: str) -> float:
    """
    Look for a TenderInfo with our LoyaltyRewardID and sum TenderAmount.
    This is how we find out how much discount the POS actually applied for points.
    """
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


# =========================
# Punch Card API Calls
# =========================

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    """
    Evaluate punch card status WITH projected punches from current basket.
    Enables immediate reward application in the qualifying transaction.
    """
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={
                "customerId": customer_id,
                "lineItems": line_items,
            },
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


# =========================
# Response builders
# =========================

def build_online_status_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return (
        "<GetLoyaltyOnlineStatusResponse>"
        f"{resp_header(pos_seq, loy_seq)}"
        '<PromptForLoyaltyFlag value="yes"/>'
        "</GetLoyaltyOnlineStatusResponse>"
    )


def build_get_rewards_response(root: ET.Element) -> str:
    """
    1) Look up the customer in the Birdies backend using loyalty ID or phone.
    2) Evaluate punch card status (with projected punches).
    3) If a punch reward is earned → apply FREE ITEM (item-level newPrice=0).
    4) Calculate points-based redemption discount (DEMO-1OFF).
    5) Combine punch rewards + points in a single GetRewardsResponse.
    """
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record

    pos_seq, loy_seq = get_req_ids(root)

    # Extract loyalty id / phone from the request
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone      = (root.findtext(".//PhoneNumber") or "").strip()

    # If LoyaltyID looks like a 10-digit phone number, treat it as phone
    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""

    # Extract and log basket items
    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items):")
        for idx, it in enumerate(items, 1):
            log(
                f"  {idx}. Line {it['line_no']}: UPC: {it['upc']} | "
                f"Qty: {it['quantity']} | Price: ${it['price']:.2f} | Amount: ${it['amount']:.2f}"
            )
        log("=" * 60)
    else:
        log("🛒 No discountable items in basket (yet)")

    log(f"DEBUG: LoyaltyID='{loyalty_id}', PhoneNumber='{phone}'")

    # Reset state for this transaction
    current_customer = None
    last_promotions_applied = []   # we aren't doing promos here
    last_punch_cards = []
    last_punches_to_record = []

    # If we have no identifier at all, no punch / points; just require ID
    if not loyalty_id and not phone:
        return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions>
  </RewardActions>
</GetRewardsResponse>""".strip()

    # 1) Customer lookup
    lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/customer-lookup",
            json=lookup_payload,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 404:
            ident = loyalty_id or phone
            log(f"⚠ Customer not found: {ident}")
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
        first_name = current_customer.get("firstName", "")
        last_name  = current_customer.get("lastName", "")
        points     = int(current_customer.get("pointsBalance", 0) or 0)
        customer_id = current_customer.get("customerId")
        log(f"✓ Customer found: {first_name} {last_name} ({points} pts)")
    except Exception as e:
        log(f"⚠ Customer lookup error: {e}")
        return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions>
  </RewardActions>
</GetRewardsResponse>""".strip()

    # Masked loyalty ID for display (match demo behavior)
    display_id = loyalty_id or phone or ""
    masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    # Store items so we can record punches on finalize
    last_punches_to_record = items

    # 2) Evaluate punch cards
    punch_rewards_xml = []
    last_punch_cards = []

    if customer_id and items:
        punch_eval = evaluate_punch_cards(customer_id, items)
        punch_cards_data = punch_eval.get("punchCards", [])

        if punch_cards_data:
            log("🎯 PUNCH CARD STATUS:")
            for pc in punch_cards_data:
                current = int(pc.get("currentPunches", 0) or 0)
                basket  = int(pc.get("punchesFromBasket", 0) or 0)
                required = int(pc.get("punchesRequired", 10) or 10)
                punches_needed = max(0, required - current)

                already_full = current >= required
                buying_extra = basket > punches_needed
                should_trigger = already_full or buying_extra

                status_line = f"  • {pc.get('punchCardName', 'Punch Card')}: {current}/{required} stored"
                if basket > 0:
                    status_line += f" + {basket} from basket"
                if already_full:
                    status_line += " [FULL CARD]"
                elif buying_extra:
                    status_line += f" [BUYING {basket} > {punches_needed} NEEDED]"
                if should_trigger:
                    status_line += " 🎁 REWARD TRIGGERED!"
                    pc["rewardTriggered"] = True
                    last_punch_cards.append(pc)
                else:
                    status_line += f" (need {punches_needed} more to trigger)"

                log(status_line)

            # Build FREE ITEM rewards: one unit of the cheapest eligible item per triggered card
            if last_punch_cards:
                # Eligible items = any real UPC item with positive amount
                eligible_items = [
                    it for it in items
                    if it.get("upc") and it.get("amount", 0) > 0 and it.get("price", 0) > 0
                ]

                for pc in last_punch_cards:
                    if not eligible_items:
                        log(
                            "  ⚠ Cannot apply FREE ITEM reward - "
                            "no eligible UPC items in basket"
                        )
                        continue

                    # Choose the cheapest item in the basket
                    cheapest = min(eligible_items, key=lambda it: it["price"])
                    line_no = cheapest["line_no"]
                    unit_price = float(cheapest["price"] or 0.0)
                    punch_card_name = pc.get("punchCardName", "Punch Reward")

                    log(
                        f"  🎁 Applying FREE ITEM punch reward for card "
                        f"'{punch_card_name}' on line {line_no} "
                        f"(UPC {cheapest['upc']} @ ${unit_price:.2f})"
                    )

                    # item-level FREE: newPrice=0.0 for quantity 1
                    punch_rewards_xml.append(f"""
    <AddReward>
      <LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>0.0000</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>FREE</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_card_name} FREE ITEM</RewardReceiptDescLong>
    </AddReward>""".rstrip())
                    pc["rewardApplied"] = True

    # 3) Points-based redemption discount (basket amountOff DEMO-1OFF)
    subtotal = sum(it["amount"] for it in items)
    log(f"Eligible subtotal: ${subtotal:.2f}")

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
      <LoyaltyRewardID>{REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="no"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{recommended:.2f}</RewardValue>
      <RewardReceiptDescShort>{RECEIPT_SHORT}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{RECEIPT_LONG}</RewardReceiptDescLong>
    </AddReward>""".rstrip()
                else:
                    log("Backend recommended $0.00 points redemption")
            else:
                log(f"⚠ calculate-redemption failed: {rr.status_code}")
        except Exception as e:
            log(f"⚠ calculate-redemption error: {e}")
    else:
        log("Customer does not have enough points for redemption, or subtotal is $0.00")

    # 4) Combine punch rewards + points
    all_rewards = []
    if punch_rewards_xml:
        all_rewards.extend(punch_rewards_xml)
    if points_reward_xml:
        all_rewards.append(points_reward_xml)

    if all_rewards:
        log(f"Sending {len(all_rewards)} reward(s) to POS")
        rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
    else:
        log("No rewards to apply")
        rewards_block = "<RewardActions/>"

    # Same minimal GetRewardsResponse as working script
    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()


def build_finalize_response(root: ET.Element) -> str:
    """
    1) Look at FinalizeRewardsRequest and see how much loyalty tender
       (DEMO-1OFF) Passport actually used (points).
    2) Tell the Birdies backend how many points were redeemed and earned.
    3) Record punches and redeem punch-card rewards that were applied.
    4) Put a nice message on the receipt.
    """
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record

    pos_seq, loy_seq = get_req_ids(root)

    # Rebuild subtotal from final basket
    items = extract_line_items(root)
    eligible_subtotal = sum(it["amount"] for it in items)
    log(f"Finalize: eligible subtotal ${eligible_subtotal:.2f}")

    # Find the loyalty tender Passport created for points
    applied_dollars = detect_loyalty_tender(root, REWARD_ID)
    if applied_dollars > 0:
        log(f"✓ Loyalty tender detected in finalize: ${applied_dollars:.2f}")
        points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR))
    else:
        log("ℹ No loyalty tender detected in finalize")
        points_redeemed = 0

    receipt_lines = []

    # Promotions are disabled, but we keep the field for backend schema
    promo_discount = 0.0

    transaction_id = (
        root.findtext(".//POSTransactionID")
        or root.findtext(".//TransactionID")
        or ""
    )

    if current_customer:
        try:
            payload = {
                "customerId": current_customer.get("customerId"),
                "eligibleSubtotal": eligible_subtotal,
                "pointsRedeemed": points_redeemed,
                "transactionId": transaction_id,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "lineItems": items,
                "promotions": last_promotions_applied or [],
                "promotionDiscount": promo_discount,
            }
            log(
                f"📤 Finalizing transaction: store={PDI_STORE_NUMBER}, "
                f"subtotal=${eligible_subtotal:.2f}, promoDiscount=${promo_discount:.2f}"
            )
            r = SESSION.post(
                f"{BACKEND_URL}/api/pos/finalize-transaction",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                pts_earned = data.get("pointsEarned", 0)
                new_bal    = data.get("newBalance", 0)

                log(
                    "✓ Transaction finalized: "
                    f"Redeemed {points_redeemed} pts (${applied_dollars:.2f}); "
                    f"Earned {pts_earned} pts; New balance {new_bal} pts"
                )

                if applied_dollars > 0:
                    receipt_lines.append(
                        f"Loyalty Discount Applied: ${applied_dollars:.2f}"
                    )
                    receipt_lines.append(
                        f"Points Redeemed: {points_redeemed} pts (${applied_dollars:.2f})"
                    )
                receipt_lines.append(f"Points Earned: {pts_earned} pts")
                receipt_lines.append(f"New Balance: {new_bal} pts")
            else:
                log(f"⚠ finalize-transaction failed: {r.status_code}")
        except Exception as e:
            log(f"⚠ Finalize error: {e}")

        # Record punches
        if last_punches_to_record:
            try:
                punch_result = record_punches(
                    current_customer.get("customerId"),
                    last_punches_to_record,
                    transaction_id or f"TXN-{uuid.uuid4().hex[:8].upper()}",
                )
                punches_recorded = punch_result.get("punchesRecorded", [])
                if punches_recorded:
                    log("  🎯 PUNCHES RECORDED:")
                    for p in punches_recorded:
                        log(
                            f"     • {p.get('punchCardName')}: "
                            f"+{p.get('punchesAdded')} → "
                            f"{p.get('currentPunches')}/{p.get('punchesRequired')}"
                        )
            except Exception as e:
                log(f"⚠ Record punches error: {e}")

        # Redeem punch rewards that were actually applied
        for pc in last_punch_cards:
            if pc.get("rewardApplied"):
                try:
                    redeem_result = redeem_punch_reward(
                        current_customer.get("customerId"),
                        pc.get("punchCardId"),
                        transaction_id or f"TXN-{uuid.uuid4().hex[:8].upper()}",
                    )
                    if redeem_result.get("success"):
                        log(f"  🎁 Redeemed punch reward: {pc.get('punchCardName')}")
                except Exception as e:
                    log(f"⚠ Punch redeem error: {e}")
            elif pc.get("rewardTriggered"):
                log(
                    "  ⚠ Reward was triggered but not applied "
                    f"(no discount sent): {pc.get('punchCardName')}"
                )

    # If we couldn't reach backend or no customer in session, just say thanks
    if not receipt_lines:
        receipt_lines.append("Thank you for shopping at Birdies!")

    # Clear session state
    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []

    receipt_xml = "\n".join(
        f"      <ReceiptLine>{line}</ReceiptLine>" for line in receipt_lines
    )
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
    global current_customer, last_promotions_applied, last_punch_cards, last_punches_to_record
    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []
    log("Transaction cancelled, customer session cleared")
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


# =========================
# Connection handler
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    log(f"POS connected from {peer}")

    # Optional safety: only accept the Passport IP
    if EXPECTED_POS_IP and addr[0] != EXPECTED_POS_IP:
        log(f"⚠ Rejecting unexpected POS IP: {addr[0]}")
        try:
            conn.close()
        except Exception:
            pass
        return

    # First heartbeat with the real POS IP
    send_heartbeat(addr[0])

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

            # POS heartbeat
            if action == ACTION_HEARTBEAT:
                if data_len:
                    _ = recv_exact(conn, data_len)
                log(f"POS heartbeat from {peer}")
                continue

            data = recv_exact(conn, data_len)
            if len(data) != data_len or crc32(data) != chk_data:
                log(f"Payload CRC/length mismatch from {peer}")
                break

            try:
                root, _raw = parse_xml(data)
            except Exception as e:
                log(f"XML parse error from {peer}: {e}")
                break

            tag = root.tag.strip()

            if tag == "GetLoyaltyOnlineStatusRequest":
                send_xml(conn, build_online_status_response(root))
                # Keep backend updated with real POS IP
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
                # Informational only — no response required
                log(f"{tag} received (no response required)")

            else:
                log(f"⚠ Unhandled message type: {tag}")

    except socket.timeout:
        log(f"POS timeout: {peer}")
    except Exception as e:
        log(f"POS error: {peer} - {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        log(f"Connection closed: {peer}")


# =========================
# Server
# =========================

def serve() -> None:
    log("Starting Birdies Loyalty Edge Agent (Passport Punch Cards)")
    log(f"Store: {PDI_STORE_NUMBER} | POS Type: {POS_TYPE} | POS ID: {POS_ID}")
    log(f"Backend: {BACKEND_URL}")
    log(f"Listening on {HOST}:{PORT}")

    # Kick off background heartbeat thread
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    log("✓ Heartbeat thread started")

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
    serve()
