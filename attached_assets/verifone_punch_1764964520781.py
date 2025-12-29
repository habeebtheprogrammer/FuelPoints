#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PUNCH CARD SUPPORT (Verifone EPS)
---------------------------------------------------------------
• Speaks Verifone EPS Loyalty Host interface (PCATS XML over TCP)
• Full punch card loyalty system:
    - Records punches when customers buy items from punch card groups
    - Shows punch status during customer lookup
    - Applies punch card rewards when earned (free item, % off, $ off)
• Maintains compatibility with existing promotions and points redemption

CONFIGURATION (edit these before deploying):
- HOST: IP address to bind the TCP server (0.0.0.0 for all interfaces)
- PORT: TCP port (typically 9000)
- PDI_STORE_NUMBER: Your store's PDI number
- BACKEND_URL: Birdies backend API URL

EPS SPECIFICS:
- 4-byte big-endian length prefix framing
- PCATS XML with namespaces
- ResponseHeader must include overallResult="success"
- Heartbeat via GetLoyaltyOnlineStatus

PUNCH CARD FLOW:
1. GetLoyaltyOnlineStatus → Returns success (POS is online)
2. GetRewardsRequest → Lookup customer + check punch status + apply rewards if earned
3. FinalizeRewardsRequest → Record punches + redeem rewards + finalize transaction
"""

import socket
import threading
import datetime
import struct
import uuid
import time
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

# =========================
# Configuration - EDIT THESE
# =========================

# Network - bind address and port for TCP server
HOST = "0.0.0.0"              # Bind to all interfaces
PORT = 9000                   # EPS FEP table should target this port
EXPECTED_EPS_IP = None        # Set to Commander IP to restrict (e.g., "10.5.50.1")

# Store / backend identity
PDI_STORE_NUMBER = "1310"     # Your Birdies / PDI store number
POS_ID = "24379"              # POS ID from your config
POS_TYPE = "Verifone-EPS"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15  # seconds between heartbeats to backend

# PCATS / Vendor naming in responses
VENDOR_NAME = "BirdiesLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

# Reward identifiers
REWARD_ID         = "DEMO-1OFF"
PUNCH_REWARD_ID   = "PUNCH-REWARD"
RECEIPT_SHORT     = "$OFF"
RECEIPT_LONG      = "Loyalty Discount"
POINTS_PER_DOLLAR = 100

# HTTP session & timeout
SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read) seconds

# Live session state (per-connection)
current_customer = None
last_points_recommended = 0.0
last_promotions_applied = []
last_punch_cards = []
last_punches_to_record = []

# PCATS Namespaces
NS_LOY   = "http://www.pcats.org/schema/naxml/loyalty/v01"
NS_CORE  = "http://www.pcats.org/schema/core/v01"
NS_POSBO = "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"

# Aliases for outgoing XML
NS_DECLS = (
    f'xmlns:ns2="{NS_POSBO}" '
    f'xmlns:ns4="{NS_CORE}" '
    f'xmlns:ns3="{NS_LOY}"'
)


# =========================
# Utilities
# =========================

def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def pretty_xml(xml_bytes: bytes) -> str:
    try:
        return minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        try:
            return xml_bytes.decode("utf-8", errors="replace")
        except Exception:
            return str(xml_bytes)

def strip_namespaces(elem: ET.Element) -> ET.Element:
    """Strip namespace prefixes for easier XPath."""
    for e in elem.iter():
        if isinstance(e.tag, str) and '}' in e.tag:
            e.tag = e.tag.split('}', 1)[1]
    return elem

# EPS framing: 4-byte big-endian length + UTF-8 XML
def send_xml(conn: socket.socket, xml_str: str) -> None:
    xml_bytes = xml_str.encode("utf-8")
    frame = struct.pack(">I", len(xml_bytes)) + xml_bytes
    conn.sendall(frame)
    log("→ Sent to EPS:\n" + pretty_xml(xml_bytes))

def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf

def recv_frame(conn: socket.socket) -> bytes:
    hdr = recv_exact(conn, 4)
    if not hdr:
        return b""
    length = struct.unpack(">I", hdr)[0]
    if length <= 0:
        return b""
    return recv_exact(conn, length)

def parse_xml(xml_bytes: bytes):
    raw = xml_bytes.decode("utf-8", errors="replace")
    log("← Received from EPS:\n" + pretty_xml(xml_bytes))
    root = ET.fromstring(raw)
    root = strip_namespaces(root)
    return root, raw

def get_req_ids(root: ET.Element):
    pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
    loy_seq = root.findtext(".//LoyaltySequenceID")
    if not loy_seq or not loy_seq.strip():
        loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
    return pos_seq, loy_seq

def resp_header(pos_seq: str, loy_seq: str) -> str:
    # EPS requires overallResult in ResponseHeader
    return (
        f'<ns3:ResponseHeader overallResult="success">'
        f'<ns3:POSLoyaltyInterfaceVersion>{IFACE_VER}</ns3:POSLoyaltyInterfaceVersion>'
        f'<ns2:VendorName>{VENDOR_NAME}</ns2:VendorName>'
        f'<ns2:VendorModelVersion>{VENDOR_VER}</ns2:VendorModelVersion>'
        f'<ns3:POSSequenceID>{pos_seq}</ns3:POSSequenceID>'
        f'<ns3:LoyaltySequenceID>{loy_seq}</ns3:LoyaltySequenceID>'
        f'<ns4:Result><Success/></ns4:Result>'
        f'</ns3:ResponseHeader>'
    )


# =========================
# Backend heartbeat
# =========================

def send_backend_heartbeat(pos_ip: str = None) -> None:
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "posId": POS_ID,
            "posType": POS_TYPE,
            "posIpAddress": pos_ip,
            "edgeIpAddress": HOST,
            "edgeVersion": "birdies-eps-punchcard-1.0",
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

def heartbeat_loop():
    while True:
        send_backend_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)


# =========================
# Basket parsing helpers
# =========================

def normalize_upc(upc: str) -> str:
    return (upc or "").strip()

def extract_line_items(root: ET.Element):
    """Extract items from EPS TransactionDetailGroup."""
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
            or ""
        ).strip()
        upc = normalize_upc(upc_raw)
        desc = (il.findtext("Description") or il.findtext("ItemDescription") or "").strip()

        qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
        atxt = il.findtext("SalesAmount") or il.findtext("ExtendedAmount")
        unit_price_txt = il.findtext("UnitPrice", "0")
        actual_price_txt = il.findtext("ActualSalesPrice", "0")

        try:
            qty = float(qtxt or 1.0)
        except Exception:
            qty = 1.0

        try:
            if atxt and atxt.strip():
                amount = float(atxt)
            else:
                amount = float(actual_price_txt or unit_price_txt or 0) * qty
        except Exception:
            amount = 0.0

        try:
            price = float(unit_price_txt or actual_price_txt or 0)
        except Exception:
            price = 0.0

        items.append({
            "line_no": line_no,
            "upc": upc,
            "description": desc,
            "quantity": qty,
            "amount": amount,
            "price": price,
        })
    return items


# =========================
# Punch Card API Calls
# =========================

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    """
    Evaluate punch card status WITH projected punches from current basket.
    This enables immediate reward application in the qualifying transaction.
    """
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
# Promotion Evaluation
# =========================

def evaluate_promotions(items: list) -> list:
    """Call backend to evaluate promotions."""
    if not items:
        return []
    
    log(f"🔍 Evaluating promotions for {len(items)} item(s)...")
    
    try:
        upc_groups = {}
        for item in items:
            upc = item["upc"]
            if not upc:
                # Skip non-UPC lines (like tax/fee) for promo grouping
                continue
            if upc not in upc_groups:
                upc_groups[upc] = {"upc": upc, "quantity": 0, "price": item["price"]}
            upc_groups[upc]["quantity"] += int(item["quantity"])

        if not upc_groups:
            log("  ℹ No UPC items to evaluate for promotions")
            return []

        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "items": list(upc_groups.values())
        }
        
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
# Response Builders (EPS)
# =========================

def build_online_status_response(root: ET.Element) -> str:
    """Handle GetLoyaltyOnlineStatusRequest."""
    pos_seq, loy_seq = get_req_ids(root)
    log("✓ Responding to GetLoyaltyOnlineStatus - Loyalty is ONLINE")
    return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

def build_get_rewards_response(root: ET.Element) -> str:
    """
    Handle GetRewardsRequest:
    1. Look up customer
    2. Check punch card status
    3. Evaluate promotions
    4. Calculate points redemption
    5. Apply punch card rewards if earned
    """
    global current_customer, last_points_recommended, last_promotions_applied
    global last_punch_cards, last_punches_to_record
    
    pos_seq, loy_seq = get_req_ids(root)
    
    # Extract loyalty ID or phone
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone = (root.findtext(".//PhoneNumber") or "").strip()
    
    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""
    
    # Parse basket
    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items):")
        for idx, it in enumerate(items, 1):
            log(
                f"  {idx}. Line {it['line_no']}: UPC: {it['upc']} | "
                f"Qty {it['quantity']} | Price ${it['price']:.2f} | Amount ${it['amount']:.2f}"
            )
        log("=" * 60)
    
    # Store items for punch recording later
    last_punches_to_record = items
    last_punch_cards = []
    last_promotions_applied = []
    last_points_recommended = 0.0
    
    # No customer ID - apply promos only (for now just return "ID required")
    if not loyalty_id and not phone:
        promotions = evaluate_promotions(items)
        # TODO: build AddReward entries for promotions (if you want promos without loyalty)
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
    
    # Customer lookup
    current_customer = None
    lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/pos/customer-lookup",
            json=lookup_payload,
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 404:
            log(f"⚠ Customer not found: {loyalty_id or phone}")
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
        if r.status_code != 200:
            log(f"⚠ Customer lookup failed: {r.status_code}")
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
        current_customer = r.json()
    except Exception as e:
        log(f"⚠ Customer lookup error: {e}")
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
    
    customer_id = current_customer.get("customerId")
    first_name = current_customer.get("firstName", "")
    last_name = current_customer.get("lastName", "")
    points = int(current_customer.get("pointsBalance", 0) or 0)
    
    log(f"✓ Customer found: {first_name} {last_name} ({points} pts)")
    
    # Evaluate punch card status WITH projected punches from current basket
    # HYBRID LOGIC: Reward triggers if:
    #   1. Customer already has full card (currentPunches >= punchesRequired), OR
    #   2. Customer is buying MORE than needed to complete the card (basketPunches > punchesNeeded)
    punch_eval = evaluate_punch_cards(customer_id, items)
    punch_cards_data = punch_eval.get("punchCards", [])
    
    if punch_cards_data:
        log("🎯 PUNCH CARD STATUS (hybrid reward logic):")
        for pc in punch_cards_data:
            current = pc.get('currentPunches', 0)
            basket = pc.get('punchesFromBasket', 0)
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
    
    # Build reward XML
    add_rewards = []
    
    # Apply punch card rewards if reward is triggered (including from current basket)
    for pc in last_punch_cards:
        reward_type = pc.get('rewardType', 'free_item')
        reward_value = pc.get('rewardValue', '0')
        punch_card_name = pc.get('punchCardName', 'Punch Reward')
        
        if reward_type in ('dollar_off', 'amount_off'):
            try:
                dollar_off = float(reward_value)
                add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{dollar_off:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""")
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
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{dollar_off:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name} {pct:.0f}% Off</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""")
                pc['rewardApplied'] = True
                log(f"  🎁 Applying punch reward: {pct}% off (${dollar_off:.2f})")
            except Exception as e:
                log(f"  ⚠ Error applying percent_off punch reward: {e}")
        
        elif reward_type == 'free_item':
            # FIX: Only consider real UPC item lines for FREE ITEM
            eligible_items = [
                it for it in items
                if it.get("upc") and it.get("amount", 0) > 0
            ]
            if eligible_items:
                cheapest_amount = min(it["amount"] for it in eligible_items)
                add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{cheapest_amount:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>FREE</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name} FREE ITEM</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""")
                pc['rewardApplied'] = True
                log(f"  🎁 Applying FREE ITEM punch reward: ${cheapest_amount:.2f} off (cheapest UPC item)")
            else:
                log("  ⚠ Cannot apply FREE ITEM reward - no eligible UPC items in basket")
    
    # Evaluate standard promotions (still not mapped to rewards here)
    promotions = evaluate_promotions(items)
    # TODO: Add promotion reward XML building + populate last_promotions_applied
    # last_promotions_applied = promotions  # when you start sending them
    
    # Points redemption
    subtotal = sum(it["amount"] for it in items)
    points_reward_xml = ""
    if subtotal > 0 and points >= POINTS_PER_DOLLAR:
        try:
            rr = SESSION.post(
                f"{BACKEND_URL}/api/pos/calculate-redemption",
                json={
                    "customerId": customer_id,
                    "eligibleSubtotal": subtotal,
                    "lineItems": items,
                },
                timeout=REQUEST_TIMEOUT
            )
            if rr.status_code == 200:
                data = rr.json()
                recommended = float(data.get("recommendedRedemption") or 0.0)
                if recommended > 0:
                    last_points_recommended = recommended
                    points_reward_xml = f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{REWARD_ID}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="no"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{recommended:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>{RECEIPT_SHORT}</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{RECEIPT_LONG}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>"""
        except Exception as e:
            log(f"⚠ calculate-redemption error: {e}")
    
    # Combine all rewards
    rewards = []
    if add_rewards:
        rewards.extend(add_rewards)
    if points_reward_xml:
        rewards.append(points_reward_xml)
    
    if rewards:
        reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>"
    else:
        reward_actions = "<ns3:RewardActions/>"
    
    masked = (loyalty_id[-4:].rjust(10, "*")) if loyalty_id else "****"
    
    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="yes">{first_name} {last_name}</ns3:LoyaltyIDValidFlag>
  <ns3:LoyaltyMemberID>{masked}</ns3:LoyaltyMemberID>
  <ns3:PointsBalance>{points}</ns3:PointsBalance>
  {reward_actions}
</ns3:GetRewardsResponse>"""


def build_finalize_response(root: ET.Element) -> str:
    """
    Handle FinalizeRewardsRequest:
    1. Finalize transaction with backend (points)
    2. Record punches for this transaction
    3. Redeem punch card rewards if applied
    """
    global current_customer, last_promotions_applied, last_punch_cards
    global last_punches_to_record, last_points_recommended
    
    pos_seq, loy_seq = get_req_ids(root)
    
    if not current_customer:
        log("⚠ No customer in session for finalize")
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:FinalizeRewardsResponse>"""
    
    customer_id = current_customer.get("customerId")
    transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    
    # Calculate subtotal from items
    subtotal = sum(it["amount"] for it in last_punches_to_record) if last_punches_to_record else 0.0
    
    log(f"🏁 Finalizing transaction: Customer {customer_id}, Subtotal ${subtotal:.2f}")
    
    # Finalize with backend (points calculation)
    try:
        finalize_payload = {
            "customerId": customer_id,
            "eligibleSubtotal": subtotal,
            "transactionId": transaction_id,
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": last_punches_to_record,
            "promotions": last_promotions_applied,
            "promotionDiscount": 0,
            "pointsRedeemed": int(last_points_recommended * POINTS_PER_DOLLAR) if last_points_recommended > 0 else 0,
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
    
    # Record punches
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
    
    # Redeem punch card rewards ONLY if they were actually applied to the transaction
    for pc in last_punch_cards:
        if pc.get('rewardApplied'):
            redeem_result = redeem_punch_reward(customer_id, pc.get('punchCardId'), transaction_id)
            if redeem_result.get('success'):
                log(f"  🎁 Redeemed punch reward: {pc.get('punchCardName')}")
        elif pc.get('rewardTriggered'):
            log(f"  ⚠ Reward was triggered but not applied (no discount sent): {pc.get('punchCardName')}")
    
    # Clear session state
    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []
    last_points_recommended = 0.0
    
    return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:FinalizeRewardsResponse>"""


def build_cancel_response(root: ET.Element) -> str:
    """Handle CancelTransactionRequest."""
    global current_customer, last_promotions_applied, last_punch_cards
    global last_punches_to_record, last_points_recommended
    
    pos_seq, loy_seq = get_req_ids(root)
    log("Transaction cancelled by POS")
    
    # Clear session state
    current_customer = None
    last_promotions_applied = []
    last_punch_cards = []
    last_punches_to_record = []
    last_points_recommended = 0.0
    
    return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:CancelTransactionResponse>"""


# =========================
# TCP Server
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    """Handle a connected Verifone Commander/EPS client."""
    log(f"🔌 Connection from {addr}")
    
    if EXPECTED_EPS_IP and addr[0] != EXPECTED_EPS_IP:
        log(f"⚠ Rejecting connection from {addr[0]} (expected {EXPECTED_EPS_IP})")
        conn.close()
        return
    
    try:
        while True:
            # Read EPS frame (4-byte length + XML)
            xml_bytes = recv_frame(conn)
            if not xml_bytes:
                log(f"Connection closed by {addr}")
                break
            
            # Parse XML
            try:
                root, raw = parse_xml(xml_bytes)
            except Exception as e:
                log(f"⚠ XML parse error: {e}")
                continue
            
            # Route request (namespace-stripped tag)
            tag = root.tag
            
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
            
            # Send response
            send_xml(conn, resp)
            
    except Exception as e:
        log(f"⚠ Client handler error: {e}")
    finally:
        conn.close()
        log(f"Connection closed: {addr}")


def main():
    log("=" * 60)
    log("🐦 BIRDIES LOYALTY EDGE AGENT - PUNCH CARD SUPPORT (VERIFONE)")
    log("=" * 60)
    log(f"  Store: {PDI_STORE_NUMBER}")
    log(f"  Backend: {BACKEND_URL}")
    log(f"  Listening on: {HOST}:{PORT}")
    log("=" * 60)
    
    # Start heartbeat thread
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    
    # Start TCP server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    
    log(f"✓ TCP server listening on {HOST}:{PORT}")
    log("Waiting for Verifone Commander/EPS connections...")
    
    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
