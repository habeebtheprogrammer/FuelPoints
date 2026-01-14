#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Birdies Loyalty Edge Agent (Verifone EPS) [PROMOS + LOYALTY HYBRID v5]
----------------------------------------------------------------------
One script that does:
  1) Promotions / discounts (2-for-$X, buy X get Y free, amount off, etc.)
     - Converted into EPS-compatible AddReward blocks (ticket-level amountOff)
  2) Loyalty (Punch cards + Points redemption)
     - Punch cards: line-targeted free-item reward (helps tax behavior) + backend-safe punch counting
     - Points redemption: ticket-level amountOff reward

Priority / stacking policy (as requested):
  - Evaluate and APPLY PROMO rewards first.
  - If ANY promo reward is applied, we DO NOT apply loyalty discounts (no punch reward, no points redemption).
  - We still allow loyalty "earning" in Finalize (points earned + punches recorded) if the customer is identified.
    (If you truly want promos to disable earning too, set DISABLE_EARNING_WHEN_PROMO=True)

EPS specifics:
  - 4-byte big-endian length prefix framing
  - ResponseHeader includes overallResult="success"
  - RewardTargetLineNumber=0 is reliable for ticket-level amountOff promos/points
  - For punch free-item, we use line-targeted amountOff + RewardLimit quantity=1

Backend endpoints (unchanged):
  - /api/pos/heartbeat
  - /api/pos/customer-lookup
  - /api/pos/evaluate-promotions
  - /api/pos/calculate-redemption
  - /api/pos/finalize-transaction
  - /api/punch-cards/evaluate
  - /api/punch-cards/record-purchase
  - /api/punch-cards/redeem

Store/Port:
  - PDI_STORE_NUMBER = "0300"
  - PORT = 9000
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
from typing import Dict, List, Optional, Tuple


# =========================
# Configuration
# =========================
HOST = "0.0.0.0"
PORT = 9000
EXPECTED_EPS_IP = None  # e.g. "10.5.50.1" to restrict

PDI_STORE_NUMBER = "0300"  # requested
POS_ID = "24379"
POS_TYPE = "Verifone-EPS"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15

VENDOR_NAME = "BirdiesLoyalty"
VENDOR_VER = "1.0"
DEFAULT_IFACE_VER = "1.0"

# Points redemption config:
# If your real program is "500 points = $1.00", keep 500.
# If it is "100 points = $1.00", set to 100.
POINTS_PER_DOLLAR = 500  # $1.00 off costs 500 points
REWARD_ID = "DEMO-1OFF"
RECEIPT_SHORT = "$OFF"
RECEIPT_LONG = "Loyalty Discount"

# Punch reward id prefix
PUNCH_REWARD_ID = "PUNCH-REWARD"

# Stacking policy switches
PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS = True   # requested behavior
DISABLE_EARNING_WHEN_PROMO = True            # if True: promos also block points earned + punches recorded

SESSION_HTTP = requests.Session()
REQUEST_TIMEOUT = (3, 5)  # (connect, read) seconds


# =========================
# PCATS Namespaces
# =========================
NS_LOY = "http://www.pcats.org/schema/naxml/loyalty/v01"
NS_CORE = "http://www.pcats.org/schema/core/v01"
NS_POSBO = "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"

NS_DECLS = (
    f'xmlns:ns2="{NS_POSBO}" '
    f'xmlns:ns4="{NS_CORE}" '
    f'xmlns:ns3="{NS_LOY}"'
)


# =========================
# Session Store (keyed by LoyaltySequenceID)
# =========================
@dataclass
class PunchRewardSent:
    punch_card_id: int
    punch_card_name: str
    reward_id: str
    reward_type: str  # free_item / amount_off / percent_off
    free_line_no: int = 0
    free_upc: str = ""
    free_units: int = 0


@dataclass
class FreeUnitAdjustment:
    punch_card_id: int
    punch_card_name: str
    reward_id: str
    line_no: int
    upc: str
    free_units: int = 1


@dataclass
class TxnSession:
    loy_seq: str
    iface_ver: str
    customer: Optional[dict] = None
    last_seen_at: float = field(default_factory=time.time)

    # Discount / promo state
    promotions_applied: List[dict] = field(default_factory=list)  # only those we actually applied
    promo_discount_total: float = 0.0
    promo_applied_flag: bool = False

    # Loyalty state (only if allowed for this txn)
    last_points_recommended: float = 0.0
    punch_rewards_sent: List[PunchRewardSent] = field(default_factory=list)


SESSIONS: Dict[str, TxnSession] = {}
SESSION_TTL_SECONDS = 10 * 60


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


# EPS framing: 4-byte big-endian length + UTF-8 XML payload.
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


def get_iface_ver(root: ET.Element) -> str:
    return (root.findtext(".//POSLoyaltyInterfaceVersion") or DEFAULT_IFACE_VER).strip()


def get_pos_transaction_id(root: ET.Element) -> str:
    return (
        (root.findtext(".//POSTransactionID") or "").strip()
        or (root.findtext(".//TransactionID") or "").strip()
        or (root.findtext(".//TransactionHeader/TransactionID") or "").strip()
    )


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
            "edgeVersion": "birdies-eps-promos-loyalty-hybrid-5.0",
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
    """
    Extract both ItemLine and MerchandiseCodeLine.
    Keep enough to:
      - compute promo discounts
      - choose a real ItemLine for punch free item targeting
      - send backend lineItems payload
    """
    items: List[dict] = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        status = (tline.get("status") or "").strip().lower()
        if status and status != "normal":
            continue

        item_line = tline.find("./ItemLine")
        merch_line = tline.find("./MerchandiseCodeLine")
        il = item_line if item_line is not None else merch_line
        if il is None:
            continue

        is_item_line = item_line is not None

        try:
            line_no = int(tline.findtext("./LineNumber", "0"))
        except Exception:
            line_no = 0

        # Some EPS lines use PaymentSystemsProductCode (PSC) instead of UPC
        psc = (il.findtext(".//PaymentSystemsProductCode") or "").strip()

        upc_raw = ""
        if is_item_line:
            upc_raw = (
                il.findtext("./ItemCode/POSCode")
                or il.findtext(".//POSCode")
                or il.findtext(".//UPC")
                or ""
            )
        else:
            # For merch lines, keep PSC in "upc" field to preserve grouping for promos,
            # but we'll avoid using merch lines as free-item targets.
            upc_raw = psc or (
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
                "is_item_line": is_item_line,
                "psc": psc,
            }
        )
    return items


def get_unit_price(it: dict) -> float:
    for k in ("unit_price", "actual_price", "regular_price", "price"):
        try:
            v = float(it.get(k, 0) or 0)
        except Exception:
            v = 0.0
        if v > 0:
            return v
    return 0.0


def choose_cheapest_eligible_itemline(items: List[dict]) -> Optional[dict]:
    """
    Choose a real ItemLine for punch-free reward targeting.
    Skip non-item lines and PSC=950 (as per your earlier behavior).
    """
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
    return min(eligible, key=lambda x: get_unit_price(x))


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

    upc_groups = {}
    for it in items:
        upc = it.get("upc", "")
        if not upc:
            continue
        if upc not in upc_groups:
            upc_groups[upc] = {"upc": upc, "quantity": 0.0, "price": float(it.get("price", 0) or 0)}
        upc_groups[upc]["quantity"] += float(it.get("quantity", 1) or 1)

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
# Promo conversion: EPS AddReward ticket-level amountOff
# =========================
def build_promotion_rewards_xml_eps(items: list, promotions: list) -> Tuple[List[str], List[dict], float]:
    """
    Convert backend promotions to EPS ticket-level amountOff rewards.

    Returns:
      (add_rewards_xml_list, applied_promotions_list, total_promo_discount)

    Important:
      - We compute the ACTUAL discount based on basket quantities and current unit price.
      - We store ONLY applied_promotions (with calculated 'discount') for finalize payload.
    """
    if not promotions:
        return [], [], 0.0

    upc_to_lines: Dict[str, List[dict]] = {}
    for it in items:
        upc = (it.get("upc") or "").strip()
        if not upc:
            continue
        upc_to_lines.setdefault(upc, []).append(it)

    # Pick best promo per UPC (prefers lowest implied per-unit new price when multipack)
    best_by_upc: Dict[str, dict] = {}
    for promo in promotions:
        upc = (promo.get("upc") or "").strip()
        if not upc:
            continue

        disc_type = promo.get("discountType", "multipack")
        qty = int(promo.get("quantity", 1) or 1)
        bundles = int(promo.get("bundleCount", 0) or 0)
        if bundles <= 0:
            continue

        if disc_type == "multipack":
            promo_price_total = float(promo.get("promoPrice", 0.0) or 0.0)
            total_units = max(qty * bundles, 1)
            per_unit_new_price = promo_price_total / total_units
        else:
            total_units = max(qty * bundles, 1)
            per_unit_new_price = None

        if upc not in best_by_upc:
            best_by_upc[upc] = {"promo": promo, "per_unit_new_price": per_unit_new_price, "total_units": total_units}
        else:
            existing = best_by_upc[upc]
            if per_unit_new_price is not None and (
                existing["per_unit_new_price"] is None or per_unit_new_price < existing["per_unit_new_price"]
            ):
                best_by_upc[upc] = {"promo": promo, "per_unit_new_price": per_unit_new_price, "total_units": total_units}

    add_rewards: List[str] = []
    applied_promotions: List[dict] = []
    total_discount_all = 0.0

    for upc, data in best_by_upc.items():
        promo = data["promo"]
        disc_type = promo.get("discountType", "multipack")
        qty = int(promo.get("quantity", 1) or 1)
        bundles = int(promo.get("bundleCount", 0) or 0)
        total_units_needed = qty * bundles
        remaining_units = total_units_needed

        matching_lines = upc_to_lines.get(upc, [])
        if not matching_lines or remaining_units <= 0:
            continue

        promo_id = promo.get("promotionId") or upc
        reward_id = f"PROMO-{promo_id}"
        promo_name = promo.get("name") or promo.get("itemGroupName") or "Promo"
        display_name = str(promo_name)[:24]

        total_discount_for_promo = 0.0

        for it in matching_lines:
            if remaining_units <= 0:
                break

            take_qty = int(min(float(it.get("quantity", 1) or 1), remaining_units))
            if take_qty <= 0:
                continue

            current_price = get_unit_price(it)
            if current_price <= 0:
                remaining_units -= take_qty
                continue

            discount_per_unit = 0.0
            if disc_type == "multipack":
                per_unit_new_price = float(data["per_unit_new_price"] or 0.0)
                discount_per_unit = max(0.0, current_price - per_unit_new_price)
            else:
                # generic total discount spread across all required units
                total_discount = float(promo.get("discount", 0.0) or 0.0)
                per_unit_discount = total_discount / max(total_units_needed, 1)
                discount_per_unit = min(per_unit_discount, current_price)

            line_discount = max(0.0, discount_per_unit * take_qty)
            total_discount_for_promo += line_discount
            remaining_units -= take_qty

        total_discount_for_promo = float(f"{total_discount_for_promo:.2f}")
        if total_discount_for_promo <= 0:
            continue

        total_discount_all += total_discount_for_promo

        add_rewards.append(
            f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{total_discount_for_promo:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PROMO</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{display_name}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip()
        )

        applied = dict(promo)
        applied["discount"] = total_discount_for_promo
        applied["name"] = display_name
        applied_promotions.append(applied)

    total_discount_all = float(f"{total_discount_all:.2f}")
    return add_rewards, applied_promotions, total_discount_all


# =========================
# Punch helpers: robust reward detection + record-purchase adjustment
# =========================
def finalize_has_reward_anywhere(root: ET.Element, reward_id: str) -> bool:
    if not reward_id:
        return False
    for node in root.findall(".//LoyaltyRewardID"):
        if (node.text or "").strip() == reward_id:
            return True
    return False


def remap_free_adjustments_to_finalize(final_items: list, adjustments: List[FreeUnitAdjustment]) -> List[FreeUnitAdjustment]:
    """
    If line_no changes between GetRewards and Finalize, fallback to UPC match.
    """
    existing_lines = {int(it.get("line_no", 0) or 0) for it in final_items}
    by_upc: Dict[str, List[dict]] = {}
    for it in final_items:
        upc = (it.get("upc") or "").strip()
        if upc:
            by_upc.setdefault(upc, []).append(it)

    remapped: List[FreeUnitAdjustment] = []
    for adj in adjustments:
        if adj.line_no in existing_lines:
            remapped.append(adj)
            continue
        cand = by_upc.get((adj.upc or "").strip(), [])
        if not cand:
            continue
        best = min(cand, key=lambda x: float(x.get("price", 0) or 0))
        remapped.append(
            FreeUnitAdjustment(
                punch_card_id=adj.punch_card_id,
                punch_card_name=adj.punch_card_name,
                reward_id=adj.reward_id,
                line_no=int(best.get("line_no", 0) or 0),
                upc=adj.upc,
                free_units=adj.free_units,
            )
        )
    return remapped


def adjust_items_for_record_purchase(final_items: list, adjustments: List[FreeUnitAdjustment]) -> list:
    """
    Split line into paid + free pseudo-line (amount=0) so backend skips punch for free unit.
    """
    free_map: Dict[int, int] = {}
    for adj in adjustments:
        free_map[adj.line_no] = free_map.get(adj.line_no, 0) + int(adj.free_units or 1)

    adjusted = []
    for it in final_items:
        ln = int(it.get("line_no", 0) or 0)
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

        orig_amt = float(it.get("amount", 0) or 0)
        unit_price = get_unit_price(it)

        if unit_price > 0:
            free_value = unit_price * free_qty
            paid_amt = max(0.0, round(orig_amt - free_value, 2))
        else:
            paid_amt = round(orig_amt * (paid_qty / max(1, qty_int)), 2)

        if paid_qty > 0:
            paid = dict(it)
            paid["quantity"] = float(paid_qty)
            paid["amount"] = paid_amt
            adjusted.append(paid)

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

    # Parse loyalty id / phone
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
            upc_disp = it.get("upc") or ""
            log(f" {i}. Line {it['line_no']} UPC/PSC {upc_disp} qty {it['quantity']} amt ${float(it['amount']):.2f}")
        log("=" * 60)

    # Session reuse/create
    sess = SESSIONS.get(loy_seq)
    if not sess:
        sess = TxnSession(loy_seq=loy_seq, iface_ver=iface_ver)
        SESSIONS[loy_seq] = sess
    sess.last_seen_at = time.time()
    sess.iface_ver = iface_ver
    sess.last_points_recommended = 0.0
    sess.punch_rewards_sent = []
    sess.promotions_applied = []
    sess.promo_discount_total = 0.0
    sess.promo_applied_flag = False

    # 1) PROMOS FIRST (always evaluate promos)
    promotions = evaluate_promotions(items)
    promo_rewards, applied_promos, promo_discount_total = build_promotion_rewards_xml_eps(items, promotions)

    sess.promotions_applied = applied_promos
    sess.promo_discount_total = promo_discount_total
    sess.promo_applied_flag = bool(promo_rewards)

    # 2) If no ID, we can still apply promos to guest
    if not loyalty_id and not phone:
        reward_xmls = list(promo_rewards)
        rewards_block = (
            "<ns3:RewardActions>\n" + "\n".join(reward_xmls) + "\n</ns3:RewardActions>"
            if reward_xmls else "<ns3:RewardActions/>"
        )
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="yes">Guest</ns3:LoyaltyIDValidFlag>
  {rewards_block}
</ns3:GetRewardsResponse>"""

    # 3) Customer lookup (or reuse if masked follow-up)
    if is_masked(loyalty_id) and sess.customer:
        customer = sess.customer
    else:
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

    sess.customer = customer
    customer_id = int(customer.get("customerId") or 0)
    points_balance = int(customer.get("pointsBalance", 0) or 0)

    display_id = phone or loyalty_id or ""
    masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    # 4) Decide whether to apply loyalty DISCOUNTS
    loyalty_discounts_allowed = True
    if PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS and sess.promo_applied_flag:
        loyalty_discounts_allowed = False

    loyalty_reward_xmls: List[str] = []

    if loyalty_discounts_allowed:
        # ---- PUNCH REWARDS ----
        punch_eval = evaluate_punch_cards(customer_id, items) if (customer_id and items) else {"punchCards": []}
        punch_cards = punch_eval.get("punchCards", []) or []

        for pc in punch_cards:
            # If backend provides rewardReady, require it
            if "rewardReady" in pc and not bool(pc.get("rewardReady")):
                continue

            current = int(pc.get("currentPunches", 0) or 0)
            basket = int(pc.get("punchesFromBasket", 0) or 0)
            required = int(pc.get("punchesRequired", 0) or 0)
            punches_needed = max(0, required - current)

            # v3 timing rule:
            already_full_before = (required > 0 and current >= required)
            buying_extra = (basket > punches_needed)
            should_apply_now = already_full_before or buying_extra

            punch_card_id = int(pc.get("punchCardId") or 0)
            punch_name = (pc.get("punchCardName") or "Punch Card").strip()
            reward_type = (pc.get("rewardType") or "free_item").strip()
            reward_value = pc.get("rewardValue") or "0"

            reward_id = f"{PUNCH_REWARD_ID}-{punch_card_id}"

            if reward_type == "free_item":
                if not should_apply_now:
                    continue

                chosen = choose_cheapest_eligible_itemline(items)
                if not chosen:
                    continue

                line_no = int(chosen.get("line_no", 0) or 0)
                unit_price = get_unit_price(chosen)
                if line_no <= 0 or unit_price <= 0:
                    continue

                loyalty_reward_xmls.append(f"""
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

                sess.punch_rewards_sent.append(
                    PunchRewardSent(
                        punch_card_id=punch_card_id,
                        punch_card_name=punch_name,
                        reward_id=reward_id,
                        reward_type="free_item",
                        free_line_no=line_no,
                        free_upc=(chosen.get("upc") or "").strip(),
                        free_units=1,
                    )
                )

            elif reward_type in ("dollar_off", "amount_off"):
                try:
                    amt = float(reward_value or 0)
                except Exception:
                    amt = 0.0
                if amt <= 0:
                    continue

                loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{punch_name}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())

                sess.punch_rewards_sent.append(
                    PunchRewardSent(
                        punch_card_id=punch_card_id,
                        punch_card_name=punch_name,
                        reward_id=reward_id,
                        reward_type="amount_off",
                    )
                )

            elif reward_type == "percent_off":
                try:
                    pct = float(reward_value or 0)
                except Exception:
                    pct = 0.0
                if pct <= 0:
                    continue
                subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
                amt = max(0.0, subtotal * (pct / 100.0))
                if amt <= 0:
                    continue

                loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{reward_id}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="yes"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{punch_name} {pct:.0f}%</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())

                sess.punch_rewards_sent.append(
                    PunchRewardSent(
                        punch_card_id=punch_card_id,
                        punch_card_name=punch_name,
                        reward_id=reward_id,
                        reward_type="percent_off",
                    )
                )

        # ---- POINTS REDEMPTION (ticket-level) ----
        eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
        if eligible_subtotal > 0 and points_balance >= POINTS_PER_DOLLAR:
            recommended = calculate_redemption(customer_id, eligible_subtotal, items)
            if recommended > 0:
                sess.last_points_recommended = float(f"{recommended:.2f}")
                loyalty_reward_xmls.append(f"""
  <ns3:AddReward>
    <ns3:LoyaltyRewardID>{REWARD_ID}</ns3:LoyaltyRewardID>
    <ns3:InstantRewardFlag value="no"/>
    <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
    <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
    <ns3:RewardValue>{sess.last_points_recommended:.2f}</ns3:RewardValue>
    <ns3:RewardReceiptDescShort>{RECEIPT_SHORT}</ns3:RewardReceiptDescShort>
    <ns3:RewardReceiptDescLong>{RECEIPT_LONG}</ns3:RewardReceiptDescLong>
  </ns3:AddReward>""".rstrip())

    # Combine rewards: PROMOS first, then loyalty (if allowed)
    reward_xmls = []
    if promo_rewards:
        reward_xmls.extend(promo_rewards)
    if loyalty_reward_xmls:
        reward_xmls.extend(loyalty_reward_xmls)

    reward_actions = (
        "<ns3:RewardActions>\n" + "\n".join(reward_xmls) + "\n</ns3:RewardActions>"
        if reward_xmls else "<ns3:RewardActions/>"
    )

    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="yes">{masked}</ns3:LoyaltyIDValidFlag>
  <ns3:PointsBalance>{points_balance}</ns3:PointsBalance>
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

    # Parse final items from finalize (most accurate)
    final_items = extract_line_items(root)
    eligible_subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)

    # If no customer, just clear session
    if not sess.customer:
        if loy_seq in SESSIONS:
            del SESSIONS[loy_seq]
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

    customer_id = int(sess.customer.get("customerId") or 0)

    # Points redeemed only if we actually suggested a redemption
    dollars_off = float(sess.last_points_recommended or 0.0)
    points_redeemed = int(round(dollars_off * POINTS_PER_DOLLAR)) if dollars_off > 0 else 0

    promo_discount = float(sess.promo_discount_total or 0.0)
    promo_applied = bool(sess.promo_applied_flag)

    log(
        f"🏁 EPS Finalize: customer={customer_id} subtotal=${eligible_subtotal:.2f} "
        f"txn={txn_id} loy={loy_seq} promoApplied={promo_applied} promoDiscount=${promo_discount:.2f}"
    )

    # If you want promos to disable earning entirely:
    if DISABLE_EARNING_WHEN_PROMO and promo_applied:
        finalize_transaction_backend(
            customer_id=customer_id,
            eligible_subtotal=eligible_subtotal,
            transaction_id=txn_id,
            line_items=final_items,
            promotions=sess.promotions_applied,
            promotion_discount=promo_discount,
            points_redeemed=0,
        )
        if loy_seq in SESSIONS:
            del SESSIONS[loy_seq]
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

    # Finalize points earned + promo accounting + points redeemed (if any)
    finalize_transaction_backend(
        customer_id=customer_id,
        eligible_subtotal=eligible_subtotal,
        transaction_id=txn_id,
        line_items=final_items,
        promotions=sess.promotions_applied,
        promotion_discount=promo_discount,
        points_redeemed=points_redeemed,
    )

    # Punch earning and reward redeem logic:
    # - If promos were applied and stacking policy disabled loyalty discounts, punch_rewards_sent will be empty
    # - We still record punches (earning), but only adjust for free units if a punch free reward was applied.
    applied_punch_rewards: List[PunchRewardSent] = []
    for pr in sess.punch_rewards_sent:
        if finalize_has_reward_anywhere(root, pr.reward_id):
            applied_punch_rewards.append(pr)

    free_adjustments: List[FreeUnitAdjustment] = []
    for pr in applied_punch_rewards:
        if pr.reward_type == "free_item" and pr.free_line_no > 0 and pr.free_upc:
            free_adjustments.append(
                FreeUnitAdjustment(
                    punch_card_id=pr.punch_card_id,
                    punch_card_name=pr.punch_card_name,
                    reward_id=pr.reward_id,
                    line_no=pr.free_line_no,
                    upc=pr.free_upc,
                    free_units=pr.free_units or 1,
                )
            )

    if free_adjustments:
        free_adjustments = remap_free_adjustments_to_finalize(final_items, free_adjustments)

    record_items = final_items
    if free_adjustments:
        log("✅ Applying FREE-UNIT adjustments before /record-purchase:")
        for a in free_adjustments:
            log(f" - 1 free unit on line {a.line_no} UPC {a.upc} for {a.punch_card_name}")
        record_items = adjust_items_for_record_purchase(final_items, free_adjustments)

    punch_result = record_punches(customer_id, record_items, txn_id)
    punches_recorded = punch_result.get("punchesRecorded", []) if isinstance(punch_result, dict) else []
    if punches_recorded:
        log(" 🎯 PUNCHES RECORDED:")
        for p in punches_recorded:
            log(
                f" • {p.get('punchCardName')}: +{p.get('punchesAdded')} → "
                f"{p.get('currentPunches')}/{p.get('punchesRequired')}"
            )

    # Redeem punch rewards that were applied
    redeemed_ids = set()
    for pr in applied_punch_rewards:
        if pr.punch_card_id and pr.punch_card_id not in redeemed_ids:
            rr = redeem_punch_reward(customer_id, pr.punch_card_id, txn_id)
            if isinstance(rr, dict) and rr.get("success"):
                log(f" 🎁 Redeemed punch reward: {pr.punch_card_name} (id={pr.punch_card_id})")
            redeemed_ids.add(pr.punch_card_id)

    # Clear session
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
        try:
            conn.close()
        except Exception:
            pass
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
    log("🐦 BIRDIES EPS AGENT [PROMOS + LOYALTY HYBRID v5]")
    log("=" * 60)
    log(f" Store: {PDI_STORE_NUMBER}")
    log(f" Backend: {BACKEND_URL}")
    log(f" Listening on: {HOST}:{PORT}")
    log(f" Policy: promo_first_disable_loyalty_discounts={PROMO_FIRST_DISABLE_LOYALTY_DISCOUNTS}, "
        f"disable_earning_when_promo={DISABLE_EARNING_WHEN_PROMO}")
    log("=" * 60)

    threading.Thread(target=heartbeat_loop, daemon=True).start()
    log("✓ Heartbeat thread started")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(64)

    log(f"✓ TCP server listening on {HOST}:{PORT}")
    log("Waiting for Verifone Commander/EPS connections...")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
