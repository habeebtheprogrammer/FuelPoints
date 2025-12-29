#!/usr/bin/env python3
"""
Birdies Loyalty - Verifone XML File Uploader
---------------------------------------------
Fetches XML files from Verifone Commander Site Controller and uploads to server.
Based on the proven Leonardtown data collection script.

Features:
- Logs into Commander Site Controller via HTTP API
- Fetches daily XML reports (vposjournal, vfueltotals, vrubyrept, etc.)
- Extracts business date from vposjournal
- Uploads raw XML to server for parsing
- Tracks uploaded files to avoid duplicates
- Runs continuously, checking for new data

Configure for your store:
1. Set PDI_STORE_NUMBER
2. Set COMMANDER_IP, USERNAME, PASSWORD
3. Run: python verifone_file_uploader.py
"""

import os
import time
import json
import requests
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import logging

# ================================
# CONFIGURATION
# ================================

# Store Information
PDI_STORE_NUMBER = "1310"  # Your store number (Hollywood = 1310, change as needed)
POS_TYPE = "Verifone-Ruby"  # or "Verifone-EPS" or "Verifone-Topaz"

# Commander Site Controller
COMMANDER_IP = "192.168.45.8"  # Commander IP address
COMMANDER_USER = "BW"          # Commander username
COMMANDER_PASS = "Welcome4"    # Commander password
COMMANDER_URL = f"https://{COMMANDER_IP}"
VERIFY_SSL = False  # Set to False for self-signed certificates

# Backend Server
# For testing, use development URL (agent can see uploads in real-time)
BACKEND_URL = "https://7f314759-0357-435a-ba76-315eef65a311-00-1c8qk8ujlqk2q.picard.replit.dev"
# For production, use: "https://salmanloyalty.replit.app"

# Local Storage (for tracking uploads)
DATA_DIR = r"C:\BirdiesData"
UPLOAD_LOG = os.path.join(DATA_DIR, "uploaded_files.json")
TEMP_DIR = os.path.join(DATA_DIR, "temp")

# Fetch Settings
FETCH_INTERVAL = 3600  # Fetch every 60 minutes (3600 seconds)
PERIOD = 1  # Commander period: 1=day, 2=week, etc.
REPTNUM = 2  # Report number: 2=previous close

# Reports to Fetch
VRUBYREPT_NAMES = [
    "summary",      # Store summary
    "department",   # Department sales  
    "category",     # Category sales
    "plu",          # PLU item sales
    "loyalty",      # Loyalty totals
    "fpDispenser",  # Fuel dispenser
    "dcrStat"       # DCR statistics
]

# ================================
# LOGGING
# ================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================================
# UPLOAD TRACKING
# ================================

def load_upload_log():
    """Load the log of already uploaded files."""
    if os.path.exists(UPLOAD_LOG):
        try:
            with open(UPLOAD_LOG, 'r') as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Could not load upload log: {e}")
            return {}
    return {}

def save_upload_log(upload_log):
    """Save the upload log."""
    try:
        os.makedirs(os.path.dirname(UPLOAD_LOG), exist_ok=True)
        with open(UPLOAD_LOG, 'w') as f:
            json.dump(upload_log, f, indent=2)
    except Exception as e:
        log.error(f"Could not save upload log: {e}")

def get_content_hash(content):
    """Calculate SHA256 hash of content for duplicate detection."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

# ================================
# COMMANDER API AUTHENTICATION
# ================================

def get_session_cookie():
    """Authenticate with Commander and get session cookie."""
    try:
        validate_url = f"{COMMANDER_URL}/cgi-bin/CGILink?cmd=validate&user={COMMANDER_USER}&passwd={COMMANDER_PASS}"
        response = requests.get(validate_url, verify=VERIFY_SSL, timeout=30)
        
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            cookie_elem = root.find('.//cookie')
            if cookie_elem is not None and cookie_elem.text:
                cookie = cookie_elem.text.strip()
                log.info(f"✅ Authenticated with Commander (cookie: {cookie[:8]}...)")
                return cookie
            else:
                log.error("❌ Session cookie not found in response")
        else:
            log.error(f"❌ Authentication failed (status {response.status_code})")
    except Exception as e:
        log.error(f"❌ Authentication error: {e}")
    return None

def release_session_cookie(cookie):
    """Release the session cookie."""
    try:
        release_url = f"{COMMANDER_URL}/cgi-bin/CGILink?cmd=releaseCredential&cookie={cookie}"
        response = requests.get(release_url, verify=VERIFY_SSL, timeout=10)
        if response.status_code == 200:
            log.info("✅ Session cookie released")
        else:
            log.warning(f"⚠️  Failed to release cookie (status {response.status_code})")
    except Exception as e:
        log.warning(f"⚠️  Error releasing cookie: {e}")

# ================================
# FETCH XML FROM COMMANDER
# ================================

def fetch_xml_report(cmd, cookie, **params):
    """Fetch a single XML report from Commander."""
    try:
        # Build URL with parameters
        url = f"{COMMANDER_URL}/cgi-bin/CGILink?cmd={cmd}&period={PERIOD}&reptnum={REPTNUM}&cookie={cookie}"
        
        # Add any additional parameters
        for key, value in params.items():
            url += f"&{key}={value}"
        
        log.debug(f"Fetching: {cmd} from Commander...")
        response = requests.get(url, verify=VERIFY_SSL, timeout=60)
        
        if response.status_code == 200:
            log.info(f"✅ Fetched {cmd} ({len(response.content)} bytes)")
            return response.content.decode('utf-8')
        else:
            log.error(f"❌ Failed to fetch {cmd} (status {response.status_code})")
            return None
    except Exception as e:
        log.error(f"❌ Error fetching {cmd}: {e}")
        return None

def extract_business_date_from_xml(xml_content):
    """Extract business date from vposjournal XML."""
    try:
        root = ET.fromstring(xml_content)
        
        # Try with namespace
        ns = {'nax': 'http://www.naxml.org/POSBO/Vocabulary/2003-10-16'}
        journal_header = root.find('.//nax:JournalHeader', ns)
        if journal_header is not None:
            end_date = journal_header.find('nax:EndDate', ns)
            if end_date is not None and end_date.text:
                return end_date.text.strip()
        
        # Try without namespace
        for elem in root.iter():
            if 'EndDate' in elem.tag:
                if elem.text:
                    return elem.text.strip()
    except Exception as e:
        log.warning(f"⚠️  Could not extract date from XML: {e}")
    
    # Default to today
    return datetime.now().strftime('%Y-%m-%d')

# ================================
# UPLOAD TO SERVER
# ================================

def upload_xml_to_server(report_type, business_date, filename, xml_content):
    """Upload XML content to the server."""
    try:
        payload = {
            "pdiStoreNumber": PDI_STORE_NUMBER,
            "reportType": report_type,
            "businessDate": business_date,
            "fileName": filename,
            "xmlContent": xml_content
        }
        
        url = f"{BACKEND_URL}/api/sales/raw-xml/upload"
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code in [200, 201]:
            log.info(f"✅ Uploaded {filename}")
            return True
        else:
            log.error(f"❌ Upload failed ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        log.error(f"❌ Upload error: {e}")
        return False

# ================================
# MAIN FETCH AND UPLOAD LOGIC
# ================================

def determine_report_type(cmd, reptname=None):
    """Map Commander report to server report type."""
    if cmd == "vposjournal" or cmd == "vtransset" or cmd == "vtranssetz":
        return "CPJR"
    elif cmd == "vfueltotals" or cmd == "vfueltotalsz":
        return "FGM"
    elif reptname:
        if reptname in ["department", "category"]:
            return "MCM"
        elif reptname in ["plu", "allProd"]:
            return "ISM"
    return "MISC"

def fetch_and_upload_reports():
    """Main function to fetch all reports from Commander and upload to server."""
    log.info("=" * 60)
    log.info("🚀 Starting Verifone data collection...")
    log.info("=" * 60)
    
    # Get session cookie
    cookie = get_session_cookie()
    if not cookie:
        log.error("❌ Could not authenticate with Commander - aborting")
        return
    
    # Load upload log
    upload_log = load_upload_log()
    uploaded_count = 0
    
    try:
        # 1. Fetch vposjournal first (to get business date)
        log.info("📥 Fetching vposjournal (transaction journal)...")
        vpos_xml = fetch_xml_report("vposjournal", cookie)
        
        if vpos_xml:
            business_date = extract_business_date_from_xml(vpos_xml)
            log.info(f"📅 Business date: {business_date}")
            
            # Check if already uploaded
            content_hash = get_content_hash(vpos_xml)
            if content_hash not in upload_log:
                filename = f"vposjournal_previousClose_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
                if upload_xml_to_server("CPJR", business_date, filename, vpos_xml):
                    upload_log[content_hash] = {
                        "filename": filename,
                        "report_type": "CPJR",
                        "business_date": business_date,
                        "uploaded_at": datetime.now().isoformat()
                    }
                    uploaded_count += 1
            else:
                log.info("⏭️  vposjournal already uploaded")
        else:
            business_date = datetime.now().strftime('%Y-%m-%d')
            log.warning(f"⚠️  Using today's date: {business_date}")
        
        # 2. Fetch transaction reports
        log.info("📥 Fetching transaction reports...")
        for cmd in ["vtransset", "vtranssetz"]:
            xml_content = fetch_xml_report(cmd, cookie)
            if xml_content:
                content_hash = get_content_hash(xml_content)
                if content_hash not in upload_log:
                    filename = f"{cmd}_previousClose_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
                    if upload_xml_to_server("CPJR", business_date, filename, xml_content):
                        upload_log[content_hash] = {
                            "filename": filename,
                            "report_type": "CPJR",
                            "business_date": business_date,
                            "uploaded_at": datetime.now().isoformat()
                        }
                        uploaded_count += 1
                else:
                    log.info(f"⏭️  {cmd} already uploaded")
        
        # 3. Fetch fuel reports
        log.info("📥 Fetching fuel reports...")
        for cmd in ["vfueltotals", "vfueltotalsz"]:
            xml_content = fetch_xml_report(cmd, cookie)
            if xml_content:
                content_hash = get_content_hash(xml_content)
                if content_hash not in upload_log:
                    filename = f"{cmd}_previousClose_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
                    if upload_xml_to_server("FGM", business_date, filename, xml_content):
                        upload_log[content_hash] = {
                            "filename": filename,
                            "report_type": "FGM",
                            "business_date": business_date,
                            "uploaded_at": datetime.now().isoformat()
                        }
                        uploaded_count += 1
                else:
                    log.info(f"⏭️  {cmd} already uploaded")
        
        # 4. Fetch Ruby reports
        log.info("📥 Fetching Ruby reports...")
        for reptname in VRUBYREPT_NAMES:
            xml_content = fetch_xml_report("vrubyrept", cookie, reptname=reptname)
            if xml_content:
                content_hash = get_content_hash(xml_content)
                if content_hash not in upload_log:
                    report_type = determine_report_type("vrubyrept", reptname)
                    filename = f"vrubyrept_{reptname}_prevClose_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
                    if upload_xml_to_server(report_type, business_date, filename, xml_content):
                        upload_log[content_hash] = {
                            "filename": filename,
                            "report_type": report_type,
                            "business_date": business_date,
                            "uploaded_at": datetime.now().isoformat()
                        }
                        uploaded_count += 1
                else:
                    log.info(f"⏭️  vrubyrept_{reptname} already uploaded")
        
        # Save upload log
        save_upload_log(upload_log)
        
        log.info("=" * 60)
        log.info(f"✨ Collection complete! Uploaded {uploaded_count} new file(s)")
        log.info("=" * 60)
        
    finally:
        # Release session cookie
        release_session_cookie(cookie)

# ================================
# MAIN LOOP
# ================================

def main():
    """Main monitoring loop."""
    log.info("=" * 60)
    log.info("🚀 Birdies Loyalty - Verifone XML File Uploader")
    log.info("=" * 60)
    log.info(f"Store Number: {PDI_STORE_NUMBER}")
    log.info(f"POS Type: {POS_TYPE}")
    log.info(f"Commander: {COMMANDER_IP}")
    log.info(f"Backend: {BACKEND_URL}")
    log.info(f"Fetch Interval: {FETCH_INTERVAL}s ({FETCH_INTERVAL/60:.0f} minutes)")
    log.info("=" * 60)
    
    # Ensure directories exist
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    log.info("✅ File uploader started - will fetch from Commander API...")
    log.info("")
    
    # Run immediately on startup
    fetch_and_upload_reports()
    
    # Main loop
    while True:
        try:
            log.info(f"⏰ Next fetch in {FETCH_INTERVAL/60:.0f} minutes...")
            time.sleep(FETCH_INTERVAL)
            
            fetch_and_upload_reports()
            
        except KeyboardInterrupt:
            log.info("\n👋 Shutting down file uploader...")
            break
        except Exception as e:
            log.error(f"⚠️  Error in main loop: {e}")
            log.info(f"⏰ Retrying in {FETCH_INTERVAL/60:.0f} minutes...")
            time.sleep(FETCH_INTERVAL)

if __name__ == "__main__":
    main()
