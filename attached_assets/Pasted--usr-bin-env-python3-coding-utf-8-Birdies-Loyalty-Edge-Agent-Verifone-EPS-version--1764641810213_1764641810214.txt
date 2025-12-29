#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Birdies Loyalty Edge Agent (Verifone EPS version)
-------------------------------------------------
• Speaks the Verifone EPS Loyalty Host interface (PCATS XML over TCP)
• Keeps your backend contracts identical to the Passport agent:
    - /api/pos/heartbeat
    - /api/pos/customer-lookup
    - /api/pos/evaluate-promotions
    - /api/pos/calculate-redemption
    - /api/pos/finalize-transaction
• Converts multipack "new price" style offers into EPS-compatible item-level
  amount-off rewards and sends points redemption as a ticket-level amount-off.

Important EPS specifics implemented here:
- Message transport is persistent TCP with a 4-byte big-endian length prefix.
- Only 'amountOff' is accepted for AddReward at item/transaction level.
- ResponseHeader must include overallResult="success".
- Heartbeat is GetLoyaltyOnlineStatus when idle (Commander will also send it).
Docs: Verifone EPS Loyalty Host Implement Guide v1.0.2. See comments for refs.
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

# Network – you asked for IP "0000" → bind-all is "0.0.0.0"; port 9000.
HOST = "0.0.0.0"          # Bind to all interfaces so Commander can connect
PORT = 9000               # EPS FEP table should target this port on this PC
EXPECTED_EPS_IP = None    # Optional: set to Commander IP to enforce allowlist

# Store / backend identity
PDI_STORE_NUMBER = "1310"
POS_ID           = "24379"
POS_TYPE         = "Verifone-EPS"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15  # seconds between our own heartbeats to backend

# PCATS / Vendor naming in responses
VENDOR_NAME = "BirdiesLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

# Points config (unchanged)
REWARD_ID          = "DEMO-1OFF"
RECEIPT_SHORT      = "$OFF"
RECEIPT_LONG       = "Loyalty Discount"
POINTS_PER_DOLLAR  = 100   # 100 pts = $1.00

# HTTP session & timeout
SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read) seconds

# Live session state (per-connection)
current_customer = None
last_points_recommended = 0.0  # stash the last points-based $ we told EPS

# Namespaces (PCATS)
NS_LOY   = "http://www.pcats.org/schema/naxml/loyalty/v01"
NS_CORE  = "http://www.pcats.org/schema/core/v01"
NS_POSBO = "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"

# Aliases used in outgoing XML
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
    """Commander/EPS uses namespaced tags; strip to simplify XPath."""
    for e in elem.iter():
        if isinstance(e.tag, str) and '}' in e.tag:
            e.tag = e.tag.split('}', 1)[1]
    return elem

# EPS framing: 4-byte big-endian length + UTF-8 XML payload.
# (EPS uses PCATS XML over standard non-encrypted TCP with persistent socket.)
# Ref: Guide sections "LHFEP / Communication" and heartbeat notes. 
# (length header itself isn't spelled out in text, but this is the standard framing used by EPS.)
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
    # EPS requires overallResult in ResponseHeader. :contentReference[oaicite:6]{index=6}
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
            "edgeVersion": "birdies-eps-amountoff-1.0",
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
# Basket parsing & promo helpers
# =========================

def normalize_upc(upc: str) -> str:
    # Preserve exactly as sent by EPS/POS. (Matches your backend strategy.)
    return (upc or "").strip()

def extract_line_items(root: ET.Element):
    """
    Pulls 'ItemLine' and 'MerchandiseCodeLine' with status="normal".
    Works with both POSBO and Loyalty schema tag variations.
    """
    items = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        status = (tline.get("status") or "").strip().lower()
        if status and status != "normal":
            continue
        il = tline.find("./ItemLine") or tline.find("./MerchandiseCodeLine")
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

        def _f(x):
            try:
                return float(x or 0)
            except Exception:
                return 0.0

        unit_price    = _f(unit_price_txt)
        actual_price  = _f(actual_price_txt)
        regular_price = _f(regular_price_txt)

        # amount used to compute subtotal; prefer ActualSalesPrice * qty if SalesAmount empty
        amount = _f(atxt) if (atxt and atxt.strip()) else (actual_price * qty)

        # effective current per-unit price
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
    return 0.0

def evaluate_promotions(items: list) -> list:
    """
    Call unchanged backend /api/pos/evaluate-promotions.
    Accepts ANY length UPC, preserved as-is.
    """
    if not items:
        return []

    # Group items by UPC for backend (it expects combined qty)
    upc_groups = {}
    for it in items:
        upc_groups.setdefault(it["upc"], {"upc": it["upc"], "quantity": 0.0, "price": it["price"]})
        upc_groups[it["upc"]]["quantity"] += it["quantity"]

    payload = {
        "pdiStoreNumber": PDI_STORE_NUMBER,
        "items": list(upc_groups.values()),
    }

    try:
        log(f"📤 Calling promotion API: {BACKEND_URL}/api/pos/evaluate-promotions")
        log(f"   Payload: {payload}")
        r = SESSION.post(f"{BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=REQUEST_TIMEOUT)
        log(f"📥 API Response: Status {r.status_code}")
        if r.status_code != 200:
            log(f"   Body: {r.text}")
            return []
        result = r.json()
        log(f"   Response data: {result}")
        promos = result.get("promotions", [])
        return promos or []
    except Exception as e:
        log(f"⚠ Evaluate promotions error: {e}")
        return []

def build_promotion_rewards_xml_eps(items: list, promotions: list) -> list:
    """
    Convert backend promotions into EPS AddReward blocks using 'amountOff' only.
    For multipack (N-for-$X), compute per-unit discount vs current unit price and
    emit item-level amount off on targeted lines. For '$X off when you buy N',
    split the discount evenly per unit on targeted lines.

    EPS notes:
      - Only 'amountOff' is accepted; 'newPrice'/'percentOff' are ignored. :contentReference[oaicite:7]{index=7}
      - RewardLimit is supported; we’ll not rely on it and instead compute exact
        per-line amountOff to avoid ambiguity. :contentReference[oaicite:8]{index=8}
    """
    if not promotions:
        return []

    # Map UPC to the list of line items (to target specific lines)
    upc_to_lines = {}
    for it in items:
        upc_to_lines.setdefault(it["upc"], []).append(it)

    # Choose the best promo per UPC by lowest implied per-unit final price
    best_by_upc = {}  # upc -> dict(promo=..., per_unit_new_price=..., total_units=...)
    for promo in promotions:
        upc = (promo.get("upc") or "").strip()
        if not upc:
            continue

        disc_type = promo.get("discountType", "multipack")
        qty       = int(promo.get("quantity", 1) or 1)
        bundles   = int(promo.get("bundleCount", 0) or 0)  # how many bundles apply in this basket

        if bundles <= 0:
            continue

        if disc_type == "multipack":
            # Example: 2 for $5 → promoPrice is total for all bundles; find per-unit final price
            promo_price_total = float(promo.get("promoPrice", 0.0) or 0.0)
            total_units = max(qty * bundles, 1)
            per_unit_new_price = promo_price_total / total_units
        else:
            # Example: $1.80 off when buy 2. Discount is total across the bundle(s); spread evenly
            total_discount = float(promo.get("discount", 0.0) or 0.0)
            total_units = max(qty * bundles, 1)
            # We'll compute amountOff directly later; per-unit new price requires current price.
            per_unit_new_price = None  # marker

        if upc not in best_by_upc:
            best_by_upc[upc] = {"promo": promo, "per_unit_new_price": per_unit_new_price, "total_units": total_units}
        else:
            existing = best_by_upc[upc]
            # pick promo with lower per-unit final price; if None (amountOff type), treat as "compute later" with current price
            if per_unit_new_price is not None and (
                existing["per_unit_new_price"] is None or per_unit_new_price < existing["per_unit_new_price"]
            ):
                best_by_upc[upc] = {"promo": promo, "per_unit_new_price": per_unit_new_price, "total_units": total_units}

    add_rewards = []
    for upc, data in best_by_upc.items():
        promo = data["promo"]
        disc_type = promo.get("discountType", "multipack")
        qty       = int(promo.get("quantity", 1) or 1)
        bundles   = int(promo.get("bundleCount", 0) or 0)
        total_units_needed = qty * bundles
        remaining_units = total_units_needed

        matching = upc_to_lines.get(upc, [])
        if not matching:
            continue

        reward_id = f"PROMO-{promo.get('promotionId', upc)}"
        group_name = (promo.get("itemGroupName") or "Promo")[:24]

        for item in matching:
            if remaining_units <= 0:
                break

            take_qty = int(min(item["quantity"], remaining_units))
            if take_qty <= 0:
                continue

            current_price = get_current_unit_price(item)
            discount_value_per_unit = 0.0

            if disc_type == "multipack":
                # per-unit new price given → amountOff = current - new, floored at ≥ 0
                per_unit_new_price = float(data["per_unit_new_price"] or 0.0)
                if current_price > per_unit_new_price:
                    discount_value_per_unit = current_price - per_unit_new_price
                else:
                    discount_value_per_unit = 0.0
            else:
                # amountOff for bundle(s) → split evenly across units
                total_discount = float(promo.get("discount", 0.0) or 0.0)
                per_unit_discount = total_discount / max(total_units_needed, 1)
                # Best-price floor: never reduce below zero
                discount_value_per_unit = min(per_unit_discount, current_price)

            total_amount_off_for_line = max(0.0, discount_value_per_unit * take_qty)
            if total_amount_off_for_line <= 0:
                remaining_units -= take_qty
                continue

            # EPS item-level reward: amountOff, targeted to line number; InstantRewardFlag yes to avoid prompts. :contentReference[oaicite:9]{index=9}
            add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>{item["line_no"]}</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{total_amount_off_for_line:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PROMO</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{group_name}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())

            remaining_units -= take_qty

    return add_rewards

# =========================
# Response builders (EPS)
# =========================

def build_online_status_response(root: ET.Element) -> str:
    # EPS uses this for heartbeat/online check. :contentReference[oaicite:10]{index=10}
    pos_seq, loy_seq = get_req_ids(root)
    return f"""<ns3:GetLoyaltyOnlineStatusResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:PromptForLoyaltyFlag value="yes"/>
</ns3:GetLoyaltyOnlineStatusResponse>"""

def build_get_rewards_response(root: ET.Element) -> str:
    global current_customer, last_points_recommended
    pos_seq, loy_seq = get_req_ids(root)

    # Extract loyalty id / phone
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone      = (root.findtext(".//PhoneNumber") or "").strip()
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
            log(f"  {idx}. Line {it['line_no']}: UPC: {it['upc']} | Qty {it['quantity']} | Price ${it['price']:.2f} | Amount ${it['amount']:.2f}")
        log("=" * 60)
    else:
        log("🛒 No discountable items in basket (yet)")

    # If no ID, still apply promos without points
    if not loyalty_id and not phone:
        promotions = evaluate_promotions(items)
        promo_rewards = build_promotion_rewards_xml_eps(items, promotions)
        rewards_block = "<ns3:RewardActions>\n" + "\n".join(promo_rewards) + "\n</ns3:RewardActions>" if promo_rewards else "<ns3:RewardActions/>"
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="yes">Guest</ns3:LoyaltyIDValidFlag>
  {rewards_block}
</ns3:GetRewardsResponse>"""

    # 1) Customer lookup (unchanged backend)
    current_customer = None
    lookup_payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
    try:
        r = SESSION.post(f"{BACKEND_URL}/api/pos/customer-lookup", json=lookup_payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
  <ns3:RewardActions/>
</ns3:GetRewardsResponse>"""
        if r.status_code != 200:
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

    display_id = loyalty_id or phone or ""
    masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    # 2) Promotions (unchanged backend → EPS amountOff)
    promotions = evaluate_promotions(items)
    promo_rewards = build_promotion_rewards_xml_eps(items, promotions)

    # 3) Points redemption (ticket-level amountOff; EPS will apply as discount)
    subtotal = sum(it["amount"] for it in items)
    points = int(current_customer.get("pointsBalance", 0) or 0)
    customer_id = current_customer.get("customerId")

    last_points_recommended = 0.0
    points_reward_xml = ""
    if subtotal > 0 and points >= POINTS_PER_DOLLAR:
        try:
            redemption_req = {
                "customerId": customer_id,
                "eligibleSubtotal": subtotal,
                "lineItems": items,
            }
            rr = SESSION.post(f"{BACKEND_URL}/api/pos/calculate-redemption", json=redemption_req, timeout=REQUEST_TIMEOUT)
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
    </ns3:AddReward>""".rstrip()
            else:
                log(f"⚠ calculate-redemption failed: {rr.status_code}")
        except Exception as e:
            log(f"⚠ calculate-redemption error: {e}")

    # 4) Combine rewards
    rewards = []
    if promo_rewards:
        rewards.extend(promo_rewards)
    if points_reward_xml:
        rewards.append(points_reward_xml)

    reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>" if rewards else "<ns3:RewardActions/>"

    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:LoyaltyIDValidFlag value="yes">{masked}</ns3:LoyaltyIDValidFlag>
  {reward_actions}
</ns3:GetRewardsResponse>"""

def build_finalize_response(root: ET.Element) -> str:
    """
    EPS finalize: we won’t see a special loyalty tender like Passport.
    We use the last_points_recommended we sent (ticket-level AddReward) as the redeemed amount.
    We still show receipt lines back to the POS. (EPS will print these.) :contentReference[oaicite:11]{index=11}
    """
    global current_customer, last_points_recommended
    pos_seq, loy_seq = get_req_ids(root)

    items = extract_line_items(root)
    eligible_subtotal = sum(it["amount"] for it in items)

    # Points redeemed (approx.) — Commander won’t echo LoyaltyRewardID back; use what we asked for.
    applied_dollars = float(f"{last_points_recommended:.2f}") if last_points_recommended > 0 else 0.0
    points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR))

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
            r = SESSION.post(f"{BACKEND_URL}/api/pos/finalize-transaction", json=payload, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                pts_earned = int(data.get("pointsEarned", 0) or 0)
                new_bal    = int(data.get("newBalance", 0) or 0)
                if applied_dollars > 0:
                    receipt_lines.append(f"Loyalty Discount Applied: ${applied_dollars:.2f}")
                    receipt_lines.append(f"Points Redeemed: {points_redeemed} pts (${applied_dollars:.2f})")
                receipt_lines.append(f"Points Earned: {pts_earned} pts")
                receipt_lines.append(f"New Balance: {new_bal} pts")
            else:
                log(f"⚠ finalize-transaction failed: {r.status_code}")
        except Exception as e:
            log(f"⚠ Finalize error: {e}")

    if not receipt_lines:
        receipt_lines.append("Thank you for shopping at Birdies!")

    current_customer = None
    last_points_recommended = 0.0

    rec_xml = "\n".join(f"      <ns3:ReceiptLine>{line}</ns3:ReceiptLine>" for line in receipt_lines)
    return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:CustomerMessageData>
    <ns3:ReceiptData>
{rec_xml}
    </ns3:ReceiptData>
  </ns3:CustomerMessageData>
</ns3:FinalizeRewardsResponse>"""

def build_cancel_txn_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    log("Transaction cancelled; clearing session")
    # EPS expects a response so that store-and-forward can confirm receipt. :contentReference[oaicite:12]{index=12}
    return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
</ns3:CancelTransactionResponse>"""

def build_end_period_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""<ns3:EndPeriodResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns4:Result><Success/></ns4:Result>
</ns3:EndPeriodResponse>"""

def build_customer_msg_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""<ns3:GetCustomerMessagingResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq)}
  <ns3:CustomerMessageData>
    <ns3:DisplayData>
      <ns3:DisplayCommand device="POS-Cashier" sequence="WhenReceived" duration="3">
        <ns3:DisplayLine>Welcome to Birdies Loyalty!</ns3:DisplayLine>
      </ns3:DisplayCommand>
    </ns3:DisplayData>
  </ns3:CustomerMessageData>
</ns3:GetCustomerMessagingResponse>"""

# =========================
# Connection handler
# =========================

def handle_client(conn: socket.socket, addr) -> None:
    peer = f"{addr[0]}:{addr[1]}"
    log(f"EPS connected from {peer}")

    if EXPECTED_EPS_IP and addr[0] != EXPECTED_EPS_IP:
        log(f"⚠ Rejecting unexpected EPS IP: {addr[0]}")
        try: conn.close()
        except Exception: pass
        return

    # Configure TCP keep-alive to prevent FIN_WAIT issues
    # Enable TCP keep-alive
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # Time before starting keep-alive probes (seconds)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
    # Interval between keep-alive probes (seconds)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
    # Number of failed probes before declaring connection dead
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    log(f"✓ TCP keep-alive configured for {peer}")

    # First heartbeat to our backend with the real EPS IP
    send_backend_heartbeat(addr[0])

    try:
        conn.settimeout(180)
        while True:
            data = recv_frame(conn)
            if not data:
                log(f"EPS disconnected: {peer}")
                break

            try:
                root, _raw = parse_xml(data)
            except Exception as e:
                log(f"XML parse error from {peer}: {e}")
                break

            tag = (root.tag or "").strip()
            # Commander uses namespaced tags; we've stripped namespaces already.
            if tag == "GetLoyaltyOnlineStatusRequest":
                send_xml(conn, build_online_status_response(root))
                send_backend_heartbeat(addr[0])

            elif tag == "GetRewardsRequest":
                send_xml(conn, build_get_rewards_response(root))

            elif tag == "FinalizeRewardsRequest":
                send_xml(conn, build_finalize_response(root))

            elif tag == "CancelTransactionRequest":
                send_xml(conn, build_cancel_txn_response(root))

            elif tag == "GetCustomerMessagingRequest":
                send_xml(conn, build_customer_msg_response(root))

            elif tag == "EndPeriodRequest":
                send_xml(conn, build_end_period_response(root))

            elif tag in ("BeginCustomerRequest", "EndCustomerRequest", "CancelRedemptionRequest",
                         "ReverseTransactionRequest", "GetRewardStatusRequest"):
                log(f"{tag} received (no special handling)")
                # EPS expects responses for reverse/cancel-redemption/get-status too; you can add as needed.

            else:
                log(f"⚠ Unhandled message type: {tag}")

    except socket.timeout:
        log(f"EPS timeout: {peer}")
    except Exception as e:
        log(f"EPS error: {peer} - {e}")
    finally:
        try: conn.close()
        except Exception: pass
        log(f"Connection closed: {peer}")

# =========================
# Server
# =========================

def serve():
    log("Starting Birdies Loyalty Edge Agent (Verifone EPS)")
    log(f"Store: {PDI_STORE_NUMBER} | POS Type: {POS_TYPE} | POS ID: {POS_ID}")
    log(f"Backend: {BACKEND_URL}")
    log(f"Listening on {HOST}:{PORT}")

    # Background heartbeat to our backend
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
