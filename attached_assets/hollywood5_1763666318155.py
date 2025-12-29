import socket
import threading
import logging
import struct
import xml.etree.ElementTree as ET
import os
import json

###############################################################################
# CONFIG & GLOBALS
###############################################################################
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("server_log.txt"),
        logging.StreamHandler()
    ]
)

def log_message(level, message):
    print(message)
    {
        "info": logging.info,
        "debug": logging.debug,
        "warning": logging.warning,
        "error": logging.error
    }.get(level.lower(), logging.debug)(message)

HOST = '0.0.0.0'  # your IP
PORT = 9000
STORE_NUMBER = "1330"
LOYALTY_SEQUENCE_FILE = "loyalty_sequence.json"

# We'll store redemption details keyed by <POSTransactionID>.
PENDING_REDEMPTIONS = {}

###############################################################################
# LOADING JSON
###############################################################################
CUSTOMERS = []
LOYALTY_PROGRAM = {}

def load_customers():
    """Load 'customers.json' into a list of customer dicts."""
    try:
        with open("customers.json", "r") as f:
            data = json.load(f)
        log_message("debug", f"Loaded customers data: {data}")
        return data.get("customers", [])
    except Exception as e:
        log_message("error", f"Error loading customers.json: {e}")
        return []

def load_loyalty_program():
    """Load 'loyalty_program.json' to get the reward structure."""
    try:
        with open("loyalty_program.json", "r") as f:
            data = json.load(f)
        log_message("debug", f"Loaded loyalty program data: {data}")
        return data
    except Exception as e:
        log_message("error", f"Error loading loyalty_program.json: {e}")
        return {}

CUSTOMERS = load_customers()
LOYALTY_PROGRAM = load_loyalty_program()

###############################################################################
# LENGTH-PREFIXED MESSAGE I/O
###############################################################################
def send_message(conn, message):
    message_bytes = message.encode('utf-8')
    header = struct.pack('>I', len(message_bytes))
    conn.sendall(header + message_bytes)
    log_message("debug", f"Sent message ({len(message_bytes)} bytes):\n{message}")

def recv_message(conn):
    header = conn.recv(4)
    if not header or len(header) < 4:
        return None
    length = struct.unpack('>I', header)[0]
    data = b''
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    message = data.decode('utf-8', errors='ignore')
    log_message("debug", f"Received message ({length} bytes):\n{message}")
    return message

###############################################################################
# LOYALTY SEQUENCE HELPER
###############################################################################
def get_next_loyalty_sequence_id(store_number):
    """
    Return a string like 'DT-1330-0001', auto-incremented from loyalty_sequence.json
    """
    try:
        if os.path.exists(LOYALTY_SEQUENCE_FILE):
            with open(LOYALTY_SEQUENCE_FILE, "r") as f:
                data = json.load(f)
            log_message("debug", f"Loyalty sequence file found: {data}")
        else:
            data = {}
            log_message("debug", "Loyalty sequence file not found. Starting fresh.")
    except Exception as e:
        log_message("error", f"Error reading sequence file: {e}")
        data = {}

    counter = data.get(store_number, 1)
    loyalty_seq_id = f"DT-{store_number}-{counter:04d}"
    data[store_number] = counter + 1

    try:
        with open(LOYALTY_SEQUENCE_FILE, "w") as f:
            json.dump(data, f)
        log_message("debug", f"Updated sequence file: {data}")
    except Exception as e:
        log_message("error", f"Error writing sequence file: {e}")

    return loyalty_seq_id

###############################################################################
# SIMPLE CUSTOMER & POINTS LOGIC
###############################################################################
def find_customer_by_phone(phone):
    """Return the matching customer dict from CUSTOMERS, or None if not found."""
    for c in CUSTOMERS:
        if c["phone"] == phone:
            return c
    return None

def compute_points_for_line(sales_amount, is_fuel=False):
    """
    Return how many points are earned for this line.
    If is_fuel=True, use fuel_purchases points_per_dollar
    Else use inside_purchases points_per_dollar
    """
    if is_fuel:
        p = LOYALTY_PROGRAM["fuel_purchases"]["points_per_dollar"]
    else:
        p = LOYALTY_PROGRAM["inside_purchases"]["points_per_dollar"]
    return int(sales_amount * p)

def redeem_inside_points(customer, total_spend):
    """
    Figure out how many increments of 2,000 points the user can redeem:
      increments = available_points // 2000
      discount = increments * $1
    BUT also CAP the discount so we never exceed total_spend.
    If discount > total_spend, reduce discount to total_spend, 
    and reduce increments accordingly.

    Return (increments, final_discount) 
    """
    points_req = LOYALTY_PROGRAM["inside_purchases"]["redemption"]["points_required"]  # 2000
    dollar_off = LOYALTY_PROGRAM["inside_purchases"]["redemption"]["dollar_off"]       # 1.0

    available = customer["available_points"]
    increments = available // points_req  # how many full chunks of 2,000?
    discount = increments * dollar_off

    # Now CAP the discount if it exceeds total_spend
    if discount > total_spend:
        # reduce discount to total_spend
        discount = total_spend
        # recalculate increments based on discount (since $1=2k points)
        # if discount=2.11, increments=2.11 => actually we do an int
        # you might do partial increments if you want to allow e.g. $2.11
        # let's do the simple approach: partial increments are truncated
        new_increments = int(discount)  # e.g. $2 if discount=2.11
        discount = float(new_increments)  # e.g. 2.0
        increments = new_increments

    return increments, discount

###############################################################################
# BUILDING RESPONSES
###############################################################################
def build_get_loyalty_online_status_response(pos_seq_id):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns2:GetLoyaltyOnlineStatusResponse 
    xmlns:ns2="http://www.pcats.org/schema/naxml/loyalty/v01"
    xmlns:ns3="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01">
    <ns2:ResponseHeader overallResult="success">
        <ns2:POSLoyaltyInterfaceVersion>1.1</ns2:POSLoyaltyInterfaceVersion>
        <ns3:VendorName>VIPER</ns3:VendorName>
        <ns3:VendorModelVersion>9.03.00</ns3:VendorModelVersion>
        <ns2:POSSequenceID>{pos_seq_id}</ns2:POSSequenceID>
        <ns2:LoyaltySequenceID>{seq_id}</ns2:LoyaltySequenceID>
        <ns4:Result>
            <Success/>
        </ns4:Result>
    </ns2:ResponseHeader>
    <ns2:PromptForLoyaltyFlag value="yes"/>
</ns2:GetLoyaltyOnlineStatusResponse>
'''

def build_generic_success_response(pos_seq_id):
    # fallback for unknown requests
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns2:GetLoyaltyOnlineStatusResponse 
    xmlns:ns2="http://www.pcats.org/schema/naxml/loyalty/v01"
    xmlns:ns3="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01">
    <ns2:ResponseHeader overallResult="success">
        <ns2:POSLoyaltyInterfaceVersion>1.1</ns2:POSLoyaltyInterfaceVersion>
        <ns3:VendorName>VIPER</ns3:VendorName>
        <ns3:VendorModelVersion>9.03.00</ns3:VendorModelVersion>
        <ns2:POSSequenceID>{pos_seq_id}</ns2:POSSequenceID>
        <ns2:LoyaltySequenceID>DT-GLOSR-1</ns2:LoyaltySequenceID>
        <ns4:Result>
            <Success/>
        </ns4:Result>
    </ns2:ResponseHeader>
    <ns2:PromptForLoyaltyFlag value="yes"/>
</ns2:GetLoyaltyOnlineStatusResponse>
'''

def build_get_rewards_response(pos_seq_id, loyalty_id, discount_value):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:GetRewardsResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
        <ns4:Result>
            <Success/>
        </ns4:Result>
    </ns3:ResponseHeader>
    <ns3:LoyaltyIDValidFlag value="yes">{loyalty_id}</ns3:LoyaltyIDValidFlag>
    <ns3:RewardActions>
        <ns3:AddReward>
            <ns3:LoyaltyRewardID>InsideReward</ns3:LoyaltyRewardID>
            <ns3:InstantRewardFlag value="yes"/>
            <ns3:RewardTargetLineNumber>1</ns3:RewardTargetLineNumber>
            <ns3:RewardDiscountMethod>amountOff</ns3:RewardDiscountMethod>
            <ns3:RewardValue>{discount_value:.2f}</ns3:RewardValue>
            <ns3:RewardLimit>99</ns3:RewardLimit>
            <ns3:RewardReceiptDescShort>Loyalty Discount</ns3:RewardReceiptDescShort>
        </ns3:AddReward>
    </ns3:RewardActions>
    <ns3:CustomerMessageData>
        <ns3:DisplayData>
            <ns3:DisplayCommand duration="3" sequence="WhenReceived" device="OPT">
                <ns3:DisplayLine>Your loyalty discount!</ns3:DisplayLine>
            </ns3:DisplayCommand>
        </ns3:DisplayData>
    </ns3:CustomerMessageData>
</ns3:GetRewardsResponse>
'''

def build_get_rewards_response_invalid(pos_seq_id, loyalty_id):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:GetRewardsResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
        <ns4:Result>
            <Success/>
        </ns4:Result>
    </ns3:ResponseHeader>
    <ns3:LoyaltyIDValidFlag value="no">{loyalty_id}</ns3:LoyaltyIDValidFlag>
    <ns3:RewardActions/>
</ns3:GetRewardsResponse>
'''

def build_finalize_rewards_response(pos_seq_id, receipt_line):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:FinalizeRewardsResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
        <ns4:Result>
            <Success/>
        </ns4:Result>
    </ns3:ResponseHeader>
    <ns3:CustomerMessageData>
        <ns3:DisplayData>
            <ns3:DisplayCommand duration="3" sequence="WhenReceived" device="OPT">
                <ns3:DisplayLine>{receipt_line}</ns3:DisplayLine>
            </ns3:DisplayCommand>
        </ns3:DisplayData>
        <ns3:ReceiptData>
            <ns3:ReceiptLine>{receipt_line}</ns3:ReceiptLine>
        </ns3:ReceiptData>
    </ns3:CustomerMessageData>
</ns3:FinalizeRewardsResponse>
'''

def build_cancel_transaction_response(pos_seq_id):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:CancelTransactionResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
    </ns3:ResponseHeader>
</ns3:CancelTransactionResponse>
'''

def build_reverse_transaction_response(pos_seq_id, display_line):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:ReverseTransactionResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
    </ns3:ResponseHeader>
    <ns3:CustomerMessageData>
        <ns3:DisplayData>
            <ns3:DisplayCommand duration="3" sequence="WhenReceived" device="OPT">
                <ns3:DisplayLine>{display_line}</ns3:DisplayLine>
            </ns3:DisplayCommand>
        </ns3:DisplayData>
    </ns3:CustomerMessageData>
</ns3:ReverseTransactionResponse>
'''

def build_end_period_response(pos_seq_id):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:EndPeriodResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
    </ns3:ResponseHeader>
</ns3:EndPeriodResponse>
'''

def build_cancel_redemption_response(pos_seq_id):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:CancelRedemptionResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
    </ns3:ResponseHeader>
</ns3:CancelRedemptionResponse>
'''

def build_get_reward_status_response(pos_seq_id, display_line):
    seq_id = get_next_loyalty_sequence_id(STORE_NUMBER)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<ns3:GetRewardStatusResponse 
    xmlns:ns2="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
    xmlns:ns4="http://www.pcats.org/schema/core/v01"
    xmlns:ns3="http://www.pcats.org/schema/naxml/loyalty/v01">
    <ns3:ResponseHeader overallResult="success">
        <ns3:POSLoyaltyInterfaceVersion>1.1</ns3:POSLoyaltyInterfaceVersion>
        <ns2:VendorName>VIPER</ns2:VendorName>
        <ns2:VendorModelVersion>9.03.00</ns2:VendorModelVersion>
        <ns3:POSSequenceID>{pos_seq_id}</ns3:POSSequenceID>
        <ns3:LoyaltySequenceID>{seq_id}</ns3:LoyaltySequenceID>
        <ns4:Result>
            <Success/>
        </ns4:Result>
    </ns3:ResponseHeader>
    <ns3:CustomerMessageData>
        <ns3:DisplayData>
            <ns3:DisplayCommand duration="3" sequence="WhenReceived" device="OPT">
                <ns3:DisplayLine>{display_line}</ns3:DisplayLine>
            </ns3:DisplayCommand>
        </ns3:DisplayData>
    </ns3:CustomerMessageData>
</ns3:GetRewardStatusResponse>
'''

###############################################################################
# PARSE REQUEST & EXTRACT FIELDS
###############################################################################
def parse_request(xml_str):
    request_type = "UnknownRequest"
    pos_seq_id = ""
    loyalty_seq_id = ""
    phone_number = ""
    postrans_id = ""

    try:
        root = ET.fromstring(xml_str)
        # local name of root
        if '}' in root.tag:
            local_tag = root.tag.split('}', 1)[1]
        else:
            local_tag = root.tag

        known_tags = [
            "GetLoyaltyOnlineStatusRequest",
            "GetRewardsRequest",
            "FinalizeRewardsRequest",
            "CancelTransactionRequest",
            "ReverseTransactionRequest",
            "EndPeriodRequest",
            "CancelRedemptionRequest",
            "GetRewardStatusRequest"
        ]
        if local_tag in known_tags:
            request_type = local_tag

        # Extract POSSequenceID
        pos_seq_id = extract_tag_text_namespace(root, "POSSequenceID")
        loyalty_seq_id = extract_tag_text_namespace(root, "LoyaltySequenceID")

        # Extract phone from <LoyaltyID> if present
        loyalty_id_elem = root.find(".//{*}LoyaltyID")
        if loyalty_id_elem is not None and loyalty_id_elem.text:
            phone_number = loyalty_id_elem.text.strip()

        # Extract <POSTransactionID> for consistent transaction tracking
        postrans_id = extract_tag_text_namespace(root, "POSTransactionID")

        return request_type, {
            "POSSequenceID": pos_seq_id,
            "LoyaltySequenceID": loyalty_seq_id,
            "PhoneNumber": phone_number,
            "POSTransactionID": postrans_id,
            "root": root
        }, xml_str

    except ET.ParseError as e:
        log_message("error", f"XML parse error: {e}")
    except Exception as e:
        log_message("error", f"Error parsing XML: {e}")

    return request_type, {
        "POSSequenceID": "",
        "LoyaltySequenceID": "",
        "PhoneNumber": "",
        "POSTransactionID": "",
        "root": None
    }, xml_str

def extract_tag_text_namespace(root, local_name):
    """Finds <...:local_name> inside root (any namespace)."""
    if not root:
        return ""
    elem = root.find(f".//{{*}}{local_name}")
    return elem.text.strip() if elem is not None and elem.text else ""

###############################################################################
# HELPER: Parse the Transaction Lines to Summation
###############################################################################
def parse_transaction_lines_for_amount(root):
    """
    Summation of <SalesAmount> for all <ItemLine> or <MerchandiseCodeLine>.
    We'll treat everything as 'inside' for demonstration.
    Return (is_fuel=False, total_inside_amount).
    If you want to detect fuel lines, you'd look for <FuelLine>.
    """
    if not root:
        return (False, 0.0)

    total_amount = 0.0
    detail_group = root.find(".//{*}TransactionDetailGroup")
    if detail_group is None:
        return (False, 0.0)

    # In each <TransactionLine>, look for <ItemLine> or <MerchandiseCodeLine> then <SalesAmount>
    for tline in detail_group.findall("{*}TransactionLine"):
        # If <ItemLine> or <MerchandiseCodeLine> is present, read <SalesAmount>
        item_line = tline.find("{*}ItemLine")
        merch_line = tline.find("{*}MerchandiseCodeLine")

        # For demonstration, let's treat everything as 'inside' purchases
        if item_line is not None:
            amt_elem = item_line.find("{*}SalesAmount")
            if amt_elem is not None and amt_elem.text:
                try:
                    val = float(amt_elem.text)
                    total_amount += val
                except:
                    pass

        if merch_line is not None:
            amt_elem = merch_line.find("{*}SalesAmount")
            if amt_elem is not None and amt_elem.text:
                try:
                    val = float(amt_elem.text)
                    total_amount += val
                except:
                    pass

    # If you want to detect fuel, you'd do so here. We'll just do is_fuel=False
    return (False, total_amount)

###############################################################################
# MAIN REQUEST HANDLER
###############################################################################
def handle_client(connection, address):
    log_message("info", f"Connection established with {address}")
    connection.settimeout(600)

    try:
        while True:
            xml_str = recv_message(connection)
            if xml_str is None:
                log_message("info", f"No more data from {address}. Closing connection.")
                break

            request_name, seq_data, _ = parse_request(xml_str)
            pos_seq_id   = seq_data["POSSequenceID"]
            loyalty_seq_in = seq_data["LoyaltySequenceID"]
            phone        = seq_data["PhoneNumber"]
            postrans_id  = seq_data["POSTransactionID"]
            root         = seq_data["root"]

            log_message(
                "info",
                f"Request Type: {request_name}, "
                f"POSSequenceID: {pos_seq_id}, "
                f"LoyaltySequenceID: {loyalty_seq_in}, "
                f"POSTransactionID: {postrans_id}, "
                f"Phone: {phone}"
            )

            if request_name == "GetLoyaltyOnlineStatusRequest":
                response_xml = build_get_loyalty_online_status_response(pos_seq_id)

            elif request_name == "GetRewardsRequest":
                customer = find_customer_by_phone(phone)
                if not customer:
                    response_xml = build_get_rewards_response_invalid(pos_seq_id, phone)
                else:
                    # parse lines to get total inside amount
                    (is_fuel, total_spend) = parse_transaction_lines_for_amount(root)

                    # Earn points
                    # We'll assume everything is inside, so points_per_dollar=100
                    # If you had fuel lines, you'd parse them separately.
                    # For demonstration, we do a single 'inside' approach:
                    points_earned = int(total_spend * LOYALTY_PROGRAM["inside_purchases"]["points_per_dollar"])
                    old_points = customer["available_points"]
                    new_points = old_points + points_earned
                    customer["available_points"] = new_points

                    # Now see how many increments can we redeem
                    increments, discount_total = redeem_inside_points(customer, total_spend)

                    # Store increments in PENDING_REDEMPTIONS
                    PENDING_REDEMPTIONS[postrans_id] = increments

                    response_xml = build_get_rewards_response(pos_seq_id, phone, discount_total)

            elif request_name == "FinalizeRewardsRequest":
                customer = find_customer_by_phone(phone)
                if not customer:
                    response_xml = build_finalize_rewards_response(pos_seq_id, "No account found.")
                else:
                    increments = PENDING_REDEMPTIONS.pop(postrans_id, 0)
                    if increments > 0:
                        points_req = LOYALTY_PROGRAM["inside_purchases"]["redemption"]["points_required"]
                        used_points = increments * points_req
                        if customer["available_points"] >= used_points:
                            customer["available_points"] -= used_points
                            msg_line = f"Used {used_points} points. Balance: {customer['available_points']}"
                        else:
                            msg_line = f"Not enough points. Current: {customer['available_points']}"
                    else:
                        msg_line = "No redemption increments."

                    response_xml = build_finalize_rewards_response(pos_seq_id, msg_line)

            elif request_name == "CancelTransactionRequest":
                # remove any pending redemption
                PENDING_REDEMPTIONS.pop(postrans_id, None)
                response_xml = build_cancel_transaction_response(pos_seq_id)

            elif request_name == "ReverseTransactionRequest":
                # remove any pending redemption
                PENDING_REDEMPTIONS.pop(postrans_id, None)
                response_xml = build_reverse_transaction_response(pos_seq_id, "Transaction Reversed")

            elif request_name == "EndPeriodRequest":
                response_xml = build_end_period_response(pos_seq_id)

            elif request_name == "CancelRedemptionRequest":
                response_xml = build_cancel_redemption_response(pos_seq_id)

            elif request_name == "GetRewardStatusRequest":
                customer = find_customer_by_phone(phone)
                if customer:
                    display_line = f"Points: {customer['available_points']}"
                else:
                    display_line = "No account found"
                response_xml = build_get_reward_status_response(pos_seq_id, display_line)

            else:
                response_xml = build_generic_success_response(pos_seq_id)

            log_message("debug", f"Response XML: {response_xml}")
            send_message(connection, response_xml)
            log_message("info", f"Response sent to {address}")

    except ConnectionResetError:
        log_message("warning", f"Connection with {address} was reset.")
    except socket.timeout:
        log_message("warning", f"Connection timed out with {address}. Closing.")
    except Exception as e:
        log_message("error", f"Unexpected error with {address}: {e}")
    finally:
        log_message("info", f"Closing connection with {address}")
        connection.close()

###############################################################################
# MAIN SERVER
###############################################################################
def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        log_message("info", f"Server listening on {HOST}:{PORT}")

        while True:
            conn, addr = server_socket.accept()
            client_thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            client_thread.start()

if __name__ == "__main__":
    start_server()
