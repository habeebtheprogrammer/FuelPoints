#!/usr/bin/env python3
"""
Verifone EPS Loyalty Host - HYBRID Implementation
Combines:
  - Lanhampunch's line-targeted discount (avoids tax on free items)
  - Highbridgepunch's reliable counting logic (always splits items correctly)

Key fixes:
  1. RewardLimit uses standard EPS format (no type="quantity" attribute)
  2. Finalize ALWAYS applies item splitting (no finalize_has_reward() check)
  3. Properly tracks free items and adjusts record-purchase payload
"""

import socket
import struct
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import os
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================
# Configuration
# =========================

PDI_STORE_NUMBER = "0300"
TCP_PORT = 5015
EXPECTED_EPS_IP = ""  # Leave empty to accept from any IP

BACKEND_URL = "https://salmanloyalty.replit.app"

POINTS_PER_DOLLAR = 10000  # 10,000 pts = $1
REQUEST_TIMEOUT = 8
SESSION_TTL = 300

REWARD_ID = "BIRDIES-POINTS"
PUNCH_REWARD_ID = "BIRDIES-PUNCH"
RECEIPT_SHORT = "BIRDIES"
RECEIPT_LONG = "Birdies Loyalty Rewards"

NS_DECLS = 'xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16" xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01" xmlns:ns4="http://www.pcats.org/schema/core/v01"'

# =========================
# HTTP Session with retry
# =========================

SESSION_HTTP = requests.Session()
retry_strategy = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
SESSION_HTTP.mount("http://", adapter)
SESSION_HTTP.mount("https://", adapter)

# =========================
# Logging
# =========================

LOG_LOCK = threading.Lock()

def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_LOCK:
        print(f"[{ts}] {msg}", flush=True)

# =========================
# Data Classes
# =========================

@dataclass
class FreePunchAdjustment:
    """Tracks a free item reward that was applied, for adjusting punch counts."""
    punch_card_id: int
    punch_card_name: str
    line_no: int
    upc: str
    free_units: int = 1

@dataclass
class LoyaltySession:
    customer: Dict[str, Any] = field(default_factory=dict)
    basket_items: List[Dict[str, Any]] = field(default_factory=list)
    free_punch_adjustments: List[FreePunchAdjustment] = field(default_factory=list)
    promotions_applied: List[Dict[str, Any]] = field(default_factory=list)
    last_points_recommended: float = 0.0
    last_seen_at: float = field(default_factory=time.time)

SESSIONS: Dict[str, LoyaltySession] = {}
SESSIONS_LOCK = threading.Lock()

def cleanup_sessions():
    now = time.time()
    with SESSIONS_LOCK:
        expired = [k for k, v in SESSIONS.items() if now - v.last_seen_at > SESSION_TTL]
        for k in expired:
            del SESSIONS[k]
            log(f"[Session] Expired session {k}")

# =========================
# XML Parsing Helpers
# =========================

def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag

def get_req_ids(root: ET.Element) -> Tuple[str, str]:
    pos_seq = ""
    loy_seq = ""
    for el in root.iter():
        tag = strip_ns(el.tag)
        if tag == "POSSequenceID":
            pos_seq = (el.text or "").strip()
        elif tag == "LoyaltySequenceID":
            loy_seq = (el.text or "").strip()
    return pos_seq, loy_seq

def get_iface_ver(root: ET.Element) -> str:
    for el in root.iter():
        if strip_ns(el.tag) == "POSLoyaltyInterfaceVersion":
            return (el.text or "").strip()
    return "1.0"

def get_pos_transaction_id(root: ET.Element) -> str:
    for el in root.iter():
        tag = strip_ns(el.tag)
        if tag == "POSTransactionID":
            return (el.text or "").strip()
        if tag == "TransactionID":
            return (el.text or "").strip()
    return ""

def get_loyalty_account(root: ET.Element) -> str:
    for el in root.iter():
        tag = strip_ns(el.tag)
        if tag in ("LoyaltyAccountNumber", "AccountNumber"):
            return (el.text or "").strip()
    return ""

def resp_header(pos_seq: str, loy_seq: str, iface_ver: str = "1.0") -> str:
    return f"""<ns3:ResponseHeader>
    <ns3:POSLoyaltyInterfaceVersion>{iface_ver}</ns3:POSLoyaltyInterfaceVersion>
    <ns3:POSSequenceID>{pos_seq}</ns3:POSSequenceID>
    <ns3:LoyaltySequenceID>{loy_seq}</ns3:LoyaltySequenceID>
    <ns4:Result><Success/></ns4:Result>
  </ns3:ResponseHeader>"""

# =========================
# Line Item Extraction
# =========================

def extract_line_items(root: ET.Element) -> List[Dict[str, Any]]:
    items = []
    for tline in root.iter():
        if strip_ns(tline.tag) != "TransactionLine":
            continue
        line_no = 0
        for ln_el in tline.iter():
            if strip_ns(ln_el.tag) == "LineNumber":
                try:
                    line_no = int(ln_el.text or 0)
                except ValueError:
                    pass
                break

        for child in tline:
            child_tag = strip_ns(child.tag)
            if child_tag in ("ItemLine", "MerchandiseCodeLine"):
                item = parse_item_line(child, line_no, is_item=True)
                if item:
                    items.append(item)
            elif child_tag == "FuelLine":
                item = parse_fuel_line(child, line_no)
                if item:
                    items.append(item)
    return items

def parse_item_line(el: ET.Element, line_no: int, is_item: bool = True) -> Optional[Dict[str, Any]]:
    upc = ""
    desc = ""
    qty = 1.0
    amt = 0.0
    unit_price = 0.0
    psc = ""

    for c in el.iter():
        tag = strip_ns(c.tag)
        txt = (c.text or "").strip()
        if tag == "POSCodeModifier":
            upc = txt
        elif tag == "POSCode":
            upc = txt
        elif tag == "Description":
            desc = txt
        elif tag == "SalesQuantity":
            try:
                qty = float(txt)
            except ValueError:
                pass
        elif tag == "SalesAmount":
            try:
                amt = float(txt)
            except ValueError:
                pass
        elif tag in ("ActualSalesPrice", "RegularSellPrice"):
            try:
                unit_price = float(txt)
            except ValueError:
                pass
        elif tag == "PaymentSystemsProductCode":
            psc = txt

    if not upc and psc:
        upc = psc

    if qty > 0 and unit_price <= 0 and amt > 0:
        unit_price = round(amt / qty, 2)

    return {
        "line_no": line_no,
        "upc": upc,
        "description": desc,
        "quantity": qty,
        "amount": amt,
        "price": unit_price,
        "psc": psc,
        "is_item_line": is_item,
    }

def parse_fuel_line(el: ET.Element, line_no: int) -> Optional[Dict[str, Any]]:
    grade = ""
    volume = 0.0
    amt = 0.0
    ppu = 0.0

    for c in el.iter():
        tag = strip_ns(c.tag)
        txt = (c.text or "").strip()
        if tag == "GradeDescription":
            grade = txt
        elif tag == "SalesVolume":
            try:
                volume = float(txt)
            except ValueError:
                pass
        elif tag == "SalesAmount":
            try:
                amt = float(txt)
            except ValueError:
                pass
        elif tag == "PricePerUnit":
            try:
                ppu = float(txt)
            except ValueError:
                pass

    return {
        "line_no": line_no,
        "upc": "",
        "description": f"FUEL: {grade}",
        "quantity": volume,
        "amount": amt,
        "price": ppu,
        "psc": "400",
        "is_item_line": False,
        "is_fuel": True,
    }

def get_unit_price(item: Dict[str, Any]) -> float:
    price = float(item.get("price", 0) or 0)
    if price > 0:
        return price
    amt = float(item.get("amount", 0) or 0)
    qty = float(item.get("quantity", 1) or 1)
    if qty > 0 and amt > 0:
        return round(amt / qty, 2)
    return 0.0

# =========================
# Backend API Calls
# =========================

def send_backend_heartbeat(pos_ip: str):
    try:
        SESSION_HTTP.post(
            f"{BACKEND_URL}/api/pos/heartbeat",
            json={"pdiStoreNumber": PDI_STORE_NUMBER, "posIp": pos_ip, "posType": "verifone"},
            timeout=5,
        )
    except Exception:
        pass

def lookup_customer(account: str) -> Dict[str, Any]:
    if not account:
        return {}
    phone_clean = account.lstrip("0").replace("-", "").replace(" ", "")
    if len(phone_clean) == 10:
        phone_clean = phone_clean
    elif len(phone_clean) > 10:
        phone_clean = phone_clean[-10:]
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/pos/customer-lookup",
            json={"phone": phone_clean, "loyaltyId": account, "pdiStoreNumber": PDI_STORE_NUMBER},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"⚠ Customer lookup error: {e}")
    return {}

def evaluate_promotions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/pos/evaluate-promotions",
            json={"pdiStoreNumber": PDI_STORE_NUMBER, "lineItems": items},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json().get("promotions", [])
    except Exception:
        pass
    return []

def evaluate_punch_cards(customer_id: int, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/punch-cards/evaluate",
            json={"customerId": customer_id, "lineItems": items, "pdiStoreNumber": PDI_STORE_NUMBER},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"⚠ Punch card evaluation error: {e}")
    return {}

def record_punches(customer_id: int, items: List[Dict[str, Any]], txn_id: str) -> Dict[str, Any]:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/punch-cards/record-purchase",
            json={
                "customerId": customer_id,
                "lineItems": items,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "transactionId": txn_id,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"⚠ Record punches error: {e}")
    return {}

def redeem_punch_reward(customer_id: int, punch_card_id: int, txn_id: str) -> Dict[str, Any]:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/punch-cards/redeem",
            json={
                "customerId": customer_id,
                "punchCardId": punch_card_id,
                "pdiStoreNumber": PDI_STORE_NUMBER,
                "transactionId": txn_id,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"⚠ Redeem punch error: {e}")
    return {}

def calculate_redemption(customer_id: int, eligible_subtotal: float, line_items: list) -> float:
    try:
        r = SESSION_HTTP.post(
            f"{BACKEND_URL}/api/pos/calculate-redemption",
            json={"customerId": customer_id, "eligibleSubtotal": eligible_subtotal, "lineItems": line_items},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return float(r.json().get("recommendedRedemption", 0) or 0)
    except Exception:
        pass
    return 0.0

# =========================
# Free Item Selection (for punch card rewards)
# =========================

def choose_free_item_line(items: List[Dict[str, Any]], eligible_upcs: Optional[set] = None) -> Optional[Dict[str, Any]]:
    """
    Choose the cheapest eligible item line for a free item reward.
    If eligible_upcs is provided, only consider items with matching UPCs.
    Excludes fuel (psc=400) and non-item lines.
    """
    candidates = []
    for it in items:
        if not it.get("is_item_line"):
            continue
        if it.get("is_fuel"):
            continue
        psc = str(it.get("psc", "")).strip()
        if psc in ("400", "950"):  # fuel or cash categories
            continue
        upc = (it.get("upc") or "").strip()
        if not upc:
            continue
        if eligible_upcs and upc not in eligible_upcs:
            continue
        unit_price = get_unit_price(it)
        if unit_price <= 0:
            continue
        candidates.append(it)
    
    if not candidates:
        return None
    
    # Return cheapest
    return min(candidates, key=lambda x: get_unit_price(x))

# =========================
# Punch Counting Adjustment (from Highbridgepunch)
# =========================

def adjust_items_for_record_purchase(items: list, adjustments: List[FreePunchAdjustment]) -> list:
    """
    Apply free-unit adjustments by splitting targeted lines into paid + free pseudo-lines.
    Free pseudo-line has amount=0 so backend skips counting that unit as a punch.
    
    Example: Buy 4 coffees, get 1 free (3 required)
    Input: line 5, qty=4, amount=$11.96
    Output: 
      - paid: line 5, qty=3, amount=$8.97 (counts as 3 punches)
      - free: line 5, qty=1, amount=$0.00 (doesn't count)
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
    with SESSIONS_LOCK:
        if loy_seq in SESSIONS:
            del SESSIONS[loy_seq]
            log(f"[Session] CancelTransaction: removed session {loy_seq}")
    return f"""<ns3:CancelTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:CancelTransactionResponse>"""

def build_reverse_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    return f"""<ns3:ReverseTransactionResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:ReverseTransactionResponse>"""

def build_rewards_response(root: ET.Element) -> str:
    """
    HYBRID: Uses line-targeted discount (lanhampunch style) for tax-free rewards
    but tracks adjustments (highbridgepunch style) for reliable punch counting.
    """
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    account = get_loyalty_account(root)

    customer = lookup_customer(account)
    if not customer or not customer.get("customerId"):
        log(f"⚠ Customer not found for account: {account}")
        return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="no">Customer not found</ns3:LoyaltyIDValidFlag>
</ns3:GetRewardsResponse>"""

    customer_id = int(customer.get("customerId"))
    first_name = customer.get("firstName", "")
    last_name = customer.get("lastName", "")
    phone = customer.get("phone", "")
    points = int(customer.get("currentPoints", 0) or 0)

    items = extract_line_items(root)
    log(f"📦 GetRewards: customer={customer_id} ({first_name} {last_name}) items={len(items)} points={points}")

    # Create/update session
    with SESSIONS_LOCK:
        sess = SESSIONS.get(loy_seq, LoyaltySession())
        sess.customer = customer
        sess.basket_items = items
        sess.free_punch_adjustments = []
        sess.promotions_applied = []
        sess.last_points_recommended = 0.0
        sess.last_seen_at = time.time()
        SESSIONS[loy_seq] = sess

    add_rewards: List[str] = []

    # Evaluate punch cards
    punch_data = evaluate_punch_cards(customer_id, items)
    punch_cards = punch_data.get("punchCards", [])

    for pc in punch_cards:
        punch_card_id = int(pc.get("punchCardId", 0) or 0)
        punch_card_name = pc.get("punchCardName", "Punch Card")
        reward_type = (pc.get("rewardType") or "").lower()
        reward_value = pc.get("rewardValue")

        current = int(pc.get("currentPunches", 0) or 0)
        basket = int(pc.get("punchesFromBasket", 0) or 0)
        required = int(pc.get("punchesRequired", 10) or 10)

        # HIGHBRIDGEPUNCH LOGIC: Determine if reward should trigger
        punches_needed = max(0, required - current)
        already_full = current >= required
        buying_extra = basket > punches_needed
        should_trigger = already_full or buying_extra

        if not should_trigger:
            log(f"  ⏳ {punch_card_name}: {current}+{basket}/{required} - not ready yet")
            continue

        log(f"  🎁 {punch_card_name}: {current}+{basket}/{required} - REWARD TRIGGERED! ({reward_type})")

        # Dollar/percent off rewards: ticket-level discount
        if reward_type in ("dollar_off", "amount_off"):
            try:
                amt = float(reward_value or 0)
                if amt > 0:
                    add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{punch_card_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name}</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())
                    # Track for redemption (no item splitting needed for dollar off)
                    sess.free_punch_adjustments.append(
                        FreePunchAdjustment(
                            punch_card_id=punch_card_id,
                            punch_card_name=punch_card_name,
                            line_no=0,
                            upc="",
                            free_units=0,  # No units to split
                        )
                    )
            except Exception:
                pass
            continue

        if reward_type == "percent_off":
            try:
                pct = float(reward_value or 0)
                subtotal = sum(float(it.get("amount", 0) or 0) for it in items)
                amt = max(0.0, subtotal * (pct / 100.0))
                if amt > 0:
                    add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{punch_card_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>0</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{amt:.2f}</ns3:RewardValue>
      <ns3:RewardReceiptDescShort>PUNCH</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name} {pct:.0f}%</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())
                    sess.free_punch_adjustments.append(
                        FreePunchAdjustment(
                            punch_card_id=punch_card_id,
                            punch_card_name=punch_card_name,
                            line_no=0,
                            upc="",
                            free_units=0,
                        )
                    )
            except Exception:
                pass
            continue

        # FREE ITEM reward: LINE-TARGETED discount (lanhampunch style, but fixed)
        if reward_type == "free_item":
            chosen = choose_free_item_line(items)
            if not chosen:
                log(f"  ⚠ No eligible item found for free item reward")
                continue

            line_no = int(chosen.get("line_no", 0) or 0)
            unit_price = get_unit_price(chosen)
            upc = (chosen.get("upc") or "").strip()

            if line_no <= 0 or unit_price <= 0:
                log(f"  ⚠ Invalid line/price for free item: line={line_no}, price={unit_price}")
                continue

            log(f"    → Free item on line {line_no}, UPC {upc}, price ${unit_price:.2f}")

            # LINE-TARGETED discount (fixes: removed type="quantity" attribute)
            add_rewards.append(f"""
    <ns3:AddReward>
      <ns3:LoyaltyRewardID>{PUNCH_REWARD_ID}-{punch_card_id}</ns3:LoyaltyRewardID>
      <ns3:InstantRewardFlag value="yes"/>
      <ns3:RewardTargetLineNumber>{line_no}</ns3:RewardTargetLineNumber>
      <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
      <ns3:RewardValue>{unit_price:.2f}</ns3:RewardValue>
      <ns3:RewardLimit>1</ns3:RewardLimit>
      <ns3:RewardReceiptDescShort>FREE</ns3:RewardReceiptDescShort>
      <ns3:RewardReceiptDescLong>{punch_card_name} FREE ITEM</ns3:RewardReceiptDescLong>
    </ns3:AddReward>""".rstrip())

            # Track adjustment for punch counting (highbridgepunch style)
            sess.free_punch_adjustments.append(
                FreePunchAdjustment(
                    punch_card_id=punch_card_id,
                    punch_card_name=punch_card_name,
                    line_no=line_no,
                    upc=upc,
                    free_units=1,
                )
            )

    # Evaluate regular promotions
    sess.promotions_applied = evaluate_promotions(items)

    # Points redemption (optional, ticket-level)
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

    rewards: List[str] = list(add_rewards)
    if points_reward_xml:
        rewards.append(points_reward_xml)

    if rewards:
        reward_actions = "<ns3:RewardActions>\n" + "\n".join(rewards) + "\n</ns3:RewardActions>"
    else:
        reward_actions = "<ns3:RewardActions/>"

    masked = (phone[-4:].rjust(10, "*")) if phone else "****"
    return f"""<ns3:GetRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
  <ns3:LoyaltyIDValidFlag value="yes">{first_name} {last_name}</ns3:LoyaltyIDValidFlag>
  <ns3:LoyaltyMemberID>{masked}</ns3:LoyaltyMemberID>
  <ns3:PointsBalance>{points}</ns3:PointsBalance>
  {reward_actions}
</ns3:GetRewardsResponse>"""


def build_finalize_response(root: ET.Element) -> str:
    """
    HYBRID: Always applies item splitting (highbridgepunch style).
    No finalize_has_reward() check - we trust that if we sent the reward, POS applied it.
    """
    cleanup_sessions()

    pos_seq, loy_seq = get_req_ids(root)
    iface_ver = get_iface_ver(root)
    txn_id = get_pos_transaction_id(root) or f"TXN-{uuid.uuid4().hex[:8].upper()}"

    with SESSIONS_LOCK:
        sess = SESSIONS.get(loy_seq)

    if not sess:
        log("⚠ No session for finalize; responding success but skipping backend calls")
        return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

    sess.last_seen_at = time.time()

    final_items = extract_line_items(root)
    subtotal = sum(float(it.get("amount", 0) or 0) for it in final_items)

    customer = sess.customer
    customer_id = int(customer.get("customerId") or 0)

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
        r = SESSION_HTTP.post(f"{BACKEND_URL}/api/pos/finalize-transaction", json=finalize_payload, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            result = r.json()
            log(f"  ✓ Points: earned {result.get('pointsEarned', 0)}, balance {result.get('newBalance', 0)}")
        else:
            log(f"  ⚠ finalize-transaction failed: {r.status_code}")
    except Exception as e:
        log(f"  ⚠ finalize-transaction error: {e}")

    # PUNCH COUNTING: Adjust items to split paid/free (ALWAYS, no finalize_has_reward check)
    record_items = final_items
    free_item_adjustments = [a for a in sess.free_punch_adjustments if a.free_units > 0]
    
    if free_item_adjustments:
        existing_lines = {int(it.get("line_no", 0) or 0) for it in final_items}
        applicable = [a for a in free_item_adjustments if a.line_no in existing_lines]
        
        if applicable:
            log("✅ Applying FREE-UNIT adjustments before /record-purchase (HYBRID):")
            for a in applicable:
                log(f"   - line {a.line_no}: 1 unit FREE for {a.punch_card_name}")
            record_items = adjust_items_for_record_purchase(final_items, applicable)

    # Record punches (using adjusted payload - only paid items count)
    punch_result = record_punches(customer_id, record_items, txn_id)
    punches_recorded = punch_result.get("punchesRecorded", [])
    if punches_recorded:
        log("  🎯 PUNCHES RECORDED:")
        for p in punches_recorded:
            log(f"     • {p.get('punchCardName')}: +{p.get('punchesAdded')} → {p.get('currentPunches')}/{p.get('punchesRequired')}")

    # Redeem punch card rewards that were applied
    redeemed = set()
    for a in sess.free_punch_adjustments:
        if a.punch_card_id and a.punch_card_id not in redeemed:
            redeem_result = redeem_punch_reward(customer_id, a.punch_card_id, txn_id)
            if redeem_result.get("success"):
                log(f"  🎁 Redeemed punch reward: {a.punch_card_name} (id={a.punch_card_id})")
            redeemed.add(a.punch_card_id)

    # Clean up session
    with SESSIONS_LOCK:
        if loy_seq in SESSIONS:
            del SESSIONS[loy_seq]

    return f"""<ns3:FinalizeRewardsResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:FinalizeRewardsResponse>"""

# =========================
# TCP Framing
# =========================

def recv_frame(sock: socket.socket) -> bytes:
    header = b""
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            return b""
        header += chunk
    length = struct.unpack(">I", header)[0]
    if length <= 0 or length > 1_000_000:
        return b""
    data = b""
    while len(data) < length:
        chunk = sock.recv(min(65536, length - len(data)))
        if not chunk:
            return b""
        data += chunk
    return data

def send_frame(sock: socket.socket, data: bytes):
    header = struct.pack(">I", len(data))
    sock.sendall(header + data)

def parse_xml(data: bytes) -> Tuple[ET.Element, str]:
    raw = data.decode("utf-8", errors="replace")
    root = ET.fromstring(raw)
    return root, raw

# =========================
# Request Router
# =========================

def route_request(root: ET.Element) -> str:
    tag = strip_ns(root.tag)
    
    if tag == "GetLoyaltyOnlineStatusRequest":
        return build_online_status_response(root)
    elif tag == "GetRewardsRequest":
        return build_rewards_response(root)
    elif tag == "FinalizeRewardsRequest":
        return build_finalize_response(root)
    elif tag == "CancelTransactionRequest":
        return build_cancel_response(root)
    elif tag == "ReverseTransactionRequest":
        return build_reverse_response(root)
    elif tag == "EndPeriodRequest":
        return build_end_period_response(root)
    else:
        log(f"⚠ Unknown request type: {tag}")
        pos_seq, loy_seq = get_req_ids(root)
        iface_ver = get_iface_ver(root)
        return f"""<ns3:UnknownResponse {NS_DECLS}>
  {resp_header(pos_seq, loy_seq, iface_ver)}
</ns3:UnknownResponse>"""

# =========================
# TCP Server
# =========================

def handle_client(conn: socket.socket, addr):
    log(f"🔌 Connection from {addr}")

    if EXPECTED_EPS_IP and addr[0] != EXPECTED_EPS_IP:
        log(f"⚠ Rejecting connection from {addr[0]} (expected {EXPECTED_EPS_IP})")
        conn.close()
        return

    send_backend_heartbeat(addr[0])

    try:
        while True:
            xml_bytes = recv_frame(conn)
            if not xml_bytes:
                log(f"Connection closed by {addr}")
                break

            try:
                root, raw = parse_xml(xml_bytes)
            except Exception as e:
                log(f"⚠ XML parse error: {e}")
                continue

            tag = strip_ns(root.tag)
            log(f"📥 {tag} from {addr[0]}")

            response_xml = route_request(root)
            send_frame(conn, response_xml.encode("utf-8"))
            log(f"📤 {strip_ns(tag).replace('Request', 'Response')} sent")

    except Exception as e:
        log(f"⚠ Client handler error: {e}")
    finally:
        conn.close()

def main():
    log("=" * 60)
    log("Verifone EPS Loyalty Host - HYBRID Implementation")
    log("  Line-targeted discount (tax-free) + Reliable counting")
    log(f"  Backend: {BACKEND_URL}")
    log(f"  Store: {PDI_STORE_NUMBER}")
    log(f"  Port: {TCP_PORT}")
    log("=" * 60)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", TCP_PORT))
    server.listen(5)
    log(f"🚀 Listening on port {TCP_PORT}")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        log("Shutting down...")
    finally:
        server.close()

if __name__ == "__main__":
    main()
