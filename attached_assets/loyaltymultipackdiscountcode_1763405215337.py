#!/usr/bin/env python3
"""
Gilbarco Passport Loyalty Demo Server – 2-for-$1.00 Item Promo (FIXED)
---------------------------------------------------------------------
• Binds to 10.96.10.175:9000
• Implements POSLOYALTY 28-byte header + XML framing
• Prints every inbound/outbound XML in the terminal
• Keeps loyalty ONLINE (OnlineStatus)
• Applies a "2 for $1.00" promo per-UPC (line-level newPrice=$0.50) when any LoyaltyID is entered
  - Pairs are counted per UPC across the whole cart (even if split across lines)
  - Only complete pairs are discounted (e.g., qty 3 → 2 discounted; 1 remains normal)
  - Best-price floor: only lowers price to $0.50 if current per-unit > $0.50 (never raises)
• Handles: OnlineStatus, GetRewards, FinalizeRewards, CancelTransaction,
  GetCustomerMessaging, Begin/EndCustomer (info only), EndPeriod (ack so POS stops retrying)
"""

import socket
import threading
import datetime
import binascii
import struct
import uuid
import xml.etree.ElementTree as ET
from xml.dom import minidom

# =========================
# Configuration
# =========================
HOST = "10.96.10.175"         # your PC's Passport NIC IP
PORT = 9000                   # Loyalty port configured on Passport MWS
EXPECTED_POS_IP = "10.5.50.2" # Optional safety: reject any other source. Set to None to allow all.

VENDOR_NAME = "DemoLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

# --- 2-for-$1.00 promo config (per UPC) ---
N_REQUIRED         = 2
BUNDLE_PRICE       = 1.00
PER_UNIT_NEW_PRICE = round(BUNDLE_PRICE / N_REQUIRED, 4)   # $0.50
PROMO_ID           = "DEMO-2FOR1"                          # LoyaltyRewardID
RECEIPT_SHORT      = "2FOR1"                               # <= 8 chars
RECEIPT_LONG       = "2 for $1"                            # <= 24 chars
# Optional cap per UPC per txn (None means unlimited bundles per UPC)
LIMIT_DISCOUNTED_QTY_PER_UPC = None  # e.g., 4 caps at two bundles per UPC

# POSLOYALTY framing
SIGNATURE = b"POSLOYALTY\x00\x00"
ACTION_MESSAGE   = 1
ACTION_HEARTBEAT = 2

# =========================
# Utilities
# =========================
def log(msg: str):
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

def send_xml(conn: socket.socket, xml_str: str, action: int = ACTION_MESSAGE):
    xml_bytes = xml_str.encode("utf-8")
    hdr = pack_header(xml_bytes, action)
    conn.sendall(hdr + xml_bytes)
    # pretty print outbound
    try:
        pretty = minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        pretty = xml_str
    log("→ Sent XML:\n" + pretty)

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
    # pretty print inbound
    try:
        pretty = minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        pretty = raw
    log("← Recv XML:\n" + pretty)
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
# Helpers for 2-for-$1.00
# =========================
def _f(num_str, default=0.0):
    try:
        return float(num_str)
    except Exception:
        return default

def parse_item_lines(root: ET.Element):
    """
    Returns list of dicts:
      {line_no:int, upc:str, qty:int,
       unit_price:float, actual_price:float, regular_price:float}
    Counts ONLY non-void TransactionLine with discountable="yes" ItemLine.
    Uses correct XML paths for LineNumber and POSCode.
    """
    lines = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        if (tline.get("status") or "").strip().lower() != "normal":
            continue  # ignore void/returned/etc.

        il = tline.find("./ItemLine")
        if il is None:
            continue

        if (il.get("discountable") or "").strip().lower() != "yes":
            continue  # respect POS flag

        # Line number is under TransactionLine
        try:
            line_no = int(tline.findtext("./LineNumber", "0"))
        except Exception:
            line_no = 0

        upc = (il.findtext("./ItemCode/POSCode") or "").strip()
        if not upc:
            continue

        qty_txt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
        try:
            qty = int(float(qty_txt))
        except Exception:
            qty = 1

        unit_price    = _f(il.findtext("UnitPrice", "0"))
        actual_price  = _f(il.findtext("ActualSalesPrice", "0"))
        regular_price = _f(il.findtext("RegularSellPrice", "0"))

        if qty > 0:
            lines.append({
                "line_no": line_no,
                "upc": upc,
                "qty": qty,
                "unit_price": unit_price,
                "actual_price": actual_price,
                "regular_price": regular_price,
            })
    return lines

def current_unit_price(l):
    """
    Resolve the effective per-unit price reported by the POS for comparison.
    Order: UnitPrice -> ActualSalesPrice -> RegularSellPrice.
    """
    for key in ("unit_price", "actual_price", "regular_price"):
        v = l.get(key, 0.0)
        try:
            v = float(v)
        except Exception:
            v = 0.0
        if v and v > 0:
            return v
    return 0.0

def build_2for1_rewards_xml(root: ET.Element):
    """
    For each UPC, if total qty >= 2, discount pairs to $0.50 each (newPrice).
    Distribute discounted units across lines with that UPC.
    Best-price floor: only emit newPrice if current per-unit > $0.50.
    Returns list of <AddReward> XML strings.
    """
    lines = parse_item_lines(root)
    log(f"Eligible lines -> {lines}")  # DEBUG

    if not lines:
        return []

    # Group by UPC
    upc_to_lines = {}
    for l in lines:
        upc_to_lines.setdefault(l["upc"], []).append(l)

    add_rewards = []

    for upc, lnlist in upc_to_lines.items():
        total_qty = sum(l["qty"] for l in lnlist)
        if total_qty < N_REQUIRED:
            continue

        # Complete pairs only
        discounted_units = (total_qty // N_REQUIRED) * N_REQUIRED

        # Optional per-UPC cap
        if LIMIT_DISCOUNTED_QTY_PER_UPC is not None:
            discounted_units = min(discounted_units, int(LIMIT_DISCOUNTED_QTY_PER_UPC))

        if discounted_units <= 0:
            continue

        # Distribute across lines (scan order). To prefer cheapest-first, sort by unit price:
        # lnlist = sorted(lnlist, key=lambda d: current_unit_price(d))

        remaining = discounted_units
        for l in lnlist:
            if remaining <= 0:
                break

            unit_now = current_unit_price(l)

            # Best-price floor: never raise price; only lower to $0.50 if current > $0.50
            if unit_now <= PER_UNIT_NEW_PRICE:
                continue

            take = min(l["qty"], remaining)
            if take <= 0:
                continue

            add_rewards.append(f"""
    <AddReward>
      <LoyaltyRewardID>{PROMO_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>{l["line_no"]}</RewardTargetLineNumber>
      <RewardDiscountMethod>newPrice</RewardDiscountMethod>
      <RewardValue>{PER_UNIT_NEW_PRICE:.4f}</RewardValue>
      <RewardLimit type="quantity">{int(take)}</RewardLimit>
      <RewardReceiptDescShort>{RECEIPT_SHORT}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{RECEIPT_LONG}</RewardReceiptDescLong>
    </AddReward>""".rstrip())

            remaining -= take

    return add_rewards

# =========================
# Response Builders
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
    pos_seq, loy_seq = get_req_ids(root)
    loyalty_id = root.findtext(".//LoyaltyID") or ""
    masked = (loyalty_id[-4:].rjust(10, "*")) if loyalty_id else ""

    add_xmls = build_2for1_rewards_xml(root)

    rewards_block = f"<RewardActions>\n    {''.join(add_xmls)}\n  </RewardActions>" if add_xmls else "<RewardActions/>"

    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>
  {rewards_block}
</GetRewardsResponse>""".strip()

def build_finalize_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""
<FinalizeRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <ReceiptData>
      <ReceiptLine>2 FOR $1 APPLIED WHERE ELIGIBLE</ReceiptLine>
    </ReceiptData>
  </CustomerMessageData>
</FinalizeRewardsResponse>""".strip()

def build_cancel_txn_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"<CancelTransactionResponse>{resp_header(pos_seq, loy_seq)}</CancelTransactionResponse>"

def build_get_customer_msg_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)
    return f"""
<GetCustomerMessagingResponse>
  {resp_header(pos_seq, loy_seq)}
  <CustomerMessageData>
    <DisplayData>
      <DisplayCommand device="POS-Cashier" sequence="WhenReceived">
        <DisplayLine>2 for $1.00 promo active</DisplayLine>
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
# Connection Handler
# =========================
def handle_client(conn: socket.socket, addr):
    peer = f"{addr[0]}:{addr[1]}"
    log(f"Connection from {peer}")

    # Optional safety: only accept the Passport IP you observed
    if EXPECTED_POS_IP and addr[0] != EXPECTED_POS_IP:
        log(f"Rejecting unexpected host {addr[0]}")
        try: conn.close()
        except: pass
        return

    try:
        conn.settimeout(180)
        while True:
            hdr = recv_exact(conn, 28)
            if not hdr:
                log(f"{peer} closed connection.")
                break

            try:
                action, data_len, chk_data = parse_header(hdr)
            except Exception as e:
                log(f"{peer} bad header: {e}")
                break

            if action == ACTION_HEARTBEAT:
                # Consume optional heartbeat payload if present
                if data_len:
                    _ = recv_exact(conn, data_len)
                log(f"{peer} heartbeat")
                continue

            data = recv_exact(conn, data_len)
            if len(data) != data_len or crc32(data) != chk_data:
                log(f"{peer} payload CRC/length mismatch")
                break

            try:
                root, _raw = parse_xml(data)
            except Exception as e:
                log(f"{peer} XML parse error: {e}")
                break

            tag = root.tag.strip()

            # ---- Message routing ----
            if tag == "GetLoyaltyOnlineStatusRequest":
                send_xml(conn, build_online_status_response(root))

            elif tag == "GetRewardsRequest":
                # Any LoyaltyID is treated as valid; apply 2-for-$1 where eligible
                send_xml(conn, build_get_rewards_response(root))

            elif tag == "FinalizeRewardsRequest":
                send_xml(conn, build_finalize_response(root))

            elif tag == "CancelTransactionRequest":
                send_xml(conn, build_cancel_txn_response(root))

            elif tag == "GetCustomerMessagingRequest":
                send_xml(conn, build_get_customer_msg_response(root))

            elif tag == "EndPeriodRequest":
                # Acknowledge so POS stops resending
                send_xml(conn, build_end_period_response(root))

            elif tag in ("BeginCustomerRequest", "EndCustomerRequest", "CancelRedemptionRequest"):
                # Informational only — no response required
                log(f"{peer} {tag} received (no response required).")

            else:
                log(f"{peer} Unhandled message type: {tag} (no response sent).")

    except socket.timeout:
        log(f"{peer} timed out.")
    except Exception as e:
        log(f"{peer} error: {e}")
    finally:
        try:
            conn.close()
        except:
            pass
        log(f"Connection closed: {peer}")

# =========================
# Server
# =========================
def serve():
    log(f"Starting Loyalty server on {HOST}:{PORT}")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(64)
    try:
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        log("Shutting down.")
    finally:
        s.close()

if __name__ == "__main__":
    serve()
