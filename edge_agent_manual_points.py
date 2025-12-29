#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - MANUAL POINTS REDEMPTION VERSION
-------------------------------------------------------------
• Speaks Gilbarco Passport POSLOYALTY on 10.96.10.175:9000
• Looks up the customer in your Birdies backend and tracks points
• Offers a basket discount to Passport exactly like the working Demo server,
  so the discount really shows up on the POS and receipts.

BEHAVIOR DIFFERENCE:
- Promotional discounts (multi-pack): Auto-apply (InstantRewardFlag=yes)
- Points redemption: Manual selection (InstantRewardFlag=no)
- Customer chooses whether to use points or save them for later
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
# We still call your backend to decide the *amount*, but we keep the ID the same
# so Passport treats it like the known DEMO-1OFF offer.
REWARD_ID      = "DEMO-1OFF"
RECEIPT_SHORT  = "$1OFF"            # <= 8 chars (label on receipt/till)
RECEIPT_LONG   = "Loyalty $ Off"    # <= 24 chars (generic text)
POINTS_PER_DOLLAR = 100             # 100 points = $1.00

# HTTP session & timeout
SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read) seconds

# Live session state (per-connection)
current_customer = None   # dict from backend for the active customer

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
            "edgeVersion": "birdies-edge-db+discount-1.0",
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
    Just strips whitespace and keeps the barcode as-is (5 digits, 10 digits, 12 digits, etc).
    Leading zeros are preserved by keeping it as a string.
    """
    if not upc:
        return ""
    return upc.strip()

def extract_line_items(root: ET.Element):
    """
    Extract item lines from TransactionDetailGroup.
    Only looks at status="normal" item lines.
    Preserves UPCs exactly as they appear (no padding) and includes line numbers for targeting.
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

        # Get unit prices for promotion evaluation
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

        # Use best available price (prefer in order: unit, actual, regular)
        price = unit_price or actual_price or regular_price or 0.0

        items.append(
            {
                "line_no": line_no,
                "upc": upc,
                "description": desc,
                "quantity": qty,
                "amount": amount,
                "price": price,  # Per-unit price for promo evaluation
                "unit_price": unit_price,
                "actual_price": actual_price,
                "regular_price": regular_price,
            }
        )
    return items

def detect_loyalty_tender(root: ET.Element, reward_id: str) -> float:
    """
    Look for a TenderInfo with our LoyaltyRewardID and sum TenderAmount.

    This is how we find out how much discount the POS actually applied.
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

def get_current_unit_price(item: dict) -> float:
    """
    Resolve the effective per-unit price for an item.
    Prefer: unit_price -> actual_price -> regular_price.
    """
    for key in ("unit_price", "actual_price", "regular_price"):
        val = item.get(key, 0.0)
        if val and val > 0:
            return float(val)
    return 0.0

def evaluate_promotions(items: list) -> list:
    """
    Call backend /api/pos/evaluate-promotions to get active promotional discounts.
    Returns list of promotion objects with UPC, line targeting, and discount info.
    """
    if not items:
        log("⚠ No items to evaluate for promotions")
        return []
    
    log(f"🔍 Evaluating promotions for {len(items)} item(s)...")
    
    try:
        # Group items by UPC and sum quantities (backend expects combined quantities)
        upc_groups = {}
        for item in items:
            upc = item["upc"]
            if upc not in upc_groups:
                upc_groups[upc] = {
                    "upc": upc,
                    "quantity": 0,
                    "price": item["price"],  # Per-unit price
                }
            upc_groups[upc]["quantity"] += item["quantity"]
        
        # Convert to list for API
        api_items = list(upc_groups.values())
        
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "items": api_items,
        }
        
        log(f"📤 Calling promotion API: {BACKEND_URL}/api/pos/evaluate-promotions")
        log(f"   Payload: {payload}")
        
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/evaluate-promotions",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        
        log(f"📥 API Response: Status {r.status_code}")
        
        if r.status_code == 200:
            result = r.json()
            log(f"   Response data: {result}")
            promotions = result.get("promotions", [])
            if promotions:
                log(f"✓ Found {len(promotions)} active promotion(s)")
                for promo in promotions:
                    log(f"  • {promo.get('description', 'Promo')}: {promo.get('itemGroupName', 'N/A')} - Discount: ${promo.get('discount', 0)}")
            else:
                log("ℹ️ No matching promotions found")
            return promotions
        else:
            log(f"⚠ Evaluate promotions failed: {r.status_code}")
            log(f"   Response: {r.text}")
            return []
    except Exception as e:
        log(f"⚠ Evaluate promotions error: {e}")
        import traceback
        log(f"   Traceback: {traceback.format_exc()}")
        return []

def build_promotion_rewards_xml(items: list, promotions: list) -> list:
    """
    Convert backend promotion results into Passport AddReward XML blocks.
    Uses line-level newPrice method for multi-buy promotions (e.g., 2-for-$1).
    
    Returns list of XML strings.
    """
    if not promotions:
        return []
    
    # Build UPC to line mapping for targeting
    upc_to_lines = {}
    for item in items:
        upc = item["upc"]
        if upc not in upc_to_lines:
            upc_to_lines[upc] = []
        upc_to_lines[upc].append(item)
    
    add_rewards = []
    promo_counter = 1
    
    for promo in promotions:
        upc = promo.get("upc", "")
        promo_qty = int(promo.get("quantity", 2))  # e.g., 2 for 2-for-$1
        bundle_count = int(promo.get("bundleCount", 0))
        promo_price = float(promo.get("promoPrice", 0))  # Total price for all bundles
        item_group_name = promo.get("itemGroupName", "Promo")
        
        if not upc or bundle_count <= 0:
            continue
        
        # Find lines with this UPC
        matching_lines = upc_to_lines.get(upc, [])
        if not matching_lines:
            continue
        
        # Calculate new per-unit price for the promo
        total_promo_units = bundle_count * promo_qty
        per_unit_new_price = promo_price / total_promo_units if total_promo_units > 0 else 0
        
        # Distribute discount across lines with this UPC
        remaining_units = total_promo_units
        
        for item in matching_lines:
            if remaining_units <= 0:
                break
            
            current_price = get_current_unit_price(item)
            
            # Best-price floor: only lower price if current > new price
            if current_price <= per_unit_new_price:
                continue
            
            take_qty = min(int(item["quantity"]), remaining_units)
            if take_qty <= 0:
                continue
            
            # Generate unique reward ID for this promo
            reward_id = f"PROMO-{promo.get('promotionId', promo_counter)}"
            
            add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{item["line_no"]}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>{per_unit_new_price:.4f}</RewardValue>
      <RewardLimit type="quantity">{take_qty}</RewardLimit>
      <RewardReceiptDescShort>PROMO</RewardReceiptDescShort>
      <RewardReceiptDescLong>{item_group_name[:24]}</RewardReceiptDescLong>
    </AddReward>""".rstrip())
            
            remaining_units -= take_qty
        
        promo_counter += 1
    
    return add_rewards


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
    2) Evaluate promotional discounts for all items (even if not in pricebook).
    3) Calculate points-based redemption discount.
    4) Combine all discounts in a single GetRewardsResponse.
    """
    pos_seq, loy_seq = get_req_ids(root)

    # Extract loyalty id / phone from the request
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone      = (root.findtext(".//PhoneNumber") or "").strip()

    # If LoyaltyID looks like a 10-digit phone number, treat it as phone
    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""

    # Extract and log basket items (with normalized UPCs and line numbers)
    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items):")
        for idx, it in enumerate(items, 1):
            log(f"  {idx}. Line {it['line_no']}: UPC: {it['upc']}")
            log(f"     Desc: {it['description']}")
            log(f"     Qty: {it['quantity']}, Price: ${it['price']:.2f}, Amount: ${it['amount']:.2f}")
        log("=" * 60)
    else:
        log("🛒 No discountable items in basket (yet)")

    log(f"DEBUG: LoyaltyID='{loyalty_id}', PhoneNumber='{phone}'")

    # If we have no identifier at all, still evaluate promotions but no points
    if not loyalty_id and not phone:
        # Still check for promotional discounts (don't require customer ID)
        promotions = evaluate_promotions(items)
        promo_rewards = build_promotion_rewards_xml(items, promotions)
        
        if promo_rewards:
            log("Applying promotional discounts without customer login")
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
  <RewardActions>
  </RewardActions>
</GetRewardsResponse>""".strip()

    # 1) Customer lookup
    global current_customer
    current_customer = None
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
        points     = current_customer.get("pointsBalance", 0)
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

    # 2) Evaluate promotional discounts (works for ANY UPC, even not in pricebook)
    promotions = evaluate_promotions(items)
    promo_rewards = build_promotion_rewards_xml(items, promotions)

    # 3) Calculate points-based redemption discount
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

    # 4) Combine all rewards (promotions + points)
    all_rewards = []
    if promo_rewards:
        all_rewards.extend(promo_rewards)
    if points_reward_xml:
        all_rewards.append(points_reward_xml)

    if all_rewards:
        log(f"Sending {len(all_rewards)} reward(s) to POS")
        rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
    else:
        log("No rewards to apply")
        rewards_block = "<RewardActions/>"

    # IMPORTANT: keep GetRewardsResponse minimal like the working loyalty (1).py
    # No <CustomerMessageData> here – just header, validity flag, and RewardActions.
    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()

def build_finalize_response(root: ET.Element) -> str:
    """
    1) Look at FinalizeRewardsRequest and see how much loyalty tender
       (DEMO-1OFF) Passport actually used.
    2) Tell the Birdies backend how many points were redeemed and earned.
    3) Put a nice message on the receipt.
    """
    pos_seq, loy_seq = get_req_ids(root)

    # Rebuild subtotal from final basket
    items = extract_line_items(root)
    eligible_subtotal = sum(it["amount"] for it in items)
    log(f"Finalize: eligible subtotal ${eligible_subtotal:.2f}")

    # Find the loyalty tender Passport created
    applied_dollars = detect_loyalty_tender(root, REWARD_ID)
    if applied_dollars > 0:
        log(f"✓ Loyalty tender detected in finalize: ${applied_dollars:.2f}")
        points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR))
    else:
        log("ℹ No loyalty tender detected in finalize")
        points_redeemed = 0

    global current_customer
    receipt_lines = []

    if current_customer:
        try:
            transaction_id = (
                root.findtext(".//POSTransactionID")
                or root.findtext(".//TransactionID")
                or ""
            )
            payload = {
                "customerId": current_customer.get("customerId"),
                "eligibleSubtotal": eligible_subtotal,
                "pointsRedeemed": points_redeemed,
                "transactionId": transaction_id,
            }
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

    # If we couldn't reach backend or no customer in session, just say thanks
    if not receipt_lines:
        receipt_lines.append("Thank you for shopping at Birdies!")

    # Clear session for safety
    current_customer = None

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
    global current_customer
    current_customer = None
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
    log("Starting Birdies Loyalty Edge Agent (DB + Discount)")
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
