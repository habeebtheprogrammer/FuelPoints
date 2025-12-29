#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Birdies Loyalty Edge Agent - Verifone EPS (PCATS) COMBINED
---------------------------------------------------------
COMBINES:
  - Promotions (multipack + amount-off) -> mapped to EPS-friendly amountOff rewards
  - Punch cards (buy N get 1 free)      -> mapped to EPS-friendly amountOff rewards
  - Points redemption                   -> mapped to EPS-friendly amountOff rewards

EPS / PCATS REQUIREMENTS IMPLEMENTED:
  - TCP framing: 4-byte BIG-ENDIAN length prefix + UTF-8 XML payload
  - ResponseHeader overallResult="success" on success
  - RewardDiscountMethod: amountOff ONLY (EPS ignores newPrice/percentOff)
  - RewardValue safety: TOTAL combined discount <= transaction subtotal
  - Remaining subtotal tracking: promo -> punch -> points (each capped to remaining)
  - Handles additional request types with responses:
      GetLoyaltyOnlineStatusRequest, GetRewardsRequest, FinalizeRewardsRequest,
      CancelTransactionRequest, ReverseTransactionRequest, EndPeriodRequest,
      GetRewardStatusRequest, GetCustomerMessagingRequest

BUSINESS RULE (OPTION A):
  - If a line is used by a promotion discount:
      1) It does NOT earn punches
      2) It is NOT eligible for punch free-item selection
  - Enforced by tracking promo-consumed line numbers and filtering punch eligibility.

DISCOUNT ORDER & CAPPING:
  - Priority: Promos first, then Punch rewards, then Points redemption
  - Each reward type is capped to remaining budget after previous rewards
  - Prevents combined discounts from exceeding transaction total

CONCURRENCY:
  - Non-blocking singleton lock: only one active EPS session at a time.
    Additional connections are rejected immediately (avoids hanging sockets).

Version: 1.1
"""

import socket
import threading
import datetime
import struct
import uuid
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

# =========================
# Configuration
# =========================

HOST = "0.0.0.0"
PORT = 9000
EXPECTED_EPS_IP = None  # Optional: set to Commander/EPS IP to enforce allowlist

PDI_STORE_NUMBER = "1310"
POS_ID           = "24379"
POS_TYPE         = "Verifone-EPS"
BACKEND_URL      = "https://salmanloyalty.replit.app"

VENDOR_NAME = "BirdiesLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

POINTS_REWARD_ID     = "DEMO-1OFF"
RECEIPT_SHORT_POINTS = "$OFF"              # <= 8 chars
RECEIPT_LONG_POINTS  = "Loyalty Discount"  # <= 24 chars
POINTS_PER_DOLLAR    = 100

PROMO_REWARD_PREFIX = "PROMO"
PUNCH_REWARD_PREFIX = "PUNCH"

SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read)

# PCATS Namespaces (outgoing)
NS_LOY   = "http://www.pcats.org/schema/naxml/loyalty/v01"
NS_CORE  = "http://www.pcats.org/schema/core/v01"
NS_POSBO = "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
NS_DECLS = (
    f'xmlns:ns2="{NS_POSBO}" '
    f'xmlns:ns4="{NS_CORE}" '
    f'xmlns:ns3="{NS_LOY}"'
)

EPS_SINGLETON_LOCK = threading.Lock()

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
    for e in elem.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
    return elem

def receipt_short(s: str) -> str:
    return (s or "").strip()[:8]

def receipt_long(s: str) -> str:
    return (s or "").strip()[:24]

def receipt_line(s: str) -> str:
    clean = "".join(ch for ch in (s or "") if ch.isprintable())
    return clean[:40]

def cap_amount_off(value: float, subtotal: float) -> float:
    """EPS ignores discounts if RewardValue > total transaction amount."""
    if subtotal <= 0:
        return 0.0
    if value < 0:
        return 0.0
    return min(float(value), float(subtotal))

# =========================
# EPS framing: 4-byte BE length + UTF-8 XML
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
# PCATS header helpers
# =========================

def get_req_ids(root: ET.Element):
    pos_seq = root.findtext(".//POSSequenceID") or "POSSEQ"
    loy_seq = root.findtext(".//LoyaltySequenceID")
    if not loy_seq or not loy_seq.strip():
        loy_seq = "LOY-" + uuid.uuid4().hex[:12].upper()
    return pos_seq, loy_seq

def resp_header(pos_seq: str, loy_seq: str, overall: str = "success") -> str:
    result_child = "<Success/>" if overall == "success" else "<Failure/>"
    return (
        f'<ns3:ResponseHeader overallResult="{overall}">'
        f'<ns3:POSLoyaltyInterfaceVersion>{IFACE_VER}</ns3:POSLoyaltyInterfaceVersion>'
        f'<ns2:VendorName>{VENDOR_NAME}</ns2:VendorName>'
        f'<ns2:VendorModelVersion>{VENDOR_VER}</ns2:VendorModelVersion>'
        f'<ns3:POSSequenceID>{pos_seq}</ns3:POSSequenceID>'
        f'<ns3:LoyaltySequenceID>{loy_seq}</ns3:LoyaltySequenceID>'
        f'<ns4:Result>{result_child}</ns4:Result>'
        f'</ns3:ResponseHeader>'
    )

# =========================
# Session state (per connection)
# =========================

class SessionState:
    def __init__(self):
        self.current_customer = None
        self.last_points_recommended = 0.0
        self.last_promotions_applied = []
        self.last_punch_cards = []
        self.last_punches_to_record = []

    def reset(self):
        self.__init__()

# =========================
# Backend calls
# =========================

def send_backend_heartbeat(pos_ip: str) -> None:
    """Only called when GetLoyaltyOnlineStatusRequest is received."""
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "posId": POS_ID,
            "posType": POS_TYPE,
            "posIpAddress": pos_ip,
            "edgeIpAddress": HOST,
            "edgeVersion": "birdies-eps-combined-1.0",
        }
        r = SESSION.post(f"{BACKEND_URL}/api/pos/heartbeat", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            log(f"✓ Heartbeat sent to backend (Store {PDI_STORE_NUMBER})")
        else:
            log(f"⚠ Heartbeat failed: {r.status_code}")
    except Exception as e:
        log(f"⚠ Heartbeat error: {e}")

def backend_customer_lookup(loyalty_id: str, phone: str):
    lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    try:
        r = SESSION.post(f"{BACKEND_URL}/api/pos/customer-lookup", json=lookup_payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return None, "not_found"
        if r.status_code != 200:
            return None, "error"
        return r.json(), "ok"
    except Exception as e:
        log(f"⚠ Customer lookup error: {e}")
        return None, "error"

def backend_evaluate_promotions(items: list) -> list:
    if not items:
        return []
    upc_groups = {}
    for it in items:
        upc = (it.get("upc") or "").strip()
        if not upc:
            continue
        upc_groups.setdefault(upc, {"upc": upc, "quantity": 0.0, "price": float(it.get("price", 0.0) or 0.0)})
        upc_groups[upc]["quantity"] += float(it.get("quantity", 0.0) or 0.0)

    if not upc_groups:
        return []

    payload = {"pdiStoreNumber": PDI_STORE_NUMBER, "items": list(upc_groups.values())}
    try:
        r = SESSION.post(f"{BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            log(f"⚠ evaluate-promotions failed: {r.status_code}")
            return []
        return (r.json() or {}).get("promotions", []) or []
    except Exception as e:
        log(f"⚠ evaluate-promotions error: {e}")
        return []

def backend_calculate_redemption(customer_id: int, subtotal: float, items: list) -> float:
    try:
        rr = SESSION.post(
            f"{BACKEND_URL}/api/pos/calculate-redemption",
            json={"customerId": customer_id, "eligibleSubtotal": subtotal, "lineItems": items},
            timeout=REQUEST_TIMEOUT,
        )
        if rr.status_code != 200:
            return 0.0
        data = rr.json() or {}
        return float(data.get("recommendedRedemption") or 0.0)
    except Exception as e:
        log(f"⚠ calculate-redemption error: {e}")
        return 0.0

def backend_finalize_transaction(customer_id: int, subtotal: float, points_redeemed: int, txn_id: str,
                                items: list, promotions: list, promo_discount: float):
    payload = {
        "customerId": customer_id,
        "eligibleSubtotal": subtotal,
        "pointsRedeemed": points_redeemed,
        "transactionId": txn_id,
        "pdiStoreNumber": PDI_STORE_NUMBER,
        "lineItems": items,
        "promotions": promotions or [],
        "promotionDiscount": promo_discount,
    }
    try:
        r = SESSION.post(f"{BACKEND_URL}/api/pos/finalize-transaction", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            log(f"⚠ finalize-transaction failed: {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        log(f"⚠ finalize-transaction error: {e}")
        return None

def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={"customerId": customer_id, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            log(f"⚠ punch-cards/evaluate failed: {r.status_code}")
            return {"punchCards": []}
        return r.json() or {"punchCards": []}
    except Exception as e:
        log(f"⚠ punch-cards/evaluate error: {e}")
        return {"punchCards": []}

def record_punches(customer_id: int, line_items: list, txn_id: str) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/record-purchase",
            json={"customerId": customer_id, "lineItems": line_items,
                  "pdiStoreNumber": PDI_STORE_NUMBER, "transactionId": txn_id},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            log(f"⚠ punch-cards/record-purchase failed: {r.status_code}")
            return {}
        return r.json() or {}
    except Exception as e:
        log(f"⚠ punch-cards/record-purchase error: {e}")
        return {}

def redeem_punch_reward(customer_id: int, punch_card_id: int, txn_id: str) -> dict:
    try:
        r = SESSION.post(
            f"{BACKEND_URL}/api/punch-cards/redeem",
            json={"customerId": customer_id, "punchCardId": punch_card_id,
                  "pdiStoreNumber": PDI_STORE_NUMBER, "transactionId": txn_id},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            log(f"⚠ punch-cards/redeem failed: {r.status_code}")
            return {}
        return r.json() or {}
    except Exception as e:
        log(f"⚠ punch-cards/redeem error: {e}")
        return {}

# =========================
# Basket parsing
# =========================

def normalize_upc(upc: str) -> str:
    return (upc or "").strip()

def extract_line_items(root: ET.Element) -> list:
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
        )
        upc = normalize_upc(upc_raw)

        desc = (il.findtext("Description") or il.findtext("ItemDescription") or "").strip()

        qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
        atxt = il.findtext("SalesAmount") or il.findtext("ExtendedAmount")
        unit_price_txt    = il.findtext("UnitPrice", "0")
        actual_price_txt  = il.findtext("ActualSalesPrice", "0")
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

        unit_price    = _f(unit_price_txt)
        actual_price  = _f(actual_price_txt)
        regular_price = _f(regular_price_txt)

        if atxt and atxt.strip():
            amount = _f(atxt)
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
        })
    return items

def get_current_unit_price(item: dict) -> float:
    for key in ("unit_price", "actual_price", "regular_price"):
        v = float(item.get(key, 0) or 0)
        if v > 0:
            return v
    return float(item.get("price", 0) or 0)

def unit_amount(item: dict) -> float:
    qty = float(item.get("quantity", 0) or 0)
    amt = float(item.get("amount", 0) or 0)
    if qty > 0:
        return amt / qty
    return float(item.get("price", 0) or 0)

# =========================
# Promotion mapping (EPS-friendly)
# =========================

def build_promotion_rewards_xml_eps(items: list, promotions: list, remaining_subtotal: float):
    """
    EPS safest: ticket-level amountOff (RewardTargetLineNumber = 0).
    Also returns promo_line_numbers used to "consume" promo units for Option A gating.
    Returns: (rewards_xml_list, applied_promos, promo_line_numbers, total_promo_discount)
    """
    if not promotions or remaining_subtotal <= 0:
        return [], [], set(), 0.0

    upc_to_lines = {}
    for it in items:
        upc_to_lines.setdefault(it["upc"], []).append(it)

    best_by_upc = {}
    for promo in promotions:
        upc = (promo.get("upc") or "").strip()
        if not upc:
            continue

        disc_type = promo.get("discountType", "multipack")
        qty       = int(promo.get("quantity", 1) or 1)
        bundles   = int(promo.get("bundleCount", 0) or 0)
        if bundles <= 0:
            continue

        per_unit_new = None
        if disc_type == "multipack":
            promo_total = float(promo.get("promoPrice", 0.0) or 0.0)
            total_units = max(qty * bundles, 1)
            per_unit_new = promo_total / total_units

        candidate = {"promo": promo, "disc_type": disc_type, "qty": qty, "bundles": bundles, "per_unit_new": per_unit_new}
        if upc not in best_by_upc:
            best_by_upc[upc] = candidate
        else:
            prev = best_by_upc[upc]
            if per_unit_new is not None and (prev["per_unit_new"] is None or per_unit_new < prev["per_unit_new"]):
                best_by_upc[upc] = candidate

    rewards = []
    applied = []
    promo_line_numbers = set()
    total_promo_discount = 0.0
    budget = float(remaining_subtotal)

    for upc, info in best_by_upc.items():
        if budget <= 0:
            break

        promo = info["promo"]
        disc_type = info["disc_type"]
        qty = info["qty"]
        bundles = info["bundles"]

        total_units_needed = qty * bundles
        remaining = total_units_needed
        matching = upc_to_lines.get(upc, [])
        if not matching:
            continue

        raw_discount = 0.0
        lines_used = set()
        for item in matching:
            if remaining <= 0:
                break
            take_qty = int(min(float(item.get("quantity", 0) or 0), remaining))
            if take_qty <= 0:
                continue

            current_price = get_current_unit_price(item)
            discount_per_unit = 0.0

            if disc_type == "multipack":
                per_unit_new = float(info["per_unit_new"] or 0.0)
                if current_price > per_unit_new:
                    discount_per_unit = current_price - per_unit_new
            else:
                api_discount = float(promo.get("discount", 0.0) or 0.0)
                per_unit_disc = api_discount / max(total_units_needed, 1)
                discount_per_unit = min(per_unit_disc, current_price)

            line_discount = max(0.0, discount_per_unit * take_qty)
            if line_discount > 0:
                lines_used.add(int(item.get("line_no", 0) or 0))
            raw_discount += line_discount
            remaining -= take_qty

        capped_discount = cap_amount_off(raw_discount, budget)
        if capped_discount <= 0:
            continue

        promo_line_numbers.update(lines_used)
        budget -= capped_discount
        total_promo_discount += capped_discount

        reward_id = f"{PROMO_REWARD_PREFIX}-{promo.get('promotionId', upc)}"
        promo_name = promo.get("name") or promo.get("itemGroupName") or "Promo"

        rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{capped_discount:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>{receipt_short("PROMO")}</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{receipt_long(promo_name)}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())

        p = dict(promo)
        p["discount"] = capped_discount
        p["name"] = receipt_long(promo_name)
        applied.append(p)

    return rewards, applied, promo_line_numbers, total_promo_discount

# =========================
# Punch reward mapping (EPS-friendly)
# =========================

def build_punch_rewards_xml_eps(triggered_cards: list, eligible_items: list, remaining_subtotal: float):
    """
    EPS safest: ticket-level amountOff.
    "Free item" = amountOff equal to ONE unit of the cheapest eligible line.
    Returns: (rewards_xml_list, total_punch_discount)
    """
    if not triggered_cards or not eligible_items or remaining_subtotal <= 0:
        return [], 0.0

    rewards = []
    available = list(eligible_items)
    total_punch_discount = 0.0
    budget = float(remaining_subtotal)

    for pc in triggered_cards:
        if not available or budget <= 0:
            break

        cheapest = min(available, key=lambda it: unit_amount(it))
        raw_free_amt = unit_amount(cheapest)
        capped_free_amt = cap_amount_off(raw_free_amt, budget)
        
        if capped_free_amt <= 0:
            available = [it for it in available if int(it.get("line_no", 0) or 0) != int(cheapest.get("line_no", 0) or 0)]
            continue

        name = pc.get("punchCardName", "Punch Reward")

        rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_PREFIX}-{pc.get('punchCardId')}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{capped_free_amt:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>{receipt_short("FREE")}</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{receipt_long(f"{name} FREE")}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())

        pc["rewardApplied"] = True
        pc["rewardAmount"] = capped_free_amt
        budget -= capped_free_amt
        total_punch_discount += capped_free_amt
        
        line_no = int(cheapest.get("line_no", 0) or 0)
        available = [it for it in available if int(it.get("line_no", 0) or 0) != line_no]

    return rewards, total_punch_discount

# =========================
# Response builders
# =========================

def build_online_status_response(root: ET.Element, pos_ip: str) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    send_backend_heartbeat(pos_ip)
    return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

def build_get_rewards_response(root: ET.Element, st: SessionState) -> str:
    pos_seq, loy_seq = get_req_ids(root)

    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone      = (root.findtext(".//PhoneNumber") or "").strip()
    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""

    items = extract_line_items(root)
    subtotal = sum(float(it.get("amount", 0) or 0) for it in items)

    if items:
        log(f"Transaction: {len(items)} items, subtotal ${subtotal:.2f}")
        for idx, it in enumerate(items, 1):
            log(f"  {idx}. Line {it['line_no']}: {it['upc']} - ${it['amount']:.2f}")

    st.last_points_recommended = 0.0
    st.last_promotions_applied = []
    st.last_punch_cards = []
    st.last_punches_to_record = []

    # Guest path: promotions only (no punch, no points)
    if not loyalty_id and not phone:
        promotions = backend_evaluate_promotions(items)
        promo_rewards, applied_promos, _promo_lines, promo_disc = build_promotion_rewards_xml_eps(items, promotions, subtotal)
        st.last_promotions_applied = applied_promos

        if promo_disc > 0:
            log(f"Guest promo discount: ${promo_disc:.2f}")

        reward_actions = "<ns3:RewardActions>\n" + "\n".join(promo_rewards) + "\n</ns3:RewardActions>" if promo_rewards else "<ns3:RewardActions/>"
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:LoyaltyIDValidFlag value="yes">Guest</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

    cust, status = backend_customer_lookup(loyalty_id, phone)
    if status == "not_found":
        log("Customer not found")
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
    if status != "ok":
        log("Customer lookup error")
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="timeout")}
  <ns3:LoyaltyIDValidFlag value="no">System Error</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""

    st.current_customer = cust
    customer_id = int(cust.get("customerId") or 0)
    points = int(cust.get("pointsBalance", 0) or 0)
    first_name = cust.get("firstName", "")
    last_name = cust.get("lastName", "")
    log(f"✓ Customer: {first_name} {last_name} ({points} pts)")

    display_id = loyalty_id or phone or ""
    masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    # =====================================================
    # REMAINING SUBTOTAL TRACKING
    # Order: Promos -> Punch -> Points
    # Each reward is capped to remaining budget
    # =====================================================
    remaining_subtotal = float(subtotal)
    log(f"Starting discount budget: ${remaining_subtotal:.2f}")

    # 1) PROMOS (amountOff) + track promo lines for Option A
    promotions = backend_evaluate_promotions(items)
    promo_rewards, applied_promos, promo_line_numbers, promo_discount = build_promotion_rewards_xml_eps(items, promotions, remaining_subtotal)
    st.last_promotions_applied = applied_promos

    if promo_discount > 0:
        remaining_subtotal -= promo_discount
        log(f"Promo discount: ${promo_discount:.2f} | Remaining budget: ${remaining_subtotal:.2f}")

    if promo_line_numbers:
        log(f"OPTION A: Lines with promo (excluded from punch): {promo_line_numbers}")

    # 2) OPTION A gating for punch (exclude promo lines)
    punch_eligible_items = [it for it in items if int(it.get("line_no", 0) or 0) not in promo_line_numbers]
    st.last_punches_to_record = punch_eligible_items

    if punch_eligible_items:
        log(f"Punch-eligible items: {len(punch_eligible_items)} of {len(items)}")

    # 3) PUNCH evaluate + reward
    punch_rewards = []
    punch_discount = 0.0
    if customer_id and punch_eligible_items and remaining_subtotal > 0:
        pe = evaluate_punch_cards(customer_id, punch_eligible_items)
        cards = pe.get("punchCards", []) or []
        triggered = []

        if cards:
            log("PUNCH CARD STATUS:")
            for pc in cards:
                current = int(pc.get("currentPunches", 0) or 0)
                basket  = int(pc.get("punchesFromBasket", 0) or 0)
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

                log(status_line)

        st.last_punch_cards = triggered

        reward_eligible = [
            it for it in punch_eligible_items
            if (it.get("upc") or "").strip() and float(it.get("amount", 0) or 0) > 0 and float(it.get("price", 0) or 0) > 0
        ]
        if triggered and reward_eligible:
            punch_rewards, punch_discount = build_punch_rewards_xml_eps(triggered, reward_eligible, remaining_subtotal)
            if punch_discount > 0:
                remaining_subtotal -= punch_discount
                log(f"Punch discount: ${punch_discount:.2f} | Remaining budget: ${remaining_subtotal:.2f}")

    # 4) POINTS redemption (amountOff) - capped to remaining budget
    points_reward_xml = ""
    if remaining_subtotal > 0 and points >= POINTS_PER_DOLLAR and customer_id:
        recommended = backend_calculate_redemption(customer_id, subtotal, items)
        recommended = cap_amount_off(recommended, remaining_subtotal)
        if recommended > 0:
            pts_to_use = int(round(recommended * POINTS_PER_DOLLAR))
            log(f"Points redemption: ${recommended:.2f} ({pts_to_use} pts) | Final remaining: ${remaining_subtotal - recommended:.2f}")
            st.last_points_recommended = float(recommended)
            points_reward_xml = f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{POINTS_REWARD_ID}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{recommended:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>{receipt_short(RECEIPT_SHORT_POINTS)}</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{receipt_long(RECEIPT_LONG_POINTS)}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip()

    # Combine rewards (order: promo -> punch -> points)
    rewards = []
    rewards.extend(promo_rewards or [])
    rewards.extend(punch_rewards or [])
    if points_reward_xml:
        rewards.append(points_reward_xml)

    total_discount = promo_discount + punch_discount + float(st.last_points_recommended or 0.0)
    if rewards:
        log(f"Sending {len(rewards)} reward(s) to EPS | Total discount: ${total_discount:.2f}")

    reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>" if rewards else "<ns3:RewardActions/>"

    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:LoyaltyIDValidFlag value="yes">{masked}</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

def build_finalize_response(root: ET.Element, st: SessionState) -> str:
    pos_seq, loy_seq = get_req_ids(root)

    raw_txn_id = (root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or "").strip()
    safe_txn_id = raw_txn_id if raw_txn_id else f"TXN-{uuid.uuid4().hex[:8].upper()}"

    items = extract_line_items(root)
    subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
    log(f"Finalize: subtotal ${subtotal:.2f}")

    receipt_lines = []

    if not st.current_customer:
        receipt_lines.append("Thank you for shopping at Birdies!")
        rec_xml = "\n".join(f"      <ns3:ReceiptLine>{receipt_line(line)}</ns3:ReceiptLine>" for line in receipt_lines)
        st.reset()
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
{rec_xml}
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:FinalizeRewardsResponse>"""

    customer_id = int(st.current_customer.get("customerId") or 0)

    applied_dollars = cap_amount_off(float(st.last_points_recommended or 0.0), subtotal)
    points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR)) if applied_dollars > 0 else 0

    promo_discount = sum(float(p.get("discount", 0) or 0) for p in (st.last_promotions_applied or []))

    data = backend_finalize_transaction(
        customer_id=customer_id,
        subtotal=subtotal,
        points_redeemed=points_redeemed,
        txn_id=safe_txn_id,
        items=items,
        promotions=st.last_promotions_applied,
        promo_discount=promo_discount,
    )

    overall = "success"
    if data is None:
        overall = "timeout"
        receipt_lines.append("Loyalty finalize error")
    else:
        pts_earned = int(data.get("pointsEarned", 0) or 0)
        new_bal = int(data.get("newBalance", 0) or 0)

        log(f"✓ Finalized: Redeemed {points_redeemed} pts, Earned {pts_earned} pts, Balance {new_bal}")

        if applied_dollars > 0:
            receipt_lines.append(f"Points Redeemed: {points_redeemed} (${applied_dollars:.2f})")
        receipt_lines.append(f"Points Earned: {pts_earned}")
        receipt_lines.append(f"New Balance: {new_bal}")

    # Record punches (Option A already enforced)
    if st.last_punches_to_record:
        pr = record_punches(customer_id, st.last_punches_to_record, safe_txn_id) or {}
        punches_recorded = pr.get("punchesRecorded", []) or []
        if punches_recorded:
            receipt_lines.append("Punches Recorded:")
            for p in punches_recorded:
                line = f"  {p.get('punchCardName','Punch')}: +{p.get('punchesAdded',0)} ({p.get('currentPunches',0)}/{p.get('punchesRequired',0)})"
                receipt_lines.append(line)

    # Redeem punch rewards
    for pc in (st.last_punch_cards or []):
        if pc.get("rewardApplied"):
            rr = redeem_punch_reward(customer_id, int(pc.get("punchCardId") or 0), safe_txn_id) or {}
            if rr.get("redeemed") or rr.get("success"):
                receipt_lines.append(f"Punch Reward Redeemed: {pc.get('punchCardName','Punch')}")

    if not receipt_lines:
        receipt_lines.append("Thank you for shopping at Birdies!")

    rec_xml = "\n".join(f"      <ns3:ReceiptLine>{receipt_line(line)}</ns3:ReceiptLine>" for line in receipt_lines)

    st.reset()

    return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall=overall)}
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
{rec_xml}
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:FinalizeRewardsResponse>"""

def build_cancel_txn_response(root: ET.Element, st: SessionState) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    st.reset()
    log("Transaction cancelled")
    return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
</ns3:CancelTransactionResponse>"""

def build_reverse_txn_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    log("Transaction reversal acknowledged")
    return f"""<ns3:ReverseTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
</ns3:ReverseTransactionResponse>"""

def build_end_period_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    log("End period acknowledged")
    return f"""<ns3:EndPeriodResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns4:Result><Success/></ns4:Result>
</ns3:EndPeriodResponse>"""

def build_customer_msg_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""<ns3:GetCustomerMessagingResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:CustomerMessageData>
    <ns3:DisplayData>
      <ns3:DisplayCommand device="POS-Cashier" sequence="WhenReceived" duration="3">
        <ns3:DisplayLine>Welcome to Birdies Loyalty!</ns3:DisplayLine>
      </ns3:DisplayCommand>
    </ns3:DisplayData>
  </ns3:CustomerMessageData>
</ns3:GetCustomerMessagingResponse>"""

def build_reward_status_response(root: ET.Element) -> str:
    """
    GetRewardStatus: balance inquiry
    Returns customer points balance and punch card progress.
    """
    pos_seq, loy_seq = get_req_ids(root)
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()

    cust, status = backend_customer_lookup(loyalty_id, phone="")
    if status != "ok" or not cust:
        return f"""<ns3:GetRewardStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:LoyaltyIDValidFlag value="no">Invalid</ns3:LoyaltyIDValidFlag>
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
      <ns3:ReceiptLine>{receipt_line("Loyalty ID not found")}</ns3:ReceiptLine>
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:GetRewardStatusResponse>"""

    customer_id = int(cust.get("customerId") or 0)
    points = int(cust.get("pointsBalance", 0) or 0)
    name = f"{cust.get('firstName','')} {cust.get('lastName','')}".strip() or "Customer"

    punch_status = evaluate_punch_cards(customer_id, []) or {}
    cards = punch_status.get("punchCards", []) or []

    lines = [f"{name}", f"Points: {points}"]
    for pc in cards[:5]:
        cur = int(pc.get("currentPunches", 0) or 0)
        req = int(pc.get("punchesRequired", 10) or 10)
        nm = pc.get("punchCardName", "Punch") or "Punch"
        lines.append(f"{nm}: {cur}/{req}")

    rec_xml = "\n".join(f"      <ns3:ReceiptLine>{receipt_line(line)}</ns3:ReceiptLine>" for line in lines)

    return f"""<ns3:GetRewardStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="success")}
  <ns3:LoyaltyIDValidFlag value="yes">OK</ns3:LoyaltyIDValidFlag>
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
{rec_xml}
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:GetRewardStatusResponse>"""

# =========================
# Connection handler / server
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    log(f"EPS connected from {peer}")

    if EXPECTED_EPS_IP and addr[0] != EXPECTED_EPS_IP:
        log(f"⚠ Rejecting unexpected EPS IP: {addr[0]}")
        try:
            conn.close()
        except Exception:
            pass
        return

    # Non-blocking singleton lock (reject if already active session)
    if not EPS_SINGLETON_LOCK.acquire(blocking=False):
        log(f"⚠ Another EPS session active; rejecting {peer}")
        try:
            conn.close()
        except Exception:
            pass
        return

    st = SessionState()

    try:
        conn.settimeout(180)
        while True:
            frame = recv_frame(conn)
            if not frame:
                log(f"EPS disconnected: {peer}")
                break

            try:
                root, _raw = parse_xml(frame)
            except Exception as e:
                log(f"XML parse error from {peer}: {e}")
                break

            tag = (root.tag or "").strip()
            log(f"Request: {tag}")

            if tag == "GetLoyaltyOnlineStatusRequest":
                resp = build_online_status_response(root, addr[0])

            elif tag == "GetRewardsRequest":
                resp = build_get_rewards_response(root, st)

            elif tag == "FinalizeRewardsRequest":
                resp = build_finalize_response(root, st)

            elif tag == "CancelTransactionRequest":
                resp = build_cancel_txn_response(root, st)

            elif tag == "ReverseTransactionRequest":
                resp = build_reverse_txn_response(root)

            elif tag == "EndPeriodRequest":
                resp = build_end_period_response(root)

            elif tag == "GetCustomerMessagingRequest":
                resp = build_customer_msg_response(root)

            elif tag == "GetRewardStatusRequest":
                resp = build_reward_status_response(root)

            else:
                log(f"Unhandled request type: {tag}")
                pos_seq, loy_seq = get_req_ids(root)
                resp = f"""<ns3:UnknownResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, overall="failure")}
</ns3:UnknownResponse>"""

            send_xml(conn, resp)

    except socket.timeout:
        log(f"EPS timeout: {peer}")
    except ConnectionResetError:
        log(f"EPS connection reset: {peer}")
    except Exception as e:
        log(f"EPS error from {peer}: {e}")
    finally:
        st.reset()
        EPS_SINGLETON_LOCK.release()
        try:
            conn.close()
        except Exception:
            pass
        log(f"EPS session ended: {peer}")

def main():
    log("=" * 60)
    log("Birdies Loyalty Edge Agent - Verifone EPS (PCATS) COMBINED")
    log("=" * 60)
    log(f"Store: {PDI_STORE_NUMBER} | POS ID: {POS_ID}")
    log(f"Backend: {BACKEND_URL}")
    log(f"Listening on {HOST}:{PORT}")
    log("Features: Promotions + Punch Cards + Points (OPTION A)")
    log("EPS: 4-byte BE framing, amountOff only, ticket-level rewards")
    log("=" * 60)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(64)

    log("Server started, waiting for EPS connections...")

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        log("Shutting down...")
    finally:
        server.close()

if __name__ == "__main__":
    main()
