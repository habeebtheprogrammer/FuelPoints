#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PUNCH CARD SUPPORT (Verifone EPS) [FIXED v2]
------------------------------------------------------------------------

This rewrite includes the same *style* of fixes we applied for Passport, but tailored to EPS:

FIX A) Session stability across repeated GetRewards/Finalize calls
- EPS can call GetRewards multiple times for the same transaction.
- We keep a per-transaction session keyed by LoyaltySequenceID (generated if missing).
- We reuse the session customer instead of re-looking up every time.
- We clear the session only on FinalizeRewardsRequest (after processing) or CancelTransactionRequest.
- (If EPS ever sends masked loyalty IDs, we refuse lookup on masked values and require an existing session.)

FIX B) Prevent punch "double count" when a punch reward makes an item free (Python-only; no JS changes)
- Your backend /api/punch-cards/record-purchase:
    * counts punches from quantity
    * skips punch counting only if amount <= 0
- EPS "free item" in this script is implemented as a basket-level amountOff, so item lines still look "paid".
  That causes the classic bug:
    start 4/5, buy 2, one becomes free -> backend records +2, then redeem -5 -> ends at 1/5 (wrong)
- We fix it by:
    * tracking when we applied a "free_item" punch reward
    * choosing ONE eligible line (cheapest eligible item) to treat as the "free unit"
    * on Finalize, BEFORE calling /record-purchase, we split that line into:
          - paid portion (qty reduced, amount>0)
          - free portion (qty=1, amount=0.0)
      so the backend naturally skips counting a punch for the free unit.
- Works even if the POS discount is basket-level, because the punch recording payload is corrected.

Notes:
- This script keeps your existing "hybrid trigger logic" for rewards.
- If you want perfect trigger behavior (4/5 + buy 1 should trigger), switch to using pc["rewardReady"] from /evaluate.
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
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =========================
# Configuration - EDIT THESE
# =========================

HOST = "0.0.0.0"
PORT = 9000
EXPECTED_EPS_IP = None  # e.g. "10.5.50.1" to restrict

PDI_STORE_NUMBER = "0300"
POS_ID = "24379"
POS_TYPE = "Verifone-EPS"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15

VENDOR_NAME = "BirdiesLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

REWARD_ID         = "DEMO-1OFF"
PUNCH_REWARD_ID   = "PUNCH-REWARD"
RECEIPT_SHORT     = "$OFF"
RECEIPT_LONG      = "Loyalty Discount"
POINTS_PER_DOLLAR = 100

SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read) seconds


# =========================
# PCATS Namespaces
# =========================

NS_LOY   = "http://www.pcats.org/schema/naxml/loyalty/v01"
NS_CORE  = "http://www.pcats.org/schema/core/v01"
NS_POSBO = "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"

NS_DECLS = (
    f'xmlns:ns2="{NS_POSBO}" '
    f'xmlns:ns4="{NS_CORE}" '
    f'xmlns:ns3="{NS_LOY}"'
)


# =========================
# Session store keyed by LoyaltySequenceID
# =========================

@dataclass
class FreePunchAdjustment:
    punch_card_id: int
    punch_card_name: str
    line_no: int
    upc: str
    free_units: int = 1

@dataclass
class TxnSession:
    loyalty_sequence_id: str
    customer: dict
    last_seen_at: float = field(default_factory=time.time)
    last_points_recommended: float = 0.0
    promotions_applied: List[dict] = field(default_factory=list)
    # One entry per free_item reward applied
    free_punch_adjustments: List[FreePunchAdjustment] = field(default_factory=list)

SESSIONS: Dict[str, TxnSession] = {}
SESSION_TTL_SECONDS = 10 * 60  # cleanup safety


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

def cleanup_sessions() -> None:
    now = time.time()
    expired = [k for k, s in SESSIONS.items() if (now - s.last_seen_at) > SESSION_TTL_SECONDS]
    for k in expired:
        del SESSIONS[k]
    if expired:
        log(f"[Session] Cleaned up {len(expired)} expired session(s)")

def is_masked(val: str) -> bool:
    return bool(val) and ("*" in val)

def normalize_upc(upc: str) -> str:
    return (upc or "").strip()

def get_pos_transaction_id(root: ET.Element) -> str:
    """
    EPS payloads vary; try common locations.
    """
    return (
        (root.findtext(".//POSTransactionID") or "").strip()
        or (root.findtext(".//TransactionID") or "").strip()
        or (root.findtext(".//TransactionHeader/TransactionID") or "").strip()
    )


# =========================
# EPS framing: 4-byte big-endian length + UTF-8 XML
# =========================

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
            "edgeVersion": "birdies-eps-punchcard-2.0",
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

def extract_line_items(root: ET.Element):
    """
    Extract items from EPS TransactionDetailGroup.
    We keep line_no so we can "attribute" a free unit to a specific line for punch correction.
    """
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

        def to_f(x):
            try:
                return float(x or 0)
            except Exception:
                return 0.0

        try:
            qty = float(qtxt or 1.0)
        except Exception:
            qty = 1.0

        try:
            if atxt and atxt.strip():
                amount = float(atxt)
            else:
                amount = to_f(actual_price_txt or unit_price_txt) * qty
        except Exception:
            amount = 0.0

        unit_price = to_f(unit_price_txt)
        actual_price = to_f(actual_price_txt)
        price = unit_price or actual_price or 0.0

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

def backend_customer_lookup(loyalty_id: str, phone: str) -> Optional[dict]:
    payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    r = SESSION.post(f"{BACKEND_URL}/api/pos/customer-lookup", json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return r.json()
    if r.status_code == 404:
        return None
    raise RuntimeError(f"customer-lookup failed: {r.status_code}")

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={"customerId": customer_id, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        log(f"⚠ Punch evaluate failed: {r.status_code}")
        return {"punchCards": [], "rewardsReady": []}
    except Exception as e:
        log(f"⚠ Punch evaluate error: {e}")
        return {"punchCards": [], "rewardsReady": []}

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
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
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
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        log(f"⚠ Punch redeem failed: {r.status_code}")
        return {}
    except Exception as e:
        log(f"⚠ Punch redeem error: {e}")
        return {}


# =========================
# Promotions (unchanged)
# =========================

def evaluate_promotions(items: list) -> list:
    if not items:
        return []

    try:
        upc_groups = {}
        for item in items:
            upc = item.get("upc", "")
            if not upc:
                continue
            if upc not in upc_groups:
                upc_groups[upc] = {"upc": upc, "quantity": 0, "price": item.get("price", 0)}
            upc_groups[upc]["quantity"] += int(item.get("quantity", 1))

        if not upc_groups:
            return []

        payload = {"pdiStoreNumber": PDI_STORE_NUMBER, "items": list(upc_groups.values())}
        r = SESSION.post(f"{BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("promotions", [])
        return []
    except Exception:
        return []


# =========================
# Punch miscount fix (Python-only)
# =========================

def choose_free_item_line(items: list) -> Optional[dict]:
    """
    Choose which line to treat as the free unit (cheapest eligible UPC line).
    """
    eligible = [it for it in items if it.get("upc") and float(it.get("amount", 0) or 0) > 0 and float(it.get("price", 0) or 0) > 0]
    if not eligible:
        return None
    return min(eligible, key=lambda it: float(it.get("price", 0) or 0))

def adjust_items_for_record_purchase(items: list, adjustments: List[FreePunchAdjustment]) -> list:
    """
    Apply free-unit adjustments by splitting targeted lines into paid + free pseudo-lines.
    Free pseudo-line has amount=0 so backend skips punch for that unit.
    """
    free_map: Dict[int, int] = {}
    for adj in adjustments:
        free_map[adj.line_no] = free_map.get(adj.line_no, 0) + int(adj.free_units or 1)

    adjusted = []
    for it in items:
        ln = int(it.get("line_no", 0) or 0)
        upc = (it.get("upc") or "").strip()

        try:
            qty_int = int(float(it.get("quantity", 1) or 1))
        except Exception:
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
            paid["amount"] = round(unit_price * paid_units, 2) if unit_price > 0 else round(max(0.01, orig_amt * (paid_units / max(1, qty_int))), 2)
            adjusted.append(paid)

        if free_units > 0:
            free = dict(it)
            free["quantity"] = float(free_units)
            free["amount"] = 0.0
            adjusted.append(free)

    return adjusted


# =========================
# Response Builders (EPS)
# =========================

def build_online_status_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

def build_get_rewards_response(root: ET.Element) -> str:
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    txn_id = get_pos_transaction_id(root)

    # Loyalty ID / phone
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone = (root.findtext(".//PhoneNumber") or "").strip()

    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10 and not is_masked(loyalty_id):
        phone = digits
        loyalty_id = ""

    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 EPS ITEMS ({len(items)}) [txn={txn_id} loy={loy_seq}]")
        for i, it in enumerate(items, 1):
            log(f"  {i}. Line {it['line_no']} UPC {it['upc']} Qty {it['quantity']} Amt ${it['amount']:.2f}")
        log("=" * 60)

    # Session reuse
    sess = SESSIONS.get(loy_seq)
    if sess:
        sess.last_seen_at = time.time()

    # Masked follow-up safety (rare in EPS, but safe)
    if is_masked(loyalty_id):
        if not sess:
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
        current_customer = sess.customer
    else:
        if sess:
            current_customer = sess.customer
        else:
            if not loyalty_id and not phone:
                return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

            try:
                current_customer = backend_customer_lookup(loyalty_id, phone)
            except Exception as e:
                log(f"⚠ Customer lookup error: {e}")
                return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

            if not current_customer:
                return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

            sess = TxnSession(loyalty_sequence_id=loy_seq, customer=current_customer)
            SESSIONS[loy_seq] = sess

    sess.last_seen_at = time.time()
    customer_id = int(sess.customer.get("customerId") or 0)
    first_name = sess.customer.get("firstName", "")
    last_name = sess.customer.get("lastName", "")
    points = int(sess.customer.get("pointsBalance", 0) or 0)

    # reset per-request caches
    sess.last_points_recommended = 0.0
    sess.promotions_applied = []
    sess.free_punch_adjustments = []

    # Punch evaluation
    punch_eval = evaluate_punch_cards(customer_id, items) if (customer_id and items) else {"punchCards": []}
    punch_cards_data = punch_eval.get("punchCards", []) or []

    # Build reward XML
    add_rewards: List[str] = []

    # Apply punch card rewards
    for pc in punch_cards_data:
        reward_type = pc.get("rewardType", "free_item")
        reward_value = pc.get("rewardValue", "0")
        punch_card_name = pc.get("punchCardName", "Punch Reward")

        current = int(pc.get("currentPunches", 0) or 0)
        basket  = int(pc.get("punchesFromBasket", 0) or 0)
        required = int(pc.get("punchesRequired", 10) or 10)
        punches_needed = max(0, required - current)

        already_full = current >= required
        buying_extra = basket > punches_needed
        should_trigger = already_full or buying_extra

        if not should_trigger:
            continue

        # Dollar/percent off (unchanged)
        if reward_type in ("dollar_off", "amount_off"):
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
    </ns3:AddReward>""".rstrip())
            except Exception:
                pass

        elif reward_type == "percent_off":
            try:
                pct = float(reward_value)
                subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
                dollar_off = subtotal * (pct / 100.0)
                add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{dollar_off:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name} {pct:.0f}% Off</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())
            except Exception:
                pass

        elif reward_type == "free_item":
            # EPS "free item" is basket-level discount in this implementation.
            # We also record a FREE UNIT adjustment so punches don't double count on finalize.
            free_line = choose_free_item_line(items)
            if not free_line:
                continue

            cheapest_amount = float(free_line.get("price", 0) or 0.0)  # use per-unit price for amountOff
            if cheapest_amount <= 0:
                continue

            add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{cheapest_amount:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>FREE</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name} FREE ITEM</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())

            sess.free_punch_adjustments.append(
                FreePunchAdjustment(
                    punch_card_id=int(pc.get("punchCardId") or 0),
                    punch_card_name=punch_card_name,
                    line_no=int(free_line.get("line_no", 0) or 0),
                    upc=free_line.get("upc", ""),
                    free_units=1,
                )
            )

    # Promotions (still not mapped to AddReward here)
    sess.promotions_applied = evaluate_promotions(items)

    # Points redemption
    subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
    points_reward_xml = ""
    if subtotal > 0 and points >= POINTS_PER_DOLLAR:
        try:
            rr = SESSION.post(
                f"{BACKEND_URL}/api/pos/calculate-redemption",
                json={"customerId": customer_id, "eligibleSubtotal": subtotal, "lineItems": items},
                timeout=REQUEST_TIMEOUT
            )
            if rr.status_code == 200:
                data = rr.json()
                recommended = float(data.get("recommendedRedemption") or 0.0)
                if recommended > 0:
                    sess.last_points_recommended = recommended
                    points_reward_xml = f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{REWARD_ID}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="no"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{recommended:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>{RECEIPT_SHORT}</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{RECEIPT_LONG}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip()
        except Exception:
            pass

    rewards: List[str] = []
    rewards.extend(add_rewards)
    if points_reward_xml:
        rewards.append(points_reward_xml)

    if rewards:
        reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>"
    else:
        reward_actions = "<ns3:RewardActions/>"

    masked = (phone[-4:].rjust(10, "*")) if phone else "****"
    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="yes">{first_name} {last_name}</ns3:LoyaltyIDValidFlag>
  <ns3:LoyaltyMemberID>{masked}</ns3:LoyaltyMemberID>
  <ns3:PointsBalance>{points}</ns3:PointsBalance>
  {reward_actions}
</ns3:GetRewardsResponse>"""


def build_finalize_response(root: ET.Element) -> str:
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    txn_id = get_pos_transaction_id(root) or f"TXN-{uuid.uuid4().hex[:8].upper()}"

    sess = SESSIONS.get(loy_seq)
    if not sess:
        log("⚠ No session for finalize; skipping backend calls")
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:FinalizeRewardsResponse>"""

    sess.last_seen_at = time.time()

    # Re-parse final items from Finalize request (more accurate than using cached basket)
    final_items = extract_line_items(root)
    subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)

    customer_id = int(sess.customer.get("customerId") or 0)
    points_redeemed = int(round(sess.last_points_recommended * POINTS_PER_DOLLAR)) if sess.last_points_recommended > 0 else 0

    log(f"🏁 EPS Finalize: customer={customer_id} subtotal=${subtotal:.2f} txn={txn_id} loy={loy_seq}")

    # Finalize points with backend
    try:
        finalize_payload = {
            "customerId": customer_id,
            "eligibleSubtotal": subtotal,
            "transactionId": txn_id,
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": final_items,
            "promotions": sess.promotions_applied or [],
            "promotionDiscount": 0,
            "pointsRedeemed": points_redeemed,
        }
        r = SESSION.post(f"{BACKEND_URL}/api/pos/finalize-transaction", json=finalize_payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            result = r.json()
            log(f"  ✓ Points: earned {result.get('pointsEarned', 0)}, balance {result.get('newBalance', 0)}")
        else:
            log(f"  ⚠ finalize-transaction failed: {r.status_code}")
    except Exception as e:
        log(f"  ⚠ finalize-transaction error: {e}")

    # Punch miscount fix: adjust record-purchase payload if we applied free-item rewards
    record_items = final_items
    if sess.free_punch_adjustments:
        # Apply adjustments only if the target line still exists in finalize
        existing_lines = {int(it.get("line_no", 0) or 0) for it in final_items}
        applicable = [a for a in sess.free_punch_adjustments if a.line_no in existing_lines]
        if applicable:
            log("✅ Applying punch FREE-UNIT adjustments before /record-purchase:")
            for a in applicable:
                log(f"   - treat 1 unit FREE on line {a.line_no} (UPC {a.upc}) for {a.punch_card_name}")
            record_items = adjust_items_for_record_purchase(final_items, applicable)

    # Record punches (using adjusted payload)
    punch_result = record_punches(customer_id, record_items, txn_id)
    punches_recorded = punch_result.get("punchesRecorded", [])
    if punches_recorded:
        log("  🎯 PUNCHES RECORDED:")
        for p in punches_recorded:
            log(f"     • {p.get('punchCardName')}: +{p.get('punchesAdded')} → {p.get('currentPunches')}/{p.get('punchesRequired')}")

    # Redeem punch card rewards that were applied (we redeem once per punch_card_id in the adjustments list)
    redeemed = set()
    for a in sess.free_punch_adjustments:
        if a.punch_card_id and a.punch_card_id not in redeemed:
            redeem_result = redeem_punch_reward(customer_id, a.punch_card_id, txn_id)
            if redeem_result.get("success"):
                log(f"  🎁 Redeemed punch reward: {a.punch_card_name} (id={a.punch_card_id})")
            redeemed.add(a.punch_card_id)

    # Clear session for this loyalty sequence id
    del SESSIONS[loy_seq]

    return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:FinalizeRewardsResponse>"""


def build_cancel_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    if loy_seq in SESSIONS:
        del SESSIONS[loy_seq]
        log(f"[Session] CancelTransaction: removed session {loy_seq}")
    return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:CancelTransactionResponse>"""


# =========================
# TCP Server
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    log(f"🔌 Connection from {addr}")

    if EXPECTED_EPS_IP and addr[0] != EXPECTED_EPS_IP:
        log(f"⚠ Rejecting connection from {addr[0]} (expected {EXPECTED_EPS_IP})")
        conn.close()
        return

    # send heartbeat with real pos ip
    send_backend_heartbeat(addr[0])

    try:
        while True:
            xml_bytes = recv_frame(conn)
            if not xml_bytes:
                log(f"Connection closed by {addr}")
                break

            try:
                root, _raw = parse_xml(xml_bytes)
            except Exception as e:
                log(f"⚠ XML parse error: {e}")
                continue

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

            send_xml(conn, resp)

    except Exception as e:
        log(f"⚠ Client handler error: {e}")
    finally:
        conn.close()
        log(f"Connection closed: {addr}")


def main():
    log("=" * 60)
    log("🐦 BIRDIES LOYALTY EDGE AGENT - PUNCH CARD SUPPORT (VERIFONE) [FIXED v2]")
    log("=" * 60)
    log(f"  Store: {PDI_STORE_NUMBER}")
    log(f"  Backend: {BACKEND_URL}")
    log(f"  Listening on: {HOST}:{PORT}")
    log("=" * 60)

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    log("✓ Heartbeat thread started")

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
