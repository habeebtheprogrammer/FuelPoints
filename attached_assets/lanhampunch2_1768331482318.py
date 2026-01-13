#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Birdies Loyalty Edge Agent - PUNCH CARD SUPPORT (Verifone EPS) [TEST BUILD v3]
-----------------------------------------------------------------------------

Fixes included:
1) Correct punch reward timing:
   - Do NOT apply free reward when a basket merely completes the card (e.g., 2/3 + buy 1).
   - Apply free reward only if:
        a) card was already full BEFORE this basket (currentPunches >= required), OR
        b) customer is buying MORE than needed this basket (punchesFromBasket > punchesNeeded)
   This prevents "free at 2/3" and ensures free happens on the next purchase after reaching 3/3,
   unless buying extra in the same transaction.

2) Detect "free reward applied" in Finalize:
   - VIPER may represent loyalty reward as Promotion/LoyaltyRewardID (not TenderInfo).
   - We detect BOTH TenderInfo/LoyaltyRewardID and Promotion/LoyaltyRewardID.

3) Points conversion updated for: $1 off per $100 spent
   - Based on observed earning (~5 pts per $1), use: 500 points = $1.
   - Set POINTS_PER_DOLLAR = 500.

4) Best-effort no-tax free item:
   - Target real ItemLine (skip MerchandiseCodeLine and PSC=950).
   - Use line-targeted amountOff with RewardLimit quantity=1.
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
# Configuration
# =========================

HOST = "0.0.0.0"
PORT = 9000
EXPECTED_EPS_IP = None  # set to commander IP if you want to restrict

PDI_STORE_NUMBER = "0300"
POS_ID = "24379"
POS_TYPE = "Verifone-EPS"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15

VENDOR_NAME = "BirdiesLoyalty"
VENDOR_VER  = "1.0"

# Points config:
# To achieve ~$1 off per $100 spent given ~5 pts per $1 earned, use 500 pts = $1.
REWARD_ID         = "DEMO-1OFF"
RECEIPT_SHORT     = "$OFF"
RECEIPT_LONG      = "Loyalty Discount"
POINTS_PER_DOLLAR = 500  # 500 points = $1.00

PUNCH_REWARD_ID = "PUNCH-REWARD"

SESSION_HTTP = requests.Session()
REQUEST_TIMEOUT = (3, 5)

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
# Session store
# =========================

@dataclass
class FreeUnit:
    punch_card_id: int
    punch_card_name: str
    line_no: int
    upc: str
    free_units: int = 1
    reward_id: str = ""

@dataclass
class TxnSession:
    loy_seq: str
    iface_ver: str
    customer: dict
    last_seen_at: float = field(default_factory=time.time)
    last_points_recommended: float = 0.0
    free_units: List[FreeUnit] = field(default_factory=list)

SESSIONS: Dict[str, TxnSession] = {}
SESSION_TTL_SECONDS = 10 * 60

# =========================
# Logging / XML utils
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
    for e in elem.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
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

# =========================
# EPS framing
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

# =========================
# Request parsing helpers
# =========================

def get_req_ids(root: ET.Element):
    pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
    loy_seq = root.findtext(".//LoyaltySequenceID")
    if not loy_seq or not loy_seq.strip():
        loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
    return pos_seq, loy_seq

def get_iface_ver(root: ET.Element) -> str:
    return (root.findtext(".//POSLoyaltyInterfaceVersion") or "1.0").strip()

def get_pos_transaction_id(root: ET.Element) -> str:
    return (
        (root.findtext(".//POSTransactionID") or "").strip()
        or (root.findtext(".//TransactionID") or "").strip()
    )

# =========================
# Response header builders
# =========================

def resp_header(pos_seq: str, loy_seq: str, iface_ver: str) -> str:
    return (
        f'<ns3:ResponseHeader overallResult="success">'
        f'<ns3:POSLoyaltyInterfaceVersion>{iface_ver}</ns3:POSLoyaltyInterfaceVersion>'
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
            "edgeVersion": "birdies-eps-punchcard-test-3.0",
        }
        r = SESSION_HTTP.post(
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

def extract_line_items(root: ET.Element) -> List[dict]:
    items: List[dict] = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        status = (tline.get("status") or "").strip().lower()
        if status and status != "normal":
            continue

        item_line = tline.find("./ItemLine")
        merch_line = None if item_line is not None else tline.find("./MerchandiseCodeLine")
        il = item_line if item_line is not None else merch_line
        if il is None:
            continue

        is_item_line = item_line is not None
        try:
            line_no = int(tline.findtext("./LineNumber", "0"))
        except Exception:
            line_no = 0

        psc = (il.findtext(".//PaymentSystemsProductCode") or "").strip()

        upc_raw = ""
        if is_item_line:
            upc_raw = (
                il.findtext("./ItemCode/POSCode")
                or il.findtext(".//POSCode")
                or il.findtext(".//UPC")
                or ""
            )
        upc = normalize_upc(upc_raw)

        desc = (il.findtext("Description") or il.findtext("ItemDescription") or "").strip()

        qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
        atxt = il.findtext("SalesAmount") or il.findtext("ExtendedAmount")
        unit_price_txt = il.findtext("UnitPrice", "0")
        actual_price_txt = il.findtext("ActualSalesPrice", "0")
        regular_price_txt = il.findtext("RegularSellPrice", "0")

        def to_f(x) -> float:
            try:
                return float(x or 0)
            except Exception:
                return 0.0

        try:
            qty = float(qtxt or 1.0)
        except Exception:
            qty = 1.0

        unit_price = to_f(unit_price_txt)
        actual_price = to_f(actual_price_txt)
        regular_price = to_f(regular_price_txt)

        if atxt and str(atxt).strip():
            amount = to_f(atxt)
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

def get_unit_price(it: dict) -> float:
    for k in ("unit_price", "actual_price", "regular_price", "price"):
        v = float(it.get(k, 0) or 0)
        if v > 0:
            return v
    return 0.0

def choose_cheapest_eligible_line(items: list) -> Optional[dict]:
    eligible = []
    for it in items:
        if not it.get("is_item_line"):
            continue
        if (it.get("psc") or "").strip() == "950":
            continue
        if not (it.get("upc") or "").strip():
            continue
        if float(it.get("amount", 0) or 0) <= 0:
            continue
        if get_unit_price(it) <= 0:
            continue
        eligible.append(it)
    if not eligible:
        return None
    return min(eligible, key=lambda it: get_unit_price(it))

# =========================
# Backend API calls
# =========================

def backend_customer_lookup(loyalty_id: str, phone: str) -> Optional[dict]:
    payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    r = SESSION_HTTP.post(f"{BACKEND_URL}/api/pos/customer-lookup", json=payload, timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return r.json()
    if r.status_code == 404:
        return None
    raise RuntimeError(f"customer-lookup failed: {r.status_code}")

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={"customerId": customer_id, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
        return {"punchCards": [], "rewardsReady": []}
    except Exception:
        return {"punchCards": [], "rewardsReady": []}

def record_punches(customer_id: int, line_items: list, transaction_id: str) -> dict:
    try:
        r = SESSION_HTTP.post(
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
        return {}
    except Exception:
        return {}

def redeem_punch_reward(customer_id: int, punch_card_id: int, transaction_id: str) -> dict:
    try:
        r = SESSION_HTTP.post(
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
        return {}
    except Exception:
        return {}

def calculate_redemption(customer_id: int, eligible_subtotal: float, line_items: list) -> float:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/pos/calculate-redemption",
            json={"customerId": customer_id, "eligibleSubtotal": eligible_subtotal, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return 0.0
        data = r.json()
        return float(data.get("recommendedRedemption") or 0.0)
    except Exception:
        return 0.0

# =========================
# Detect applied reward in Finalize (TenderInfo OR Promotion)
# =========================

def finalize_has_reward(root: ET.Element, reward_id: str) -> bool:
    if not reward_id:
        return False

    # TenderInfo / LoyaltyRewardID
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        ti = tline.find("./TenderInfo")
        if ti is not None:
            lrid = (ti.findtext("LoyaltyRewardID") or "").strip()
            if lrid == reward_id:
                return True

    # Promotion / LoyaltyRewardID (VIPER often uses this for free item)
    for promo in root.findall(".//Promotion"):
        lrid = (promo.findtext("LoyaltyRewardID") or "").strip()
        if lrid == reward_id:
            return True

    return False

# =========================
# Punch-count correction: split paid/free in /record-purchase
# =========================

def adjust_items_for_record_purchase(final_items: list, free_units: List[FreeUnit]) -> list:
    free_map: Dict[int, int] = {}
    for fu in free_units:
        free_map[fu.line_no] = free_map.get(fu.line_no, 0) + int(fu.free_units or 1)

    adjusted = []
    for it in final_items:
        ln = int(it.get("line_no", 0) or 0)

        if not it.get("is_item_line"):
            adjusted.append(it)
            continue

        upc = (it.get("upc") or "").strip()
        if not upc:
            adjusted.append(it)
            continue

        try:
            qty_int = int(float(it.get("quantity", 1) or 1))
        except Exception:
            qty_int = 1

        if qty_int <= 0:
            adjusted.append(it)
            continue

        free_qty = int(free_map.get(ln, 0) or 0)
        if free_qty <= 0:
            adjusted.append(it)
            continue

        free_qty = max(0, min(free_qty, qty_int))
        paid_qty = qty_int - free_qty

        unit_price = get_unit_price(it)
        orig_amt = float(it.get("amount", 0) or 0)

        if paid_qty > 0:
            paid = dict(it)
            paid["quantity"] = float(paid_qty)
            paid["amount"] = round(unit_price * paid_qty, 2) if unit_price > 0 else round(max(0.01, orig_amt * (paid_qty / max(1, qty_int))), 2)
            adjusted.append(paid)

        if free_qty > 0:
            free = dict(it)
            free["quantity"] = float(free_qty)
            free["amount"] = 0.0
            adjusted.append(free)

    return adjusted

# =========================
# EPS Response Builders
# =========================

def build_online_status_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

def build_end_period_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    return f"""<ns3:EndPeriodResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns4:Result><Success/></ns4:Result>
</ns3:EndPeriodResponse>"""

def build_cancel_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    if loy_seq in SESSIONS:
        del SESSIONS[loy_seq]
        log(f"[Session] CancelTransaction removed session {loy_seq}")
    return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:CancelTransactionResponse>"""

def build_get_rewards_response(root: ET.Element) -> str:
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    txn_id = get_pos_transaction_id(root)

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
            upc_disp = it.get("upc") or (it.get("psc") if not it.get("is_item_line") else "")
            log(f"  {i}. Line {it['line_no']} UPC {upc_disp} qty {it['quantity']} amt ${float(it['amount']):.2f} itemLine={it.get('is_item_line')} psc={it.get('psc')}")
        log("=" * 60)

    sess = SESSIONS.get(loy_seq)
    if sess:
        sess.last_seen_at = time.time()

    if is_masked(loyalty_id):
        if not sess:
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
        customer = sess.customer
    else:
        if sess:
            customer = sess.customer
        else:
            if not loyalty_id and not phone:
                return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer ID Required</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

            try:
                customer = backend_customer_lookup(loyalty_id, phone)
            except Exception as e:
                log(f"⚠ customer-lookup error: {e}")
                return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

            if not customer:
                return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

            sess = TxnSession(loy_seq=loy_seq, iface_ver=iface_ver, customer=customer)
            SESSIONS[loy_seq] = sess

    sess.last_seen_at = time.time()
    sess.iface_ver = iface_ver
    sess.last_points_recommended = 0.0
    sess.free_units = []

    customer_id = int(customer.get("customerId") or 0)
    first_name = customer.get("firstName", "")
    last_name = customer.get("lastName", "")
    points = int(customer.get("pointsBalance", 0) or 0)

    display = phone or loyalty_id or ""
    member_mask = (display[-4:].rjust(10, "*")) if display else "****"

    punch_eval = evaluate_punch_cards(customer_id, items) if (customer_id and items) else {"punchCards": []}
    punch_cards = punch_eval.get("punchCards", []) or []

    add_rewards: List[str] = []

    # ---- PUNCH REWARD TIMING FIX ----
    for pc in punch_cards:
        if not bool(pc.get("rewardReady")):
            continue

        current = int(pc.get("currentPunches", 0) or 0)
        basket  = int(pc.get("punchesFromBasket", 0) or 0)
        required = int(pc.get("punchesRequired", 0) or 0)

        punches_needed = max(0, required - current)

        already_full_before = (current >= required and required > 0)
        buying_extra = (basket > punches_needed)  # strictly more than needed
        should_apply_free_now = already_full_before or buying_extra

        punch_card_id = int(pc.get("punchCardId") or 0)
        punch_name = (pc.get("punchCardName") or "Punch Card").strip()
        reward_type = (pc.get("rewardType") or "free_item").strip()
        reward_value = pc.get("rewardValue")

        if reward_type not in ("free_item", "", None) and reward_type != "free_item":
            # keep other reward types unchanged
            pass

        if not should_apply_free_now and reward_type == "free_item":
            log(f"ℹ Punch rewardReady but NOT applying yet (complete-only case): {punch_name} current={current}/{required} basket={basket}")
            continue

        if reward_type in ("dollar_off", "amount_off"):
            try:
                amt = float(reward_value or 0)
            except Exception:
                amt = 0.0
            if amt <= 0:
                continue

            add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{punch_card_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_name}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())
            continue

        if reward_type == "percent_off":
            try:
                pct = float(reward_value or 0)
            except Exception:
                pct = 0.0
            subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
            amt = max(0.0, subtotal * (pct / 100.0))
            if amt <= 0:
                continue

            add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{punch_card_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_name} {pct:.0f}%</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())
            continue

        # free_item: best-effort no-tax by targeting coffee ItemLine (not psc=950)
        chosen = choose_cheapest_eligible_line(items)
        if not chosen:
            continue

        line_no = int(chosen.get("line_no", 0) or 0)
        unit_price = get_unit_price(chosen)
        if line_no <= 0 or unit_price <= 0:
            continue

        reward_id = f"{PUNCH_REWARD_ID}-{punch_card_id}"

        add_rewards.append(f"""
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

        sess.free_units.append(
            FreeUnit(
                punch_card_id=punch_card_id,
                punch_card_name=punch_name,
                line_no=line_no,
                upc=(chosen.get("upc") or "").strip(),
                free_units=1,
                reward_id=reward_id,
            )
        )

    # Points redemption (ticket-level amountOff)
    subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
    points_reward_xml = ""
    if subtotal > 0 and points >= POINTS_PER_DOLLAR:
        recommended = calculate_redemption(customer_id, subtotal, items)
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

    rewards = list(add_rewards)
    if points_reward_xml:
        rewards.append(points_reward_xml)

    reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>" if rewards else "<ns3:RewardActions/>"

    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="yes">{first_name} {last_name}</ns3:LoyaltyIDValidFlag>
  <ns3:LoyaltyMemberID>{member_mask}</ns3:LoyaltyMemberID>
  <ns3:PointsBalance>{points}</ns3:PointsBalance>
  {reward_actions}
</ns3:GetRewardsResponse>"""

def build_finalize_response(root: ET.Element) -> str:
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    txn_id = get_pos_transaction_id(root) or f"TXN-{uuid.uuid4().hex[:8].upper()}"

    sess = SESSIONS.get(loy_seq)
    if not sess:
        log("⚠ No session for finalize; responding success but skipping backend calls")
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

    sess.last_seen_at = time.time()

    final_items = extract_line_items(root)
    eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)

    customer = sess.customer
    customer_id = int(customer.get("customerId") or 0)

    points_redeemed = int(round(float(sess.last_points_recommended or 0) * POINTS_PER_DOLLAR))

    log(f"🏁 EPS Finalize: customer={customer_id} subtotal=${eligible_subtotal:.2f} txn={txn_id} loy={loy_seq}")

    # finalize points in backend
    try:
        finalize_payload = {
            "customerId": customer_id,
            "eligibleSubtotal": eligible_subtotal,
            "transactionId": txn_id,
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": final_items,
            "promotions": [],
            "promotionDiscount": 0,
            "pointsRedeemed": points_redeemed,
        }
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/pos/finalize-transaction",
            json=finalize_payload,
            timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            result = r.json()
            log(f"  ✓ Points: earned {result.get('pointsEarned', 0)}, balance {result.get('newBalance', 0)}")
        else:
            log(f"  ⚠ finalize-transaction failed: {r.status_code}")
    except Exception as e:
        log(f"  ⚠ finalize-transaction error: {e}")

    # Only treat units as free if POS actually applied reward in Finalize (TenderInfo OR Promotion)
    applied_free_units: List[FreeUnit] = []
    for fu in sess.free_units:
        if finalize_has_reward(root, fu.reward_id):
            applied_free_units.append(fu)
        else:
            log(f"⚠ Free reward not detected in Finalize; will NOT redeem or punch-adjust: {fu.reward_id} ({fu.punch_card_name})")

    record_items = final_items
    if applied_free_units:
        existing_lines = {int(it.get("line_no", 0) or 0) for it in final_items}
        applicable = [fu for fu in applied_free_units if fu.line_no in existing_lines]
        if applicable:
            log("✅ Applying FREE-UNIT punch adjustments before /record-purchase:")
            for fu in applicable:
                log(f"   - line {fu.line_no} UPC {fu.upc} (1 free unit) for {fu.punch_card_name}")
            record_items = adjust_items_for_record_purchase(final_items, applicable)

    punch_result = record_punches(customer_id, record_items, txn_id)
    punches_recorded = punch_result.get("punchesRecorded", []) if isinstance(punch_result, dict) else []
    if punches_recorded:
        log("  🎯 PUNCHES RECORDED:")
        for p in punches_recorded:
            log(f"     • {p.get('punchCardName')}: +{p.get('punchesAdded')} → {p.get('currentPunches')}/{p.get('punchesRequired')}")

    # Redeem ONLY for rewards that POS applied
    redeemed = set()
    for fu in applied_free_units:
        if fu.punch_card_id and fu.punch_card_id not in redeemed:
            redeem_result = redeem_punch_reward(customer_id, fu.punch_card_id, txn_id)
            if isinstance(redeem_result, dict) and redeem_result.get("success"):
                log(f"  🎁 Redeemed punch reward: {fu.punch_card_name} (id={fu.punch_card_id})")
            redeemed.add(fu.punch_card_id)

    if loy_seq in SESSIONS:
        del SESSIONS[loy_seq]

    return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

# =========================
# TCP Server
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    log(f"🔌 Connection from {peer}")

    if EXPECTED_EPS_IP and addr[0] != EXPECTED_EPS_IP:
        log(f"⚠ Rejecting connection from {addr[0]} (expected {EXPECTED_EPS_IP})")
        conn.close()
        return

    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except Exception:
        pass

    send_backend_heartbeat(addr[0])

    try:
        while True:
            xml_bytes = recv_frame(conn)
            if not xml_bytes:
                log(f"Connection closed by {peer}")
                break

            try:
                root, _raw = parse_xml(xml_bytes)
            except Exception as e:
                log(f"⚠ XML parse error: {e}")
                continue

            tag = (root.tag or "").strip()

            if tag == "GetLoyaltyOnlineStatusRequest":
                send_xml(conn, build_online_status_response(root))
            elif tag == "GetRewardsRequest":
                send_xml(conn, build_get_rewards_response(root))
            elif tag == "FinalizeRewardsRequest":
                send_xml(conn, build_finalize_response(root))
            elif tag == "CancelTransactionRequest":
                send_xml(conn, build_cancel_response(root))
            elif tag == "EndPeriodRequest":
                send_xml(conn, build_end_period_response(root))
            else:
                log(f"⚠ Unknown request type: {tag}")

    except Exception as e:
        log(f"⚠ Client handler error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        log(f"Connection closed: {peer}")

def main():
    log("=" * 60)
    log("🐦 BIRDIES LOYALTY EDGE AGENT - PUNCH CARD SUPPORT (VERIFONE EPS) [TEST BUILD v3]")
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
    server.listen(20)

    log(f"✓ TCP server listening on {HOST}:{PORT}")
    log("Waiting for Verifone Commander/EPS connections...")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()
