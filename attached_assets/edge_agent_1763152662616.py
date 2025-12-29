#!/usr/bin/env python3
"""
Birdies Loyalty Edge Agent - Demo Clone
---------------------------------------
• Listens on 10.96.10.175:9000 and speaks Passport POSLOYALTY
• Sends heartbeats to backend (for monitoring)
• For ANY LoyaltyID, always sends the SAME $1 basket discount
  as the working DemoLoyalty server (DEMO-1OFF, instant, line 0)
• Backend lookup is best-effort and only affects messaging/points,
  NOT whether the $1 discount is sent.
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
HOST = "10.96.10.175"      # Edge NIC IP (Passport-facing)
PORT = 9000                # Loyalty port configured on Passport MWS
EXPECTED_POS_IP = "10.5.50.2"  # Restrict to Passport IP; set None to allow all

# Store / backend identity
PDI_STORE_NUMBER = "1340"
POS_ID = "24379"
POS_TYPE = "Passport"

BACKEND_URL = "https://salmanloyalty.replit.app"
HEARTBEAT_INTERVAL = 15  # seconds

# IMPORTANT: Match the working demo identity
VENDOR_NAME = "DemoLoyalty"
VENDOR_VER  = "1.0"
IFACE_VER   = "1.0"

# Reward config – EXACTLY like loyalty (1).py
DISCOUNT_VALUE = 1.00
REWARD_ID      = "DEMO-1OFF"
RECEIPT_SHORT  = "$1OFF"            # <= 8 chars
RECEIPT_LONG   = "Loyalty $1 Off"   # <= 24 chars

# HTTP session & timeout
SESSION = requests.Session()
REQUEST_TIMEOUT = (2, 2)  # (connect, read) seconds

# Session state (for points)
current_customer = None

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
    try:
        pretty = minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        pretty = xml_str
    log("→ Sent to POS:\n" + pretty)

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
    try:
        pretty = minidom.parseString(xml_bytes).toprettyxml()
    except Exception:
        pretty = raw
    log("← Received from POS:\n" + pretty)
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
# Heartbeat to backend
# =========================
def send_heartbeat(pos_ip: str = None):
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "posId": POS_ID,
            "posType": POS_TYPE,
            "posIpAddress": pos_ip or EXPECTED_POS_IP,
            "edgeIpAddress": HOST,
            "edgeVersion": "birdies-edge-demo-clone-1.0",
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
        send_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)

# =========================
# Helpers
# =========================
def extract_live_items(root: ET.Element):
    """Return only status='normal' item lines for logging/subtotal."""
    items = []
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        if (tline.get("status") or "").strip().lower() != "normal":
            continue
        il = tline.find("./ItemLine")
        if il is None:
            continue
        upc = (il.findtext("./ItemCode/POSCode") or "").strip()
        desc = (il.findtext("Description") or "").strip()
        qtxt = il.findtext("SalesQuantity", il.findtext("SellingUnits", "1"))
        atxt = il.findtext("SalesAmount")
        ap   = il.findtext("ActualSalesPrice", il.findtext("UnitPrice", "0"))
        try:
            qty = float(qtxt or 1.0)
        except:
            qty = 1.0
        try:
            amount = float(atxt) if atxt and atxt.strip() else float(ap or 0) * qty
        except:
            amount = 0.0
        items.append({
            "upc": upc,
            "description": desc,
            "quantity": qty,
            "amount": amount,
        })
    return items

def detect_loyalty_tender(root: ET.Element, reward_id: str) -> float:
    """Look for a TenderInfo with our LoyaltyRewardID; return dollars if found."""
    dollars = 0.0
    for tline in root.findall(".//TransactionDetailGroup/TransactionLine"):
        ti = tline.find("./TenderInfo")
        if ti is None:
            continue
        lrid = (ti.findtext("LoyaltyRewardID") or "").strip()
        if lrid == reward_id:
            try:
                dollars += float(ti.findtext("TenderAmount", "0") or 0)
            except:
                pass
    return round(dollars, 2)

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

    # Extract ID / phone
    loyalty_id = (root.findtext(".//LoyaltyID") or "").strip()
    phone      = (root.findtext(".//PhoneNumber") or "").strip()
    digits = "".join(ch for ch in loyalty_id if ch.isdigit())
    if len(digits) == 10:
        phone = digits
        loyalty_id = ""

    # Log items
    items = extract_live_items(root)
    if items:
        log("=" * 60)
        log(f"🛒 TRANSACTION ITEMS ({len(items)} items):")
        for idx, it in enumerate(items, 1):
            log(f"  {idx}. UPC: {it['upc']}")
            log(f"     Desc: {it['description']}")
            log(f"     Qty: {it['quantity']}, Amount: ${it['amount']:.2f}")
        log("=" * 60)
    else:
        log("🛒 No live items in transaction yet")

    log(f"DEBUG: LoyaltyID='{loyalty_id}', PhoneNumber='{phone}'")

    # Best-effort customer lookup (for your own logging / points)
    global current_customer
    current_customer = None
    lookup_ident = loyalty_id or phone
    if lookup_ident:
        try:
            payload = {"loyaltyId": loyalty_id} if loyalty_id else {"phone": phone}
            r = SESSION.post(
                f"{BACKEND_URL}/api/pos/customer-lookup",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                current_customer = r.json()
                first_name = current_customer.get("firstName", "")
                last_name  = current_customer.get("lastName", "")
                points     = current_customer.get("pointsBalance", 0)
                log(f"✓ Customer found: {first_name} {last_name} ({points} pts)")
            elif r.status_code == 404:
                log(f"⚠ Customer not found: {lookup_ident}")
            else:
                log(f"⚠ Customer lookup failed: {r.status_code}")
        except Exception as e:
            log(f"⚠ Customer lookup error: {e}")
    else:
        log("⚠ No loyalty ID or phone supplied; will still apply $1 off like demo")

    # Masked ID for receipt (exactly like demo semantics)
    display_id = (loyalty_id or phone or "")
    masked = (display_id[-4:].rjust(10, "*")) if display_id else "****"

    # ALWAYS send instant $1 basket reward (demo behavior)
    reward_actions_xml = f"""
    <AddReward>
      <LoyaltyRewardID>{REWARD_ID}</LoyaltyRewardID>
      <InstantRewardFlag value="yes"/>
      <RewardTargetLineNumber>0</RewardTargetLineNumber>
      <RewardDiscountMethod>amountOff</RewardDiscountMethod>
      <RewardValue>{DISCOUNT_VALUE:.2f}</RewardValue>
      <RewardReceiptDescShort>{RECEIPT_SHORT}</RewardReceiptDescShort>
      <RewardReceiptDescLong>{RECEIPT_LONG}</RewardReceiptDescLong>
    </AddReward>""".rstrip()

    # Minimal GetRewardsResponse, plus optional greeting if we know name
    greeting_xml = ""
    if current_customer:
        first_name = current_customer.get("firstName", "")
        points     = current_customer.get("pointsBalance", 0)
        greeting_xml = f"""
  <CustomerMessageData>
    <DisplayData>
      <DisplayCommand device="POS-Cashier" sequence="WhenReceived">
        <DisplayLine>Welcome {first_name}!</DisplayLine>
        <DisplayLine>Points Balance: {points}</DisplayLine>
      </DisplayCommand>
    </DisplayData>
  </CustomerMessageData>"""

    return f"""
<GetRewardsResponse>
  {resp_header(pos_seq, loy_seq)}
  <LoyaltyIDValidFlag value="yes">{masked}</LoyaltyIDValidFlag>{greeting_xml}
  <RewardActions>
{reward_actions_xml}
  </RewardActions>
</GetRewardsResponse>""".strip()

def build_finalize_response(root: ET.Element) -> str:
    pos_seq, loy_seq = get_req_ids(root)

    # See if Passport actually applied the $1 tender
    applied = detect_loyalty_tender(root, REWARD_ID)
    if applied > 0:
        log(f"✓ Loyalty tender detected in finalize: ${applied:.2f}")
    else:
        log("ℹ No loyalty tender detected in finalize")

    # Optional: call backend to award points (not critical for this test)
    global current_customer
    if current_customer:
        try:
            eligible_subtotal = sum(it["amount"] for it in extract_live_items(root))
            payload = {
                "customerId": current_customer.get("customerId"),
                "eligibleSubtotal": eligible_subtotal,
                "pointsRedeemed": int(round(applied * 100)),  # 100pts = $1
                "transactionId": root.findtext(".//POSTransactionID") or "",
            }
            r = SESSION.post(
                f"{BACKEND_URL}/api/pos/finalize-transaction",
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                res = r.json()
                pts_earned = res.get("pointsEarned", 0)
                new_bal    = res.get("newBalance", 0)
                log(f"✓ Transaction finalized: Earned {pts_earned} pts, New balance: {new_bal} pts")
                receipt_lines = [
                    f"Points Earned: {pts_earned} pts",
                    f"New Balance: {new_bal} pts",
                    "Thank you for shopping at Birdies!",
                ]
            else:
                log(f"⚠ Finalize failed: {r.status_code}")
                receipt_lines = ["Thank you for shopping at Birdies!"]
        except Exception as e:
            log(f"⚠ Finalize error: {e}")
            receipt_lines = ["Thank you for shopping at Birdies!"]
    else:
        receipt_lines = ["Thank you for shopping at Birdies!"]

    current_customer = None  # clear session

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
    global current_customer
    current_customer = None
    log("Transaction cancelled, customer session cleared")
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
# Connection Handler
# =========================
def handle_client(conn: socket.socket, addr):
    peer = f"{addr[0]}:{addr[1]}"
    log(f"POS connected from {peer}")

    if EXPECTED_POS_IP and addr[0] != EXPECTED_POS_IP:
        log(f"⚠ Rejecting unexpected POS IP: {addr[0]}")
        try:
            conn.close()
        except:
            pass
        return

    # send initial heartbeat with real POS IP
    send_heartbeat(addr[0])

    try:
        conn.settimeout(180)
        while True:
            hdr = recv_exact(conn, 28)
            if not hdr:
                log(f"POS disconnected: {peer}")
                break

            try:
                action, data_len, chk_data = parse_header(hdr)
            except Exception as e:
                log(f"Bad header from {peer}: {e}")
                break

            if action == ACTION_HEARTBEAT:
                if data_len:
                    _ = recv_exact(conn, data_len)
                log(f"POS heartbeat from {peer}")
                continue

            data = recv_exact(conn, data_len)
            if len(data) != data_len or crc32(data) != chk_data:
                log(f"Payload CRC/length mismatch from {peer}")
                break

            try:
                root, _raw = parse_xml(data)
            except Exception as e:
                log(f"XML parse error from {peer}: {e}")
                break

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

            elif tag in ("BeginCustomerRequest", "EndCustomerRequest"):
                log(f"{tag} received (no response required)")

            else:
                log(f"⚠ Unhandled message: {tag}")

    except socket.timeout:
        log(f"POS timeout: {peer}")
    except Exception as e:
        log(f"POS error: {peer} - {e}")
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
    log("Starting Birdies Loyalty Edge Agent (Demo Clone)")
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
