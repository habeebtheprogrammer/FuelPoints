#!/usr/bin/env python3
import requests
import xml.etree.ElementTree as ET
import logging
import time

# ================================
# CONFIG
# ================================
COMMANDER_IP   = "192.168.45.95"
COMMANDER_URL  = f"https://{COMMANDER_IP}"
COMMANDER_USER = "BW"
COMMANDER_PASS = "Welcome4"   # use the currently working password
VERIFY_SSL     = False        # Commander commonly uses self-signed certs

# Target change
INPUT_CODE     = "81003051808"   # can be 11/12/13/14 digits; we'll normalize to GTIN-14
NEW_PRICE      = 3.99            # dollars

# ================================
# LOGGING
# ================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ================================
# Helpers: UPC/GTIN normalization
# ================================
def upc_check_digit_12(upc11: str) -> str:
    """
    Compute UPC-A check digit for 11-digit input. Returns the single check digit.
    """
    if len(upc11) != 11 or not upc11.isdigit():
        raise ValueError("upc11 must be 11 digits")
    digits = [int(d) for d in upc11]
    odd_sum  = sum(digits[0::2])   # positions 1,3,5,7,9,11
    even_sum = sum(digits[1::2])   # positions 2,4,6,8,10
    total = odd_sum * 3 + even_sum
    check = (10 - (total % 10)) % 10
    return str(check)

def to_gtin14(code: str) -> str:
    """
    Normalize input code to a 14-digit GTIN string the Commander pricebook uses in <POSCode>.
    - 14 digits: return as-is
    - 13 digits: prefix '0'
    - 12 digits: prefix '00'
    - 11 digits: compute UPC check digit -> 12-digit UPC -> prefix '00'
    """
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == 14:
        return digits
    if len(digits) == 13:
        return "0" + digits
    if len(digits) == 12:
        return "00" + digits
    if len(digits) == 11:
        check = upc_check_digit_12(digits)
        return "00" + digits + check
    raise ValueError(f"Unsupported code length {len(digits)} for '{code}'")

# ================================
# Commander auth
# ================================
def get_cookie(user: str, passwd: str) -> str:
    url = f"{COMMANDER_URL}/cgi-bin/CGILink?cmd=validate&user={user}&passwd={passwd}"
    r = requests.get(url, timeout=30, verify=VERIFY_SSL)
    r.raise_for_status()
    # credential.xsd doc: <credential><cookie>...</cookie>...
    root = ET.fromstring(r.text)
    cookie_elem = root.find(".//cookie")
    if cookie_elem is None or not cookie_elem.text:
        raise RuntimeError("No cookie in validate response")
    return cookie_elem.text.strip()

def release_cookie(cookie: str):
    try:
        url = f"{COMMANDER_URL}/cgi-bin/CGILink?cmd=releaseCredential&cookie={cookie}"
        requests.get(url, timeout=15, verify=VERIFY_SSL)
    except Exception:
        pass

# ================================
# NAXML: fetch & update
# ================================
NAXML_NS = {"nax": "http://www.naxml.org/POSBO/Vocabulary/2003-10-16"}

def fetch_item_price(cookie: str, gtin14: str):
    """
    Download Item dataset and return (price_str, description) for given GTIN-14, or (None, None).
    """
    url = f"{COMMANDER_URL}/cgi-bin/NAXML?cmd=vMaintenance&dataset=Item&cookie={cookie}"
    r = requests.get(url, timeout=120, verify=VERIFY_SSL)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    # Iterate ITTDetail looking for matching POSCode
    for itt in root.findall(".//nax:ItemMaintenance/nax:ITTDetail", NAXML_NS):
        poscode = itt.find("./nax:ItemCode/nax:POSCode", NAXML_NS)
        if poscode is not None and (poscode.text or "").strip() == gtin14:
            price = itt.find("./nax:ITTData/nax:RegularSellPrice", NAXML_NS)
            desc  = itt.find("./nax:ITTData/nax:Description", NAXML_NS)
            return ((price.text.strip() if price is not None and price.text else None),
                    (desc.text.strip() if desc is not None and desc.text else None))
    return (None, None)

def build_item_price_update_xml(gtin14: str, new_price: float) -> str:
    """
    Minimal NAXML ItemMaintenance document to change RegularSellPrice for one PLU.
    Uses allowed values: TableAction=update, RecordAction=addchange.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NAXML-MaintenanceRequest version="3.4"
  xmlns="http://www.naxml.org/POSBO/Vocabulary/2003-10-16"
  xmlns:vxt="urn:vfi-sapphire:np.naxmlext.2005-06-24">
  <ItemMaintenance>
    <TableAction type="update"/>
    <RecordAction type="addchange"/>
    <ITTDetail>
      <ItemCode>
        <POSCodeFormat format="PLU"/>
        <POSCode>{gtin14}</POSCode>
        <POSCodeModifier>000</POSCodeModifier>
      </ItemCode>
      <ITTData>
        <RegularSellPrice>{new_price:.2f}</RegularSellPrice>
      </ITTData>
    </ITTDetail>
  </ItemMaintenance>
</NAXML-MaintenanceRequest>
""".strip()

def post_item_update(cookie: str, xml_payload: str):
    url = f"{COMMANDER_URL}/cgi-bin/NAXML?cmd=uMaintenance&dataset=Item&cookie={cookie}"
    headers = {"Content-Type": "application/xml"}
    r = requests.post(url, data=xml_payload.encode("utf-8"), headers=headers,
                      timeout=60, verify=VERIFY_SSL)
    r.raise_for_status()
    return r.text

# ================================
# MAIN
# ================================
def main():
    target_gtin14 = to_gtin14(INPUT_CODE)
    log.info(f"Normalized code: {INPUT_CODE} -> GTIN-14 {target_gtin14}")

    cookie = get_cookie(COMMANDER_USER, COMMANDER_PASS)
    log.info("Got Commander cookie")

    try:
        before_price, desc = fetch_item_price(cookie, target_gtin14)
        if before_price is None:
            raise RuntimeError(f"PLU {target_gtin14} not found in Item dataset")

        log.info(f"Current price for '{desc or target_gtin14}': {before_price}")

        if float(before_price) == float(NEW_PRICE):
            log.info("Price already at requested value; no update needed.")
            return

        update_xml = build_item_price_update_xml(target_gtin14, NEW_PRICE)
        log.info("Posting price update...")
        resp = post_item_update(cookie, update_xml)
        log.info("Update POST complete (HTTP 200).")

        # Short pause then re-poll to verify
        time.sleep(3)
        after_price, _ = fetch_item_price(cookie, target_gtin14)
        if after_price is None:
            raise RuntimeError("Verification: item disappeared after update (unexpected).")
        log.info(f"New price: {after_price}")

        if float(after_price) != float(NEW_PRICE):
            raise RuntimeError(f"Verification failed: expected {NEW_PRICE:.2f}, saw {after_price}")
        log.info("✅ Price change verified.")
    finally:
        release_cookie(cookie)
        log.info("Cookie released")

if __name__ == "__main__":
    main()
