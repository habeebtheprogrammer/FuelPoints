#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Birdies Loyalty Edge Agent - PASSPORT PROMOS + PUNCH + POINTS (v3 - unified)

What this does:
- Promotions/discounts from backend (/api/pos/evaluate-promotions)
  -> Applies line-targeted newPrice rewards to Passport (best-price per UPC)
  -> On Finalize, only counts promo discounts that actually applied (reward IDs present)
- Punch cards (/api/punch-cards/evaluate + record-purchase + redeem)
  -> Applies FREE ITEM using line-targeted newPrice=0.0000, RewardLimit=1
  -> Fixes punch double-count by splitting the free unit in record-purchase payload (amount=0)
- Points redemption (/api/pos/calculate-redemption)
  -> Suggests DEMO-1OFF amountOff at basket level
  -> On Finalize, uses TenderInfo to compute pointsRedeemed accurately

Critical Passport fixes:
- Session keyed by LoyaltySequenceID (handles masked follow-ups ******1234)
- NEVER backend lookup with masked LoyaltyID
- Ignore BeginCustomerRequest/EndCustomerRequest for session resets
- Track CancelRedemptionRequest and exclude canceled promo reward ids from promo accounting

Points conversion:
- POINTS_PER_DOLLAR means "how many points equal $1 off".
  Example:
    POINTS_PER_DOLLAR = 10000  =>  10,000 points = $1.00 off
- We compute pointsRedeemed as: round(applied_dollars * POINTS_PER_DOLLAR)

Note:
- This script allows stacking by default: promos + points redemption + punch reward can all apply
  (you can change policy if you want).

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
from typing import Dict, List, Optional, Tuple


# =========================
# Configuration
# =========================
HOST = "0.0.0.0"
PORT = 9000
EXPECTED_POS_IP = "10.5.50.2"  # set None to allow all

PDI_STORE_NUMBER = "1340"
POS_ID = "24379"
POS_TYPE = "Passport"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15

# Must match working demo server so Passport applies rewards reliably
VENDOR_NAME = "DemoLoyalty"
VENDOR_VER = "1.0"
IFACE_VER = "1.0"

# Points redemption
REWARD_ID = "DEMO-1OFF"
RECEIPT_SHORT = "$1OFF"          # <= 8 chars
RECEIPT_LONG = "Loyalty $ Off"   # <= 24 chars

# IMPORTANT: points conversion
# 100 pts = $1    -> 100
# 500 pts = $1    -> 500
# 10,000 pts = $1 -> 10000 (your EPS example)
POINTS_PER_DOLLAR = 10000

# Punch reward prefix
PUNCH_REWARD_ID = "PUNCH-REWARD"

SESSION_HTTP = requests.Session()
REQUEST_TIMEOUT = (3, 5)

# POSLOYALTY framing
SIGNATURE = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE = 1
ACTION_HEARTBEAT = 2

SESSION_TTL_SECONDS = 10 * 60


# =========================
# Session Store (keyed by LoyaltySequenceID)
# =========================
@dataclass
class PromoLineApplied:
    reward_id: str
    promo_id: str
    upc: str
    discount: float


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
    customer: Optional[dict] = None

    last_seen_at: float = field(default_factory=time.time)

    # Promos computed/sent in latest GetRewards
    promo_lines_sent: List[PromoLineApplied] = field(default_factory=list)
    promo_meta_by_id: Dict[str, dict] = field(default_factory=dict)  # promo_id -> promo dict copy

    # Punch free lines intended in latest GetRewards
    applied_free_lines: List[FreePunchLine] = field(default_factory=list)

    # Points redemption suggested in latest GetRewards
    last_points_recommended: float = 0.0

    # Cancelled rewards (CancelRedemptionRequest)
    cancelled_reward_ids: set = field(default_factory=set)


SESSIONS: Dict[str, TxnSession] = {}


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


def normalize_upc(upc: str) -> str:
    return (upc or "").strip()


def get_pos_transaction_id(root: ET.Element) -> str:
    return (root.findtext(".//POSTransactionID") or root.findtext(".//TransactionID") or "").strip()


def finalize_has_reward_anywhere(root: ET.Element, reward_id: str) -> bool:
    if not reward_id:
        return False
    for node in root.findall(".//LoyaltyRewardID"):
        if (node.text or "").strip() == reward_id:
            return True
    return False


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
            "edgeVersion": "birdies-passport-promos+punch+points-v3.0",
        }
        r = SESSION_HTTP.post(f"{BACKEND_URL}/api/pos/heartbeat", json=payload, timeout=REQUEST_TIMEOUT)
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
def extract_line_items(root: ET.Element) -> List[dict]:
    """
    Only ItemLine with status="normal".
    Also collects ItemLine/Promotion/LoyaltyRewardID values so we can confirm punch free item applied.
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
        atxt = il.findtext("SalesAmount")
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

        price = unit_price or actual_price or regular_price or 0.0

        if atxt and atxt.strip():
            amount = to_f(atxt)
        else:
            amount = actual_price * qty

        promo_reward_ids = []
        for promo in il.findall("./Promotion"):
            lrid = (promo.findtext("LoyaltyRewardID") or "").strip()
            if lrid:
                promo_reward_ids.append(lrid)

        items.append(
            {
                "line_no": line_no,
                "upc": upc,
                "description": desc,
                "quantity": qty,
                "amount": amount,
                "price": price,
                "unit_price": unit_price,
                "actual_price": actual_price,
                "regular_price": regular_price,
                "promo_reward_ids": promo_reward_ids,
            }
        )
    return items


def get_current_unit_price(item: dict) -> float:
    for key in ("unit_price", "actual_price", "regular_price"):
        val = item.get(key, 0.0)
        if val and float(val) > 0:
            return float(val)
    # fallback
    try:
        return float(item.get("price", 0) or 0)
    except Exception:
        return 0.0


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


def confirmed_free_lines_from_finalize(final_items: list) -> set:
    """
    Confirm punch free items applied by checking Promotion/LoyaltyRewardID on item line.
    Returns set of line_no where a LoyaltyRewardID starts with "PUNCH-REWARD".
    """
    confirmed = set()
    for it in final_items:
        ln = int(it.get("line_no", 0) or 0)
        for lrid in it.get("promo_reward_ids", []) or []:
            if lrid.startswith(PUNCH_REWARD_ID):
                confirmed.add(ln)
                break
    return confirmed


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


def evaluate_promotions(items: list) -> list:
    if not items:
        return []

    # Group by UPC, sum quantities (backend expects combined)
    upc_groups = {}
    for item in items:
        upc = (item.get("upc") or "").strip()
        if not upc:
            continue
        if upc not in upc_groups:
            upc_groups[upc] = {"upc": upc, "quantity": 0.0, "price": float(item.get("price", 0) or 0)}
        upc_groups[upc]["quantity"] += float(item.get("quantity", 1) or 1)

    if not upc_groups:
        return []

    payload = {"pdiStoreNumber": PDI_STORE_NUMBER, "items": list(upc_groups.values())}

    try:
        r = SESSION_HTTP.post(f"{BACKEND_URL}/api/pos/evaluate-promotions", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("promotions", []) or []
        return []
    except Exception:
        return []


def calculate_redemption(customer_id: int, eligible_subtotal: float, line_items: list) -> float:
    """
    Returns recommended dollars off. Points cost is computed locally using POINTS_PER_DOLLAR.
    """
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


def finalize_transaction_backend(
    customer_id: int,
    eligible_subtotal: float,
    transaction_id: str,
    line_items: list,
    promotions: list,
    promotion_discount: float,
    points_redeemed: int,
) -> None:
    try:
        payload = {
            "customerId": customer_id,
            "eligibleSubtotal": eligible_subtotal,
            "pointsRedeemed": points_redeemed,
            "transactionId": transaction_id,
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "lineItems": line_items,
            "promotions": promotions or [],
            "promotionDiscount": float(promotion_discount or 0),
        }
        r = SESSION_HTTP.post(f"{BACKEND_URL}/api/pos/finalize-transaction", json=payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            log(f" ✓ Finalize OK: pointsEarned={data.get('pointsEarned', 0)} newBalance={data.get('newBalance', 0)}")
        else:
            log(f" ⚠ finalize-transaction failed: {r.status_code}")
    except Exception as e:
        log(f" ⚠ finalize-transaction error: {e}")


def evaluate_punch_cards(customer_id: int, line_items: list) -> dict:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={"customerId": customer_id, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT,
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
            timeout=REQUEST_TIMEOUT,
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
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
        return {}
    except Exception:
        return {}


# =========================
# Promo conversion: Passport AddReward (newPrice) with best-price logic
# =========================
def build_promotion_rewards_xml(
    items: list,
    promotions: list,
) -> Tuple[List[str], List[PromoLineApplied], Dict[str, dict]]:
    """
    Best-price per UPC by lowest implied per-unit new price.
    Applies line-targeted newPrice with RewardLimit quantity.
    Returns (xml_blocks, promo_lines, promo_meta_by_id).
    """
    if not promotions:
        return [], [], {}

    # Map UPC -> lines
    upc_to_lines: Dict[str, List[dict]] = {}
    for it in items:
        upc = (it.get("upc") or "").strip()
        if upc:
            upc_to_lines.setdefault(upc, []).append(it)

    # Group promos by (upc, promo_id) and compute per-unit new price
    grouped: Dict[Tuple[str, str], dict] = {}
    for promo in promotions:
        upc = (promo.get("upc") or "").strip()
        promo_id = str(promo.get("promotionId") or "").strip()
        if not upc or not promo_id:
            continue

        promo_qty = int(promo.get("quantity", 2) or 2)
        bundle_count = int(promo.get("bundleCount", 0) or 0)
        promo_price = float(promo.get("promoPrice", 0) or 0)

        if bundle_count <= 0:
            continue

        total_units = max(bundle_count * promo_qty, 1)
        per_unit_new_price = promo_price / total_units if total_units else 0.0

        key = (upc, promo_id)
        if key not in grouped:
            grouped[key] = {
                "promo": promo,
                "per_unit_price": per_unit_new_price,
                "total_bundle_count": bundle_count,
            }
        else:
            grouped[key]["total_bundle_count"] += bundle_count

    # Pick best promo per UPC by lowest per-unit
    best_by_upc: Dict[str, dict] = {}
    for (upc, _pid), data in grouped.items():
        if upc not in best_by_upc or data["per_unit_price"] < best_by_upc[upc]["per_unit_price"]:
            best_by_upc[upc] = data

    add_rewards: List[str] = []
    promo_lines: List[PromoLineApplied] = []
    promo_meta_by_id: Dict[str, dict] = {}

    for upc, best_data in best_by_upc.items():
        promo = best_data["promo"]
        promo_id = str(promo.get("promotionId") or "").strip()
        if not promo_id:
            continue

        promo_qty = int(promo.get("quantity", 2) or 2)
        bundle_count = int(best_data["total_bundle_count"] or 0)
        per_unit_new_price = float(best_data["per_unit_price"] or 0.0)

        promo_name = promo.get("name") or promo.get("itemGroupName") or "Promo"
        display_name = str(promo_name)[:24]

        matching_lines = upc_to_lines.get(upc, [])
        if not matching_lines:
            continue

        total_units_needed = bundle_count * promo_qty
        remaining_units = total_units_needed

        meta = dict(promo)
        meta["name"] = display_name
        promo_meta_by_id[promo_id] = meta

        for it in matching_lines:
            if remaining_units <= 0:
                break

            current_price = get_current_unit_price(it)
            if current_price <= 0:
                continue

            if current_price <= per_unit_new_price:
                continue

            take_qty = min(int(float(it.get("quantity", 1) or 1)), remaining_units)
            if take_qty <= 0:
                continue

            line_no = int(it.get("line_no", 0) or 0)
            if line_no <= 0:
                continue

            reward_id = f"PROMO-{promo_id}-L{line_no}"

            discount_per_unit = current_price - per_unit_new_price
            line_discount = round(discount_per_unit * take_qty, 2)
            if line_discount <= 0:
                remaining_units -= take_qty
                continue

            add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{reward_id}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{line_no}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>{per_unit_new_price:.4f}</RewardValue>
      <RewardLimit type="quantity">{take_qty}</RewardLimit>
      <RewardReceiptDescShort>PROMO</RewardReceiptDescShort>
      <RewardReceiptDescLong>{display_name}</RewardReceiptDescLong>
    </AddReward>""".rstrip())

            promo_lines.append(
                PromoLineApplied(
                    reward_id=reward_id,
                    promo_id=promo_id,
                    upc=upc,
                    discount=float(f"{line_discount:.2f}"),
                )
            )

            remaining_units -= take_qty

    return add_rewards, promo_lines, promo_meta_by_id


# =========================
# Punch miscount fix: split free unit in record-purchase payload
# =========================
def adjust_items_for_record_purchase(final_items: list, free_lines: List[FreePunchLine]) -> list:
    """
    Split targeted free line into paid + free pseudo-lines.
    Backend skips counting punches for free unit because amount=0.0.
    """
    free_map: Dict[int, int] = {}
    for f in free_lines:
        free_map[f.line_no] = free_map.get(f.line_no, 0) + int(f.free_units or 1)

    adjusted = []
    for it in final_items:
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
            if unit_price > 0:
                paid["amount"] = round(unit_price * paid_units, 2)
            else:
                paid["amount"] = round(max(0.01, orig_amt * (paid_units / max(1, qty_int))), 2)
            adjusted.append(paid)

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

    # Session fetch/create
    sess = SESSIONS.get(loy_seq)
    if not sess:
        sess = TxnSession(loyalty_sequence_id=loy_seq)
        SESSIONS[loy_seq] = sess
    sess.last_seen_at = time.time()

    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone = (root.findtext(".//PhoneNumber") or "").strip()

    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10 and not is_masked(loyalty_id):
        phone = digits
        loyalty_id = ""

    items = extract_line_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 PASSPORT ITEMS ({len(items)}) [txn={txn_id} loy={loy_seq}]")
        for i, it in enumerate(items, 1):
            log(f" {i}. Line {it['line_no']} UPC {it['upc']} Qty {it['quantity']} Amt ${it['amount']:.2f}")
        log("=" * 60)

    # Reset latest-computed state for this txn view
    sess.promo_lines_sent = []
    sess.promo_meta_by_id = {}
    sess.applied_free_lines = []
    sess.last_points_recommended = 0.0
    # keep cancelled_reward_ids

    # ---- 1) PROMOS (guest or logged in) ----
    promos = evaluate_promotions(items)
    promo_rewards_xml, promo_lines, promo_meta_by_id = build_promotion_rewards_xml(items, promos)
    sess.promo_lines_sent = promo_lines
    sess.promo_meta_by_id = promo_meta_by_id

    # ---- 2) CUSTOMER LOOKUP (masked-safe) ----
    customer: Optional[dict] = None

    if is_masked(loyalty_id):
        if not sess.customer:
            log("⚠ Masked LoyaltyID but no session customer exists yet")
            # allow promos-only guest response
            customer = None
        else:
            customer = sess.customer
    else:
        if sess.customer:
            customer = sess.customer
        else:
            if loyalty_id or phone:
                try:
                    customer = backend_customer_lookup(loyalty_id, phone)
                except Exception as e:
                    log(f"⚠ customer-lookup error: {e}")
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

                sess.customer = customer

    # If still no customer: promos-only guest path
    points_balance = 0
    customer_id = 0
    masked_display = "Guest"

    if customer:
        points_balance = int(customer.get("pointsBalance", 0) or 0)
        customer_id = int(customer.get("customerId") or 0)

        display_id = phone or loyalty_id or ""
        if is_masked(loyalty_id):
            masked_display = loyalty_id
        else:
            masked_display = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    # ---- 3) PUNCH REWARDS (only if customer exists) ----
    punch_rewards_xml: List[str] = []
    if customer_id and items:
        punch_eval = evaluate_punch_cards(customer_id, items)
        punch_cards = punch_eval.get("punchCards", []) or []

        # Trigger logic (same pattern you used previously)
        for pc in punch_cards:
            if "rewardReady" in pc and not bool(pc.get("rewardReady")):
                continue

            current = int(pc.get("currentPunches", 0) or 0)
            basket = int(pc.get("punchesFromBasket", 0) or 0)
            required = int(pc.get("punchesRequired", 10) or 10)
            punches_needed = max(0, required - current)

            already_full = current >= required
            buying_extra = basket > punches_needed
            should_trigger = already_full or buying_extra
            if not should_trigger:
                continue

            # pick cheapest eligible line by price
            eligible = [it for it in items if it.get("upc") and float(it.get("amount", 0) or 0) > 0 and float(it.get("price", 0) or 0) > 0]
            if not eligible:
                continue
            cheapest = min(eligible, key=lambda it: float(it.get("price", 0) or 0))

            line_no = int(cheapest.get("line_no", 0) or 0)
            if line_no <= 0:
                continue

            punch_card_id = int(pc.get("punchCardId") or 0)
            punch_name = (pc.get("punchCardName") or "Punch Reward").strip()
            reward_id = f"{PUNCH_REWARD_ID}-{punch_card_id}"

            # Passport free item via newPrice=0.0000
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

            sess.applied_free_lines.append(
                FreePunchLine(
                    punch_card_id=punch_card_id,
                    punch_card_name=punch_name,
                    line_no=line_no,
                    upc=(cheapest.get("upc") or "").strip(),
                    free_units=1,
                    loyalty_reward_id=reward_id,
                )
            )

    # ---- 4) POINTS REDEMPTION (only if customer exists) ----
    points_reward_xml = ""
    if customer_id and items:
        eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in items)

        # If points_balance is high enough for at least $1, still let backend decide recommended dollars
        if eligible_subtotal > 0 and points_balance >= POINTS_PER_DOLLAR:
            recommended = calculate_redemption(customer_id, eligible_subtotal, items)
            if recommended > 0:
                sess.last_points_recommended = float(f"{recommended:.2f}")
                points_reward_xml = f"""
    <AddReward>
      <LoyaltyRewardID>{REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="no"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{sess.last_points_recommended:.2f}</RewardValue>
      <RewardReceiptDescShort>{RECEIPT_SHORT}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{RECEIPT_LONG}</RewardReceiptDescLong>
    </AddReward>""".rstrip()

    # ---- Combine rewards: promos + punch + points ----
    all_rewards: List[str] = []
    if promo_rewards_xml:
        all_rewards.extend(promo_rewards_xml)
    if punch_rewards_xml:
        all_rewards.extend(punch_rewards_xml)
    if points_reward_xml:
        all_rewards.append(points_reward_xml)

    rewards_block = "<RewardActions/>"
    if all_rewards:
        rewards_block = "<RewardActions>\n" + "\n".join(all_rewards) + "\n  </RewardActions>"

    # If we have a customer OR promos exist, we can return "yes". Otherwise require ID.
    if customer_id or promo_rewards_xml:
        return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked_display}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()

    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="no">Customer ID Required</LoyaltyIDValidFlag>
  <RewardActions/>
</GetRewardsResponse>""".strip()


def build_finalize_response(root: ET.Element) -> str:
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    txn_id = get_pos_transaction_id(root) or f"TXN-{uuid.uuid4().hex[:8].upper()}"

    sess = SESSIONS.get(loy_seq)
    if not sess:
        log("⚠ No session found for finalize; skipping backend finalize")
        return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
</FinalizeRewardsResponse>""".strip()

    sess.last_seen_at = time.time()

    final_items = extract_line_items(root)
    eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)

    # Points applied is determined by TenderInfo in Finalize
    applied_dollars = detect_loyalty_tender(root, REWARD_ID)
    points_redeemed = int(round(applied_dollars * POINTS_PER_DOLLAR)) if applied_dollars > 0 else 0

    # Promo discount: only count promo reward lines that appear in finalize AND weren't cancelled
    promo_discount_total = 0.0
    promo_discount_by_promo_id: Dict[str, float] = {}

    for pl in sess.promo_lines_sent:
        if pl.reward_id in sess.cancelled_reward_ids:
            continue
        if finalize_has_reward_anywhere(root, pl.reward_id):
            promo_discount_total += float(pl.discount or 0)
            promo_discount_by_promo_id[pl.promo_id] = promo_discount_by_promo_id.get(pl.promo_id, 0.0) + float(pl.discount or 0)

    promo_discount_total = float(f"{promo_discount_total:.2f}")

    promotions_for_backend: List[dict] = []
    for promo_id, disc in promo_discount_by_promo_id.items():
        meta = sess.promo_meta_by_id.get(promo_id, {})
        out = dict(meta) if isinstance(meta, dict) else {}
        out["promotionId"] = promo_id
        out["discount"] = float(f"{disc:.2f}")
        promotions_for_backend.append(out)

    log(
        f"🏁 Finalize [txn={txn_id} loy={loy_seq}] subtotal=${eligible_subtotal:.2f} "
        f"promoDiscount=${promo_discount_total:.2f} pointsTender=${applied_dollars:.2f} pointsRedeemed={points_redeemed}"
    )

    # Backend finalize only if customer exists
    if sess.customer:
        customer_id = int(sess.customer.get("customerId") or 0)
        finalize_transaction_backend(
            customer_id=customer_id,
            eligible_subtotal=eligible_subtotal,
            transaction_id=txn_id,
            line_items=final_items,
            promotions=promotions_for_backend,
            promotion_discount=promo_discount_total,
            points_redeemed=points_redeemed,
        )

        # Punch recording + redeem
        # Confirm free lines actually applied
        confirmed_lines = confirmed_free_lines_from_finalize(final_items)
        intended_confirmed = [f for f in sess.applied_free_lines if int(f.line_no) in confirmed_lines]

        record_items = adjust_items_for_record_purchase(final_items, intended_confirmed) if intended_confirmed else final_items

        punch_result = record_punches(customer_id, record_items, txn_id)
        punches_recorded = punch_result.get("punchesRecorded", []) if isinstance(punch_result, dict) else []
        if punches_recorded:
            log(" 🎯 PUNCHES RECORDED:")
            for p in punches_recorded:
                log(f" • {p.get('punchCardName')}: +{p.get('punchesAdded')} → {p.get('currentPunches')}/{p.get('punchesRequired')}")

        redeemed = set()
        for f in intended_confirmed:
            if f.punch_card_id and f.punch_card_id not in redeemed:
                rr = redeem_punch_reward(customer_id, f.punch_card_id, txn_id)
                if isinstance(rr, dict) and rr.get("success"):
                    log(f" 🎁 Redeemed punch reward: {f.punch_card_name} (id={f.punch_card_id})")
                redeemed.add(f.punch_card_id)

    else:
        log("ℹ Guest finalize: no customer → no backend finalize or punch calls")

    # Clear session
    if loy_seq in SESSIONS:
        del SESSIONS[loy_seq]

    return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
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
            tag = (root.tag or "").strip()

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

            elif tag == "CancelRedemptionRequest":
                # Track cancellation so we don't overcount promo discount in finalize.
                _pos_seq, loy_seq = get_req_ids(root)
                reward_id = (root.findtext(".//LoyaltyRewardID") or "").strip()
                sess = SESSIONS.get(loy_seq)
                if sess and reward_id:
                    sess.cancelled_reward_ids.add(reward_id)
                    sess.last_seen_at = time.time()
                    log(f"[Session] CancelRedemption tracked: loy={loy_seq} reward={reward_id}")
                else:
                    log("CancelRedemptionRequest received (no session / no reward id)")
                # No response required

            elif tag in ("BeginCustomerRequest", "EndCustomerRequest"):
                # Ignore for session resets (outside sales noise)
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
    log("Starting Birdies Loyalty Edge Agent (Passport Promos + Punch + Points) [v3]")
    log(f"Store: {PDI_STORE_NUMBER} | POS Type: {POS_TYPE} | POS ID: {POS_ID}")
    log(f"Backend: {BACKEND_URL}")
    log(f"Listening on {HOST}:{PORT}")
    log(f"POINTS_PER_DOLLAR = {POINTS_PER_DOLLAR}  (points per $1 off)")

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
