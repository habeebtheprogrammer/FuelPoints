#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - PASSPORT PUNCH CARD SUPPORT (v2 - fixed)

INCLUDES BOTH FIXES:

FIX #1: Masked LoyaltyID + session stability across follow-up GetRewards/Finalize
- Passport often sends:
    GetRewardsRequest with real entry (e.g. 2405851628)
    then GetRewardsRequest + FinalizeRewardsRequest with masked ******1628
- We now key session state by LoyaltySequenceID (stable across the transaction).
- We NEVER attempt backend lookup using a masked LoyaltyID.
- We reuse the existing session for masked follow-ups.

FIX #1b: "BeginCustomerRequest/EndCustomerRequest resets my session" (fuel/outside sales noise)
- Passport can send Begin/EndCustomer for OUTSIDE SALES (fuel) while an inside transaction is still active.
- We DO NOT reset session on BeginCustomerRequest / EndCustomerRequest anymore.
- We only clear session on FinalizeRewardsRequest (after processing) or CancelTransactionRequest.

FIX #2: Punch miscount when FREE ITEM is applied (no JS/backend changes required)
- Backend /record-purchase counts punches by quantity for eligible UPCs and skips only if amount <= 0.
- Passport Finalize can keep SalesAmount > 0 even when item is free via loyalty promotion.
- We track which line number we targeted for the punch free item (RewardTargetLineNumber).
- On Finalize, we confirm the reward actually applied using Promotion/LoyaltyRewardID on the item line.
- Then we adjust the payload we send to /record-purchase by splitting the line:
    paid portion: quantity reduced, amount > 0
    free portion: quantity = free_units, amount = 0.0
  so the backend naturally skips counting punches for the free unit.

NOTES:
- On Windows, binding HOST to an IP you *don't have assigned* causes WinError 10049.
  If that happens, set HOST="0.0.0.0" or your machine's actual IP on the loyalty NIC.
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
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =========================
# Configuration
# =========================

# Bind address (Windows tip: use 0.0.0.0 unless your NIC truly has the specific IP)
HOST = "0.0.0.0"
PORT = 9000

EXPECTED_POS_IP = "10.5.50.2"  # set None to allow all

PDI_STORE_NUMBER = "1370"
POS_ID = "24379"
POS_TYPE = "Passport"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15

VENDOR_NAME = "DemoLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

REWARD_ID         = "DEMO-1OFF"   # points basket coupon
RECEIPT_SHORT     = "$1OFF"
RECEIPT_LONG      = "Loyalty $ Off"
POINTS_PER_DOLLAR = 100

PUNCH_REWARD_ID = "PUNCH-REWARD"

SESSION = requests.Session()
REQUEST_TIMEOUT = (3, 5)

# POSLOYALTY framing
SIGNATURE = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE   = 1
ACTION_HEARTBEAT = 2


# =========================
# Session store keyed by LoyaltySequenceID
# =========================

@dataclass
class FreePunchLine:
    punch_card_id: int
    punch_card_name: str
    line_no: int
    upc: str
    free_units: int
    loyalty_reward_id: str

@dataclass
class TxnSession:
    loyalty_sequence_id: str
    customer: dict
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    applied_free_lines: List[FreePunchLine] = field(default_factory=list)
    promotions: List[dict] = field(default_factory=list)

# In-memory session map (per process)
SESSIONS: Dict[str, TxnSession] = {}
SESSION_TTL_SECONDS = 10 * 60  # safety cleanup: 10 minutes


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

def cleanup_sessions() -> None:
    now = time.time()
    expired = [k for k, s in SESSIONS.items() if (now - s.last_seen_at) > SESSION_TTL_SECONDS]
    for k in expired:
        del SESSIONS[k]
    if expired:
        log(f"[Session] Cleaned up {len(expired)} expired session(s)")

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
    log("→ Sent to POS:\n" + pretty_xml(xml_bytes))

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
    log("← Received from POS:\n" + pretty_xml(xml_bytes))
    root = ET.fromstring(raw)
    return root, raw

def get_req_ids(root: ET.Element):
    """
    IMPORTANT: This generates a LoyaltySequenceID if missing.
    That LoyaltySequenceID becomes our session key and is echoed back by POS on follow-up calls.
    """
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

def is_masked(val: str) -> bool:
    return bool(val) and ("*" in val)

def get_pos_transaction_id(root: ET.Element) -> str:
    return (root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or "").strip()

def normalize_upc(upc: str) -> str:
    return (upc or "").strip()


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
            "edgeVersion": "birdies-edge-passport-punch-2.0",
        }
        r = SESSION.post(f"{BACKEND_URL}/api/pos/heartbeat", json=payload, timeout=REQUEST_TIMEOUT)
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
# POS XML extraction helpers
# =========================

def extract_line_items(root: ET.Element):
    """
    Extract item lines from TransactionDetailGroup (status="normal").
    Captures:
      - line_no
      - upc (POSCode)
      - quantity (SalesQuantity)
      - amount (SalesAmount if present, else ActualSalesPrice * qty)
      - price (best per-unit)
      - actual_price (ActualSalesPrice)
      - promo_reward_ids (Promotion/LoyaltyRewardID list)
    """
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
        sales_amount_txt = il.findtext("SalesAmount")
        unit_price_txt = il.findtext("UnitPrice", "0")
        actual_price_txt = il.findtext("ActualSalesPrice", "0")
        regular_price_txt = il.findtext("RegularSellPrice", "0")

        def to_f(x):
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

        price = unit_price or actual_price or regular_price or 0.0

        if sales_amount_txt and sales_amount_txt.strip():
            amount = to_f(sales_amount_txt)
        else:
            amount = actual_price * qty

        promo_reward_ids = []
        for promo in il.findall("./Promotion"):
            lrid = (promo.findtext("LoyaltyRewardID") or "").strip()
            if lrid:
                promo_reward_ids.append(lrid)

        items.append({
            "line_no": line_no,
            "upc": upc,
            "description": desc,
            "quantity": qty,
            "amount": amount,
            "price": price,
            "actual_price": actual_price,
            "promo_reward_ids": promo_reward_ids,
        })
    return items

def detect_loyalty_tender(root: ET.Element, reward_id: str) -> float:
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
# Backend API calls
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
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
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
        log(f"⚠ Punch redeem failed: {r.status_code}")
        return {}
    except Exception as e:
        log(f"⚠ Punch redeem error: {e}")
        return {}


# =========================
# Punch miscount fix helpers (Python-only)
# =========================

def confirmed_free_lines_from_finalize(final_items: list) -> set:
    """
    Confirm free item applied by checking Promotion/LoyaltyRewardID on the item line.
    Returns set of line_no that show a LoyaltyRewardID starting with PUNCH_REWARD_ID.
    """
    confirmed = set()
    for it in final_items:
        for lrid in it.get("promo_reward_ids", []) or []:
            if lrid.startswith(PUNCH_REWARD_ID):
                confirmed.add(int(it.get("line_no", 0) or 0))
                break
    return confirmed

def adjust_items_for_record_purchase(final_items: list, session_free_lines: List[FreePunchLine]) -> list:
    """
    Split targeted free lines into paid + free pseudo-lines so backend doesn't count punches for free unit(s).

    We only manipulate the JSON we send to /record-purchase.
    """
    free_map: Dict[int, int] = {}
    for f in session_free_lines:
        free_map[f.line_no] = free_map.get(f.line_no, 0) + int(f.free_units or 1)

    adjusted = []
    for it in final_items:
        ln = int(it.get("line_no", 0) or 0)
        upc = (it.get("upc") or "").strip()

        try:
            qty_int = int(float(it.get("quantity", 1) or 1))
        except Exception:
            qty_int = 1

        # If not an upc line, keep as-is
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

        # Paid portion (amount must be > 0)
        if paid_units > 0:
            paid = dict(it)
            paid["quantity"] = float(paid_units)
            if unit_price > 0:
                paid["amount"] = round(unit_price * paid_units, 2)
            else:
                # proportional fallback
                paid["amount"] = round(max(0.01, orig_amt * (paid_units / max(1, qty_int))), 2)
            adjusted.append(paid)

        # Free portion (amount=0 so backend skips punch)
        if free_units > 0:
            free = dict(it)
            free["quantity"] = float(free_units)
            free["amount"] = 0.0
            adjusted.append(free)

    return adjusted


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
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    txn_id = get_pos_transaction_id(root)

    # Extract loyalty id / phone
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone      = (root.findtext(".//PhoneNumber") or "").strip()

    # If LoyaltyID looks like a 10-digit phone number, treat it as phone (only if not masked)
    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10 and not is_masked(loyalty_id):
        phone = digits
        loyalty_id = ""

    # Basket
    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items) [txn={txn_id} loy={loy_seq}]")
        for idx, it in enumerate(items, 1):
            log(f"  {idx}. Line {it['line_no']}: UPC {it['upc']} Qty {it['quantity']} Amount ${it['amount']:.2f}")
        log("=" * 60)
    else:
        log(f"🛒 No items yet [txn={txn_id} loy={loy_seq}]")

    # Session fetch/create
    sess = SESSIONS.get(loy_seq)
    if sess:
        sess.last_seen_at = time.time()

    # Masked follow-up: NEVER lookup. Must reuse existing session.
    if is_masked(loyalty_id):
        if not sess:
            log("⚠ Masked LoyaltyID but no session exists to reuse")
            return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()
        log(f"✓ Masked LoyaltyID follow-up; reusing session customer [txn={txn_id} loy={loy_seq}]")
        customer = sess.customer
    else:
        # Not masked: lookup customer (or reuse session if already found)
        if sess:
            customer = sess.customer
        else:
            if not loyalty_id and not phone:
                return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

            try:
                customer = backend_customer_lookup(loyalty_id, phone)
            except Exception as e:
                log(f"⚠ Customer lookup error: {e}")
                return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">System Error</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

            if not customer:
                ident = loyalty_id or phone
                log(f"⚠ Customer not found: {ident}")
                return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer not found</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()

            SESSIONS[loy_seq] = TxnSession(loyalty_sequence_id=loy_seq, customer=customer)
            sess = SESSIONS[loy_seq]
            log(f"✓ Customer found: {customer.get('firstName','')} {customer.get('lastName','')} [txn={txn_id} loy={loy_seq}]")

    points = int(customer.get("pointsBalance", 0) or 0)
    customer_id = int(customer.get("customerId") or 0)

    # Masked display
    display_id = loyalty_id or phone or ""
    masked_display = loyalty_id if is_masked(loyalty_id) else ((display_id[-4:].rjust(10, "*")) if display_id else "****")

    # Punch evaluation
    punch_rewards_xml: List[str] = []
    if customer_id and items:
        punch_eval = evaluate_punch_cards(customer_id, items)
        punch_cards = punch_eval.get("punchCards", []) or []

        if punch_cards:
            log("🎯 PUNCH CARD STATUS:")
            for pc in punch_cards:
                current = int(pc.get("currentPunches", 0) or 0)
                basket  = int(pc.get("punchesFromBasket", 0) or 0)
                required = int(pc.get("punchesRequired", 10) or 10)
                punches_needed = max(0, required - current)

                already_full = current >= required
                buying_extra = basket > punches_needed  # keeping your behavior
                should_trigger = already_full or buying_extra

                status_line = f"  • {pc.get('punchCardName','Punch Card')}: {current}/{required} stored"
                if basket > 0:
                    status_line += f" + {basket} basket"
                if should_trigger:
                    status_line += " 🎁 REWARD TRIGGERED!"
                else:
                    status_line += f" (need {punches_needed} more to trigger)"
                log(status_line)

                if should_trigger:
                    # pick cheapest eligible item line for the free item
                    eligible = [it for it in items if it.get("upc") and float(it.get("amount", 0) or 0) > 0 and float(it.get("price", 0) or 0) > 0]
                    if not eligible:
                        continue
                    cheapest = min(eligible, key=lambda it: float(it.get("price", 0) or 0))
                    line_no = int(cheapest.get("line_no", 0) or 0)
                    reward_id = f"{PUNCH_REWARD_ID}-{int(pc.get('punchCardId') or 0)}"
                    punch_name = pc.get("punchCardName", "Punch Reward")

                    punch_rewards_xml.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>0.0000</RewardValue>
      <RewardLimit type="quantity">1</RewardLimit>
      <RewardReceiptDescShort>FREE</RewardReceiptDescShort>
      <RewardReceiptDescLong>{punch_name} FREE ITEM</RewardReceiptDescLong>
    </AddReward>""".rstrip())

                    # store intended free line for finalize correction
                    if sess:
                        sess.applied_free_lines.append(
                            FreePunchLine(
                                punch_card_id=int(pc.get("punchCardId") or 0),
                                punch_card_name=punch_name,
                                line_no=line_no,
                                upc=cheapest.get("upc", ""),
                                free_units=1,
                                loyalty_reward_id=reward_id,
                            )
                        )

    # Points redemption (kept as-is)
    subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
    log(f"Eligible subtotal: ${subtotal:.2f}")

    points_reward_xml = ""
    if subtotal > 0 and points >= POINTS_PER_DOLLAR:
        try:
            rr = SESSION.post(
                f"{BACKEND_URL}/api/pos/calculate-redemption",
                json={"customerId": customer_id, "eligibleSubtotal": subtotal, "lineItems": items},
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
        except Exception as e:
            log(f"⚠ calculate-redemption error: {e}")
    else:
        log("Customer does not have enough points for redemption, or subtotal is $0.00")

    # Combine rewards
    all_rewards = []
    all_rewards.extend(punch_rewards_xml)
    if points_reward_xml:
        all_rewards.append(points_reward_xml)

    if all_rewards:
        rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"
    else:
        rewards_block = "<RewardActions/>"

    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked_display}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()


def build_finalize_response(root: ET.Element) -> str:
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    txn_id = get_pos_transaction_id(root)

    final_items = extract_line_items(root)
    eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)
    log(f"Finalize: eligible subtotal ${eligible_subtotal:.2f} [txn={txn_id} loy={loy_seq}]")

    applied_dollars = detect_loyalty_tender(root, REWARD_ID)
    points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR)) if applied_dollars > 0 else 0
    if applied_dollars > 0:
        log(f"✓ Loyalty tender detected: ${applied_dollars:.2f}")
    else:
        log("ℹ No loyalty tender detected in finalize")

    sess = SESSIONS.get(loy_seq)
    if not sess:
        log("⚠ No session found for finalize; cannot post to backend")
        receipt_lines = ["Thank you for shopping at Birdies!"]
        receipt_xml = "\n".join(f"      <ReceiptLine>{line}</ReceiptLine>" for line in receipt_lines)
        return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <ReceiptData>
{receipt_xml}
    </ReceiptData>
  </CustomerMessageData>
</FinalizeRewardsResponse>""".strip()

    sess.last_seen_at = time.time()
    customer = sess.customer
    customer_id = int(customer.get("customerId") or 0)

    # Confirm which line(s) were actually free (Promotion/LoyaltyRewardID present)
    confirmed_free_lines = confirmed_free_lines_from_finalize(final_items)

    intended = sess.applied_free_lines
    intended_confirmed = [f for f in intended if f.line_no in confirmed_free_lines]

    if intended and not intended_confirmed:
        log("ℹ Punch free line(s) were intended, but not confirmed in finalize (POS may not have applied them)")
    if intended_confirmed:
        log("✅ Confirmed punch FREE ITEM line(s) in finalize:")
        for f in intended_confirmed:
            log(f"   - line {f.line_no} (reward {f.loyalty_reward_id})")

    # Adjust punch recording payload only when confirmed
    punch_record_items = adjust_items_for_record_purchase(final_items, intended_confirmed) if intended_confirmed else final_items

    receipt_lines: List[str] = []

    # Finalize transaction in backend (points)
    try:
        payload = {
            "customerId": customer_id,
            "eligibleSubtotal": eligible_subtotal,
            "pointsRedeemed": points_redeemed,
            "transactionId": txn_id,
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": final_items,
            "promotions": sess.promotions or [],
            "promotionDiscount": 0.0,
        }
        r = SESSION.post(f"{BACKEND_URL}/api/pos/finalize-transaction", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            pts_earned = data.get("pointsEarned", 0)
            new_bal = data.get("newBalance", 0)

            if applied_dollars > 0:
                receipt_lines.append(f"Loyalty Discount Applied: ${applied_dollars:.2f}")
                receipt_lines.append(f"Points Redeemed: {points_redeemed} pts (${applied_dollars:.2f})")
            receipt_lines.append(f"Points Earned: {pts_earned} pts")
            receipt_lines.append(f"New Balance: {new_bal} pts")
        else:
            log(f"⚠ finalize-transaction failed: {r.status_code}")
    except Exception as e:
        log(f"⚠ finalize-transaction error: {e}")

    # Record punches (using adjusted payload)
    try:
        punch_result = record_punches(customer_id, punch_record_items, txn_id or f"TXN-{uuid.uuid4().hex[:8].upper()}")
        punches_recorded = punch_result.get("punchesRecorded", [])
        if punches_recorded:
            log("  🎯 PUNCHES RECORDED:")
            for p in punches_recorded:
                log(f"     • {p.get('punchCardName')}: +{p.get('punchesAdded')} → {p.get('currentPunches')}/{p.get('punchesRequired')}")
    except Exception as e:
        log(f"⚠ Record punches error: {e}")

    # Redeem punch reward(s) only if confirmed applied
    redeemed_ids = set()
    for f in intended_confirmed:
        if f.punch_card_id and f.punch_card_id not in redeemed_ids:
            try:
                redeem_result = redeem_punch_reward(customer_id, f.punch_card_id, txn_id or f"TXN-{uuid.uuid4().hex[:8].upper()}")
                if redeem_result.get("success"):
                    log(f"  🎁 Redeemed punch reward: {f.punch_card_name} (id={f.punch_card_id})")
                    redeemed_ids.add(f.punch_card_id)
            except Exception as e:
                log(f"⚠ Punch redeem error: {e}")

    if not receipt_lines:
        receipt_lines = ["Thank you for shopping at Birdies!"]

    # Clear this session ONLY (do not touch anything else)
    del SESSIONS[loy_seq]

    receipt_xml = "\n".join(f"      <ReceiptLine>{line}</ReceiptLine>" for line in receipt_lines)
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
    if loy_seq in SESSIONS:
        del SESSIONS[loy_seq]
        log(f"[Session] CancelTransaction: removed session {loy_seq}")
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

    if EXPECTED_POS_IP and addr[0] != EXPECTED_POS_IP:
        log(f"⚠ Rejecting unexpected POS IP: {addr[0]}")
        try:
            conn.close()
        except Exception:
            pass
        return

    send_heartbeat(addr[0])

    try:
        conn.settimeout(180)
        while True:
            hdr = recv_exact(conn, 28)
            if not hdr:
                log(f"POS disconnected: {peer}")
                break

            action, data_len, chk_data = parse_header(hdr)

            if action == ACTION_HEARTBEAT:
                if data_len:
                    _ = recv_exact(conn, data_len)
                log(f"POS heartbeat from {peer}")
                continue

            data = recv_exact(conn, data_len)
            if len(data) != data_len or crc32(data) != chk_data:
                log("Payload CRC/length mismatch")
                break

            root, _raw = parse_xml(data)
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
                # DO NOT reset sessions here (fuel/outside sales can overlap!)
                log(f"{tag} received (ignored for session reset)")

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
    log("Starting Birdies Loyalty Edge Agent (Passport Punch Cards) [Fixed v2]")
    log(f"Store: {PDI_STORE_NUMBER} | POS Type: {POS_TYPE} | POS ID: {POS_ID}")
    log(f"Backend: {BACKEND_URL}")
    log(f"Listening on {HOST}:{PORT}")

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
