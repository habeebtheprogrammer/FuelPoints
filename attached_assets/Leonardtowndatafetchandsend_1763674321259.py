"""
Integrated Script to:
  1. Fetch XML files from network shares (Verifone files)
  2. Organize them into a dated folder structure (ROOT_DIR/YYYY/MM/DD) with XML files stored directly in the day folder.
  3. Transform the XML files into JSON reports
  4. Send the JSON reports via API calls
  5. Use a sent_log.json file (stored in the day folder) to avoid re-sending data
  6. Archive sent JSON files into an "archive" subfolder within the day folder
  7. Iterate over unprocessed day folders (including older days if not yet processed)
"""

import os
import shutil
import requests
import xml.etree.ElementTree as ET
import datetime
import logging
import json
from pathlib import Path
import pandas as pd
from dateutil import parser as dtparser

# ================================
# CONFIGURATION
# ================================

# Network / Commander settings (for fetching XML files)
BASE_URL = 'https://192.168.45.8'     # IP/URL of your Commander Site Controller
USERNAME = 'BW'
PASSWORD = 'Welcome1'
REQUESTS_VERIFY_SSL = False  # Often uses self-signed certificates

# Local root directory where XML and JSON files will be stored.
ROOT_DIR = r'C:\birdiesloyalty'

# API endpoint base URL (where JSON reports are sent)
API_BASE_URL = "https://loyalty.birdiesstore.com/api"

# ================================
# LOGGING CONFIGURATION
# ================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def get_daily_log_path(root_dir=ROOT_DIR):
    logs_folder = os.path.join(root_dir, "logs")
    os.makedirs(logs_folder, exist_ok=True)
    today_str = datetime.datetime.now().strftime('%Y%m%d')
    return os.path.join(logs_folder, f"{today_str}.log")

def write_log(message, root_dir=ROOT_DIR):
    log_path = get_daily_log_path(root_dir)
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"[{timestamp}] {message}\n")
    logging.info(message)

# ================================
# 1) FETCHING FUNCTIONS
# ================================

# URLs for authentication
VALIDATE_URL = f"{BASE_URL}/cgi-bin/CGILink?cmd=validate&user={USERNAME}&passwd={PASSWORD}"
RELEASE_URL_TEMPLATE = f"{BASE_URL}/cgi-bin/CGILink?cmd=releaseCredential&cookie="

def get_session_cookie():
    try:
        response = requests.get(VALIDATE_URL, verify=REQUESTS_VERIFY_SSL)
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            cookie_elem = root.find('.//cookie')
            if cookie_elem is not None and cookie_elem.text:
                cookie = cookie_elem.text.strip()
                write_log(f"Session cookie obtained: {cookie}")
                return cookie
            else:
                write_log("Session cookie not found in response XML.")
        else:
            write_log(f"Failed to authenticate. Status code: {response.status_code}")
    except Exception as e:
        write_log(f"Error during authentication: {e}")
    return None

def release_session_cookie(cookie):
    try:
        release_url = RELEASE_URL_TEMPLATE + cookie
        response = requests.get(release_url, verify=REQUESTS_VERIFY_SSL)
        if response.status_code == 200:
            write_log("Session cookie released successfully.")
        else:
            write_log(f"Failed to release session cookie. Status code: {response.status_code}")
    except Exception as e:
        write_log(f"Error releasing session cookie: {e}")

def extract_business_date_from_vposjournal(xml_file_path):
    """
    Attempts to parse <nax:JournalHeader><nax:EndDate> from a vposjournal.
    Returns the EndDate string (e.g. '2024-12-16') if found, else None.
    """
    try:
        ns = {'nax': 'http://www.naxml.org/POSBO/Vocabulary/2003-10-16'}
        tree = ET.parse(xml_file_path)
        root = tree.getroot()
        journal_header = root.find('.//nax:JournalHeader', ns)
        if journal_header is not None:
            end_date_elem = journal_header.find('nax:EndDate', ns)
            if end_date_elem is not None and end_date_elem.text:
                return end_date_elem.text.strip()
    except Exception as e:
        write_log(f"Error parsing {xml_file_path} for EndDate: {e}")
    return None

def ensure_day_folder(root_dir, year_str, month_str, day_str):
    """
    Ensures that the folder for a given day exists:
      ROOT_DIR\YYYY\MM\DD
    Also creates an 'archive' subfolder within the day folder (for JSON files).
    Returns the Path object for the day folder.
    """
    day_folder = Path(root_dir) / year_str / month_str / day_str
    day_folder.mkdir(parents=True, exist_ok=True)
    # Create an archive subfolder for JSON files if desired.
    (day_folder / "archive").mkdir(exist_ok=True)
    return day_folder

def fetch_and_save(url, report_label, cookie, year_str, month_str, day_str):
    """
    Fetch the report from 'url', then save it directly into the day folder:
      ROOT_DIR\YYYY\MM\DD\<report_label>_<timestamp>.xml
    """
    try:
        response = requests.get(url, verify=REQUESTS_VERIFY_SSL, timeout=60)
        if response.status_code == 200:
            now_ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{report_label}_{now_ts}.xml"
            final_folder = ensure_day_folder(ROOT_DIR, year_str, month_str, day_str)
            final_path = final_folder / filename
            with open(final_path, 'wb') as file:
                file.write(response.content)
            write_log(f"Fetched {report_label} -> {final_path}")
        else:
            write_log(f"Failed to fetch {report_label}. Status code: {response.status_code}")
    except Exception as e:
        write_log(f"Error fetching {report_label}: {e}")

def fetch_ruby_previous_close_reports(cookie):
    """
    1) Fetch vposjournal to extract the effective <EndDate>.
    2) Use that date for all other report fetches.
    """
    cmd_vpos = "vposjournal"
    label_vpos = "vposjournal_previousClose"
    url_vpos = f"{BASE_URL}/cgi-bin/CGILink?cmd={cmd_vpos}&period=1&reptnum=2&cookie={cookie}"
    temp_folder = Path(ROOT_DIR) / "temp"
    temp_folder.mkdir(parents=True, exist_ok=True)
    now_ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_filename = f"{label_vpos}_{now_ts}.xml"
    temp_path = temp_folder / temp_filename

    try:
        response = requests.get(url_vpos, verify=REQUESTS_VERIFY_SSL, timeout=60)
        if response.status_code == 200:
            with open(temp_path, 'wb') as f:
                f.write(response.content)
            write_log(f"Fetched vposjournal -> {temp_path}")
            end_date_str = extract_business_date_from_vposjournal(str(temp_path))
            if end_date_str:
                try:
                    dt_obj = datetime.datetime.strptime(end_date_str, '%Y-%m-%d')
                except ValueError:
                    write_log(f"EndDate '{end_date_str}' not in YYYY-MM-DD format. Using today's date.")
                    dt_obj = datetime.datetime.now()
            else:
                write_log("No EndDate found in vposjournal. Using today's date.")
                dt_obj = datetime.datetime.now()
            year_str = dt_obj.strftime('%Y')
            month_str = dt_obj.strftime('%m')
            day_str = dt_obj.strftime('%d')
            # Move the vposjournal from temp into the final day folder.
            final_folder = ensure_day_folder(ROOT_DIR, year_str, month_str, day_str)
            final_filename = f"{label_vpos}_{now_ts}.xml"
            final_path = final_folder / final_filename
            os.rename(str(temp_path), str(final_path))
            write_log(f"Moved vposjournal to {final_path}")
        else:
            write_log(f"Failed to fetch vposjournal. Status code: {response.status_code}")
            dt_obj = datetime.datetime.now()
            year_str = dt_obj.strftime('%Y')
            month_str = dt_obj.strftime('%m')
            day_str = dt_obj.strftime('%d')
    except Exception as e:
        write_log(f"Error fetching/parsing vposjournal: {e}")
        dt_obj = datetime.datetime.now()
        year_str = dt_obj.strftime('%Y')
        month_str = dt_obj.strftime('%m')
        day_str = dt_obj.strftime('%d')

    # Now fetch additional reports using the same effective date.
    endpoints_transaction = {
        "vtransset":  "vtransset_previousClose",
        "vtranssetz": "vtranssetz_previousClose",
    }
    for cmd, label in endpoints_transaction.items():
        url = f"{BASE_URL}/cgi-bin/CGILink?cmd={cmd}&period=1&reptnum=2&cookie={cookie}"
        fetch_and_save(url, label, cookie, year_str, month_str, day_str)

    endpoints_fuel = {
        "vfueltotals":  "vfueltotals_previousClose",
        "vfueltotalsz": "vfueltotalsz_previousClose",
    }
    for cmd, label in endpoints_fuel.items():
        url = f"{BASE_URL}/cgi-bin/CGILink?cmd={cmd}&period=1&reptnum=2&cookie={cookie}"
        fetch_and_save(url, label, cookie, year_str, month_str, day_str)

    # Fetch a subset of VRuby reports.
    vrubyrept_names = ["summary", "department", "dcrStat", "loyalty", "fpDispenser", "plu", "category"]
    for reptname in vrubyrept_names:
        url_vruby = (
            f"{BASE_URL}/cgi-bin/CGILink?"
            f"cmd=vrubyrept&reptname={reptname}&period=1&reptnum=2&cookie={cookie}"
        )
        label = f"vrubyrept_{reptname}_prevClose"
        fetch_and_save(url_vruby, label, cookie, year_str, month_str, day_str)

# ================================
# 2) TRANSFORMATION FUNCTIONS
# ================================

def parse_us_datetime(date_str, time_str=None):
    if not date_str:
        return ""
    if 'T' in date_str or 'Z' in date_str:
        try:
            dt_obj = dtparser.isoparse(date_str)
            return dt_obj.strftime("%m/%d/%Y %H:%M:%S")
        except Exception as e:
            logging.error("Error parsing ISO datetime %s: %s", date_str, e)
            return date_str
    if time_str:
        combined = f"{date_str}T{time_str}"
        try:
            dt_obj = dtparser.isoparse(combined)
            return dt_obj.strftime("%m/%d/%Y %H:%M:%S")
        except Exception as e:
            logging.error("Error parsing combined datetime %s: %s", combined, e)
            return f"{date_str} {time_str}"
    else:
        try:
            dt_obj = dtparser.isoparse(date_str)
            return dt_obj.strftime("%m/%d/%Y %H:%M:%S")
        except Exception as e:
            logging.error("Error parsing datetime %s: %s", date_str, e)
            return date_str

def find_file_by_prefix(directory, prefix):
    for file in Path(directory).iterdir():
        if file.is_file() and file.name.lower().startswith(prefix.lower()):
            return str(file)
    return None

def find_files(directory):
    cpjr_file = find_file_by_prefix(directory, "cpjr")
    fgm_file  = find_file_by_prefix(directory, "fgm")
    mcm_file  = find_file_by_prefix(directory, "mcm")
    ism_file  = find_file_by_prefix(directory, "ism")
    return cpjr_file, fgm_file, mcm_file, ism_file

def extract_cpjr_store_and_sequence(cpjr_file):
    tree = ET.parse(cpjr_file)
    root = tree.getroot()
    store_number = root.findtext('.//TransmissionHeader/StoreLocationID', default="Unknown")
    sequence_id  = root.findtext('.//JournalHeader/ReportSequenceNumber', default="Unknown")
    return store_number, sequence_id

def extract_mcm_dates(mcm_file):
    tree = ET.parse(mcm_file)
    root = tree.getroot()
    begin_date = root.findtext('.//MerchandiseCodeMovement/MovementHeader/BeginDate', "")
    begin_time = root.findtext('.//MerchandiseCodeMovement/MovementHeader/BeginTime', "")
    end_date   = root.findtext('.//MerchandiseCodeMovement/MovementHeader/EndDate', "")
    end_time   = root.findtext('.//MerchandiseCodeMovement/MovementHeader/EndTime', "")
    business_date_begin = parse_us_datetime(begin_date, begin_time)
    business_date_end   = parse_us_datetime(end_date, end_time)
    return business_date_begin, business_date_end

def create_store_summary_df(cpjr_file):
    tree = ET.parse(cpjr_file)
    root = tree.getroot()
    void_count = 0
    void_amount = 0.0
    no_sale_count = 0
    no_sale_amount = 0.0
    for sale_event in root.findall('.//SaleEvent'):
        for tline in sale_event.findall('.//TransactionLine[@status="cancel"]'):
            amt_elem = tline.find('.//SalesAmount')
            if amt_elem is not None and amt_elem.text:
                try:
                    amt = float(amt_elem.text)
                except:
                    amt = 0.0
                if amt != 0:
                    void_count += 1
                    void_amount += amt
    data = {
        "Store Name": ["Passport CPJR File"],
        "Number of Voids": [void_count],
        "Void Amount ($)": [void_amount],
        "Number of No Sales": [no_sale_count],
        "No Sales Amount ($)": [no_sale_amount],
        "Number of Error Corrects": [0],
        "Error Correct Amount ($)": [0.0],
    }
    return pd.DataFrame(data)

def create_fuel_dispenser_df(cpjr_file):
    tree = ET.parse(cpjr_file)
    root = tree.getroot()
    dispenser_map = {}
    for sale_event in root.findall('.//SaleEvent'):
        for fuel_line in sale_event.findall('.//FuelLine'):
            pos_id = fuel_line.findtext('FuelPositionID', "Unknown")
            qty = float(fuel_line.findtext('SalesQuantity', "0") or 0)
            amt = float(fuel_line.findtext('SalesAmount', "0") or 0)
            if pos_id not in dispenser_map:
                dispenser_map[pos_id] = {
                    "Dispenser #": pos_id,
                    "Count": 0,
                    "Amount ($)": 0.0,
                    "Volume (USG)": 0.0
                }
            dispenser_map[pos_id]["Count"] += 1
            dispenser_map[pos_id]["Amount ($)"] += amt
            dispenser_map[pos_id]["Volume (USG)"] += qty
    return pd.DataFrame(dispenser_map.values())

def create_loyalty_dfs(cpjr_file):
    tree = ET.parse(cpjr_file)
    root = tree.getroot()
    detail_rows = []
    for sale_event in root.findall('.//SaleEvent'):
        ev_seq = sale_event.findtext('EventSequenceID', "")
        trans_id = sale_event.findtext('TransactionID', "")
        for tline in sale_event.findall('.//TransactionLine'):
            fuel_line = tline.find('./FuelLine')
            if fuel_line is not None:
                promo = fuel_line.find('./Promotion')
                if promo is not None:
                    reason = promo.findtext('PromotionReason', "")
                    if reason == 'loyaltyDiscount':
                        loyalty_name = promo.findtext('PromotionID', "UnknownLoyalty")
                        promo_amt_text = promo.findtext('PromotionAmount', "0")
                        try:
                            promo_val = float(promo_amt_text)
                        except:
                            promo_val = 0.0
                        loyalty_amt = abs(promo_val)
                        reg_ppu_text = fuel_line.findtext('RegularSellPrice', "0")
                        act_ppu_text = fuel_line.findtext('ActualSalesPrice', "0")
                        try:
                            reg_ppu = float(reg_ppu_text)
                            act_ppu = float(act_ppu_text)
                        except:
                            reg_ppu = 0.0
                            act_ppu = 0.0
                        loyalty_ppu_disc = round(reg_ppu - act_ppu, 4)
                        detail_rows.append({
                            "EventSequenceID": ev_seq,
                            "TransactionID": trans_id,
                            "LoyaltyName": loyalty_name,
                            "LoyaltyAmount": loyalty_amt,
                            "LoyaltyPPUDiscount": loyalty_ppu_disc,
                            "OriginalPPU": reg_ppu
                        })
    if not detail_rows:
        cols = ["EventSequenceID","TransactionID","LoyaltyName","LoyaltyAmount","LoyaltyPPUDiscount","OriginalPPU"]
        return pd.DataFrame(columns=cols), pd.DataFrame(columns=["LoyaltyName","TotalLoyaltyTransactions","TotalLoyaltyAmount","TotalPPUDiscount"])
    detailed_df = pd.DataFrame(detail_rows)
    grouped = detailed_df.groupby("LoyaltyName", as_index=False).agg({
        "TransactionID": pd.Series.nunique,
        "LoyaltyAmount": "sum",
        "LoyaltyPPUDiscount": "sum"
    })
    grouped.rename(columns={
        "TransactionID": "TotalLoyaltyTransactions",
        "LoyaltyAmount": "TotalLoyaltyAmount",
        "LoyaltyPPUDiscount": "TotalPPUDiscount"
    }, inplace=True)
    return detailed_df, grouped

def create_transactions_dfs(cpjr_file):
    tree = ET.parse(cpjr_file)
    root = tree.getroot()
    trans_rows = []
    line_rows = []
    for sale_event in root.findall('.//SaleEvent'):
        ev_seq = sale_event.findtext('EventSequenceID', "")
        trans_id = sale_event.findtext('TransactionID', "")
        cashier = sale_event.findtext('CashierID', "")
        date_ = sale_event.findtext('EventStartDate', "")
        time_ = sale_event.findtext('EventStartTime', "")
        event_dt = parse_us_datetime(date_, time_)
        grand_elem = sale_event.find('.//TransactionSummary/TransactionTotalGrandAmount')
        total_amt = float(grand_elem.text) if (grand_elem is not None and grand_elem.text) else 0.0
        fuel_vol = 0.0
        fuel_money = 0.0
        merch_money = 0.0
        fuel_price = 0.0

        for f_line in sale_event.findall('.//FuelLine'):
            try:
                qty = float(f_line.findtext('SalesQuantity', "0") or 0)
            except Exception:
                qty = 0.0
            try:
                amt = float(f_line.findtext('SalesAmount', "0") or 0)
            except Exception:
                amt = 0.0
            try:
                reported_ppg = float(f_line.findtext('ActualSalesPrice', "0") or 0)
            except Exception:
                reported_ppg = 0.0
            unit_price = reported_ppg if reported_ppg > 0 else (amt / qty if qty > 0 else 0.0)
            desc = f_line.findtext('Description', "Fuel")
            fuel_vol += qty
            fuel_money += amt
            if unit_price > 0:
                fuel_price = unit_price
            line_rows.append({
                "Transaction ID": trans_id,
                "Transaction DateTime": event_dt,
                "Line Status": f_line.get("status", "normal"),
                "UPC": "",
                "Description": desc,
                "Unit Price ($)": unit_price,
                "Quantity": qty,
                "Amount ($)": amt,
                "Sales Tax": 0.0,
                "Credit Card": "",
                "Transaction Total ($)": total_amt,
                "EventSequenceID": ev_seq,
                "Cashier": cashier
            })

        for i_line in sale_event.findall('.//ItemLine'):
            upc = i_line.findtext('./ItemCode/POSCode', "")
            desc = i_line.findtext('Description', "Merchandise")
            try:
                unit_price = float(i_line.findtext('ActualSalesPrice', "0") or 0)
                qty = float(i_line.findtext('SalesQuantity', "0") or 0)
                amt = float(i_line.findtext('SalesAmount', "0") or 0)
            except Exception:
                unit_price, qty, amt = 0.0, 0.0, 0.0
            merch_money += amt
            line_rows.append({
                "Transaction ID": trans_id,
                "Transaction DateTime": event_dt,
                "Line Status": i_line.get("status", "normal"),
                "UPC": upc,
                "Description": desc,
                "Unit Price ($)": unit_price,
                "Quantity": qty,
                "Amount ($)": amt,
                "Sales Tax": 0.0,
                "Credit Card": "",
                "Transaction Total ($)": total_amt,
                "EventSequenceID": ev_seq,
                "Cashier": cashier
            })

        trans_rows.append({
            "EventSequenceID": ev_seq,
            "Transaction ID": trans_id,
            "Transaction DateTime": event_dt,
            "Cashier": cashier,
            "Fuel Volume (USG)": fuel_vol,
            "Fuel PPG ($)": fuel_price,
            "Fuel Amount ($)": fuel_money,
            "Merchandise Amount ($)": merch_money,
            "Total Amount ($)": total_amt
        })
    transactions_df = pd.DataFrame(trans_rows)
    line_items_df = pd.DataFrame(line_rows)
    return transactions_df, line_items_df

def create_item_totals_dfs_from_ism(ism_file):
    tree = ET.parse(ism_file)
    root = tree.getroot()
    items = []
    for detail in root.findall('.//ISMDetail'):
        upc = detail.findtext('./ItemCode/POSCode', "")
        desc = detail.findtext('Description', "")
        qty_elem = detail.find('.//ISMSalesTotals/SalesQuantity')
        amt_elem = detail.find('.//ISMSalesTotals/SalesAmount')
        qty = float(qty_elem.text) if (qty_elem is not None and qty_elem.text) else 0.0
        amt = float(amt_elem.text) if (amt_elem is not None and amt_elem.text) else 0.0
        items.append({
            "UPC": upc,
            "Item Description": desc,
            "Quantity Sold": qty,
            "Sales Amount ($)": amt
        })
    raw_df = pd.DataFrame(items)
    if raw_df.empty:
        agg_df = pd.DataFrame(columns=["UPC", "Item Description", "Quantity Sold", "Sales Amount ($)"])
    else:
        agg_df = raw_df.groupby(["UPC", "Item Description"], as_index=False).agg({
            "Quantity Sold": "sum",
            "Sales Amount ($)": "sum"
        })
    return raw_df, agg_df

def create_department_sales_df_from_mcm(mcm_file):
    tree = ET.parse(mcm_file)
    root = tree.getroot()
    rows = []
    for detail in root.findall('.//MerchandiseCodeMovement/MCMDetail'):
        code = detail.findtext('MerchandiseCode', "")
        desc = detail.findtext('MerchandiseCodeDescription', "")
        stot = detail.find('./MCMSalesTotals')
        amt = qty = tcount = 0
        if stot is not None:
            amt = float(stot.findtext('SalesAmount', "0") or 0)
            qty = float(stot.findtext('SalesQuantity', "0") or 0)
            tcount = float(stot.findtext('TransactionCount', "0") or 0)
        rows.append({
            "Department Number": code,
            "Department Name": desc,
            "Department Sales": amt,
            "Department Quantity": qty,
            "TransactionCount": tcount
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[~df["Department Name"].str.lower().str.contains("fuel")]
    return df

def create_fuel_by_grade_df_from_fgm(fgm_file):
    tree = ET.parse(fgm_file)
    root = tree.getroot()
    details = root.findall('.//FuelGradeMovement/FGMDetail')
    grade_map = {}
    for d in details:
        grade_id = d.findtext('FuelGradeID', "Unknown")
        pos_summaries = d.findall('.//FGMPositionSummary')
        if pos_summaries:
            vol_sum = amt_sum = 0.0
            for p in pos_summaries:
                vol = float(p.findtext('./FGMSalesTotals/FuelGradeSalesVolume', "0") or 0)
                amt = float(p.findtext('./FGMSalesTotals/FuelGradeSalesAmount', "0") or 0)
                vol_sum += vol
                amt_sum += amt
        else:
            vol_sum = float(d.findtext('.//FGMSalesTotals/FuelGradeSalesVolume', "0") or 0)
            amt_sum = float(d.findtext('.//FGMSalesTotals/FuelGradeSalesAmount', "0") or 0)
        desc = f"Fuel Grade {grade_id}"
        if grade_id not in grade_map:
            grade_map[grade_id] = {
                "Fuel Grade": desc,
                "Volume (USG)": 0.0,
                "Sales ($)": 0.0
            }
        grade_map[grade_id]["Volume (USG)"] += vol_sum
        grade_map[grade_id]["Sales ($)"] += amt_sum
    df = pd.DataFrame(grade_map.values())
    if df.empty:
        df = pd.DataFrame(columns=["Fuel Grade", "Volume (USG)", "Sales ($)"])
    return df

def create_total_and_fuel_sales_dfs_from_fgm_and_mcm(fgm_file, mcm_file):
    fgm_df = create_fuel_by_grade_df_from_fgm(fgm_file)
    total_fuel_amount = fgm_df["Sales ($)"].sum()
    total_fuel_volume = fgm_df["Volume (USG)"].sum()
    dept_df = create_department_sales_df_from_mcm(mcm_file)
    total_merch = dept_df["Department Sales"].sum()
    total_sales = total_fuel_amount + total_merch
    total_sales_df = pd.DataFrame([{
        "Fuel Sales ($)": total_fuel_amount,
        "Merchandise Sales ($)": total_merch,
        "Total Sales ($)": total_sales
    }])
    fuel_sales_df = pd.DataFrame([{
        "Total Fuel Volume (USG)": total_fuel_volume,
        "Total Fuel Revenue ($)": total_fuel_amount
    }])
    return total_sales_df, fuel_sales_df

def append_metadata(df, store_number, sequence_id, biz_begin, biz_end):
    df["storeNumber"] = store_number
    df["sequenceId"] = sequence_id
    df["transactionDateTime"] = biz_end
    df["businessDateBegin"] = biz_begin
    df["businessDateEnd"] = biz_end
    df["date"] = biz_end.split()[0] if biz_end else ""
    return df

def rename_for_api(df, mapping):
    return df.rename(columns=mapping)

def save_df_as_json(df, fname):
    if df is not None and not df.empty:
        df.to_json(fname, orient="records", indent=2, date_format="iso")
    else:
        Path(fname).write_text("[]")

def run_all_reports(xml_dir, json_dir):
    """
    In this version, xml_dir and json_dir refer to the same day folder.
    The function finds specific XML files (by prefix) in that folder,
    transforms them into various JSON reports, and writes the JSON files into the same folder.
    """
    cpjr_file, fgm_file, mcm_file, ism_file = find_files(xml_dir)
    if not cpjr_file:
        logging.error("No CPJR file found in %s", xml_dir)
    if not fgm_file:
        logging.error("No FGM file found in %s", xml_dir)
    if not mcm_file:
        logging.error("No MCM file found in %s", xml_dir)
    if not ism_file:
        logging.error("No ISM file found in %s", xml_dir)

    store_number, sequence_id = ("Unknown", "Unknown")
    if cpjr_file:
        try:
            store_number, sequence_id = extract_cpjr_store_and_sequence(cpjr_file)
        except Exception as e:
            logging.error("Error extracting CPJR store# & sequence#: %s", e)

    biz_begin, biz_end = ("", "")
    if mcm_file:
        try:
            biz_begin, biz_end = extract_mcm_dates(mcm_file)
        except Exception as e:
            logging.error("Error extracting MCM dates: %s", e)

    logging.info("Found files:")
    logging.info("  CPJR = %s", cpjr_file)
    logging.info("  FGM  = %s", fgm_file)
    logging.info("  MCM  = %s", mcm_file)
    logging.info("  ISM  = %s", ism_file)
    logging.info("StoreNumber = %s, SequenceID = %s, BusinessDateBegin = %s, BusinessDateEnd = %s",
                 store_number, sequence_id, biz_begin, biz_end)

    json_path = Path(json_dir)
    json_path.mkdir(parents=True, exist_ok=True)

    # Store Summary
    if cpjr_file:
        try:
            df = create_store_summary_df(cpjr_file)
            df = append_metadata(df, store_number, sequence_id, biz_begin, biz_end)
            mapping = {
                "Store Name": "store_name",
                "Number of Voids": "number_of_voids",
                "Void Amount ($)": "void_amount",
                "Number of No Sales": "number_of_no_sales",
                "No Sales Amount ($)": "no_sales_amount",
                "Number of Error Corrects": "number_of_error_corrects",
                "Error Correct Amount ($)": "error_correct_amount"
            }
            df = rename_for_api(df, mapping)
            outp = json_path / "store_summary.json"
            save_df_as_json(df, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in store_summary: %s", e)

    # Fuel Dispenser Data
    if cpjr_file:
        try:
            df = create_fuel_dispenser_df(cpjr_file)
            df = append_metadata(df, store_number, sequence_id, biz_begin, biz_end)
            mapping = {
                "Dispenser #": "dispenser",
                "Count": "count",
                "Amount ($)": "amount",
                "Volume (USG)": "volume"
            }
            df = rename_for_api(df, mapping)
            outp = json_path / "fuel_dispenser_data.json"
            save_df_as_json(df, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in fuel_dispenser_data: %s", e)

    # Total & Fuel Sales
    if fgm_file and mcm_file:
        try:
            total_sales_df, fuel_sales_df = create_total_and_fuel_sales_dfs_from_fgm_and_mcm(fgm_file, mcm_file)
            total_sales_df = append_metadata(total_sales_df, store_number, sequence_id, biz_begin, biz_end)
            mapping_total = {
                "Fuel Sales ($)": "fuel_sales",
                "Merchandise Sales ($)": "merchandise_sales",
                "Total Sales ($)": "total_sales"
            }
            total_sales_df = rename_for_api(total_sales_df, mapping_total)
            outp = json_path / "daily_total_sales.json"
            save_df_as_json(total_sales_df, str(outp))
            logging.info("Created %s", outp)
            
            fuel_sales_df = append_metadata(fuel_sales_df, store_number, sequence_id, biz_begin, biz_end)
            mapping_fuel = {
                "Total Fuel Volume (USG)": "total_fuel_volume",
                "Total Fuel Revenue ($)": "total_fuel_revenue"
            }
            fuel_sales_df = rename_for_api(fuel_sales_df, mapping_fuel)
            outp = json_path / "daily_fuel_sales.json"
            save_df_as_json(fuel_sales_df, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in total/fuel sales: %s", e)

    # Fuel by Grade
    if fgm_file:
        try:
            df = create_fuel_by_grade_df_from_fgm(fgm_file)
            df = append_metadata(df, store_number, sequence_id, biz_begin, biz_end)
            mapping = {
                "Fuel Grade": "fuel_grade",
                "Volume (USG)": "volume",
                "Sales ($)": "sales"
            }
            df = rename_for_api(df, mapping)
            outp = json_path / "fuel_by_grade.json"
            save_df_as_json(df, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in fuel_by_grade: %s", e)

    # Loyalty Data
    if cpjr_file:
        try:
            loyalty_det, loyalty_ov = create_loyalty_dfs(cpjr_file)
            loyalty_det = append_metadata(loyalty_det, store_number, sequence_id, biz_begin, biz_end)
            mapping_det = {
                "EventSequenceID": "eventsequenceid",
                "TransactionID": "transactionid",
                "LoyaltyName": "loyaltyname",
                "LoyaltyAmount": "loyaltyamount",
                "LoyaltyPPUDiscount": "loyaltyppudiscount",
                "OriginalPPU": "originalppu"
            }
            loyalty_det = rename_for_api(loyalty_det, mapping_det)
            outp = json_path / "loyalty_data_detailed.json"
            save_df_as_json(loyalty_det, str(outp))
            logging.info("Created %s", outp)
            
            loyalty_ov = append_metadata(loyalty_ov, store_number, sequence_id, biz_begin, biz_end)
            mapping_ov = {
                "LoyaltyName": "loyaltyname",
                "TotalLoyaltyTransactions": "totalloyaltytransactions",
                "TotalLoyaltyAmount": "totalloyaltyamount",
                "TotalPPUDiscount": "totalppudiscount"
            }
            loyalty_ov = rename_for_api(loyalty_ov, mapping_ov)
            outp = json_path / "loyalty_data_overview.json"
            save_df_as_json(loyalty_ov, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in loyalty data: %s", e)

    # Transactions & Line Items
    if cpjr_file:
        try:
            trans_df, line_df = create_transactions_dfs(cpjr_file)
            trans_df = append_metadata(trans_df, store_number, sequence_id, biz_begin, biz_end)
            mapping_trans = {
                "Transaction ID": "transaction_id",
                "Transaction DateTime": "date_time",
                "Cashier": "cashier",
                "Fuel Volume (USG)": "fuel_volume",
                "Fuel PPG ($)": "fuel_ppg",
                "Fuel Amount ($)": "fuel_amount",
                "Merchandise Amount ($)": "merchandise_amount",
                "Total Amount ($)": "total_amount"
            }
            trans_df = rename_for_api(trans_df, mapping_trans)
            outp = json_path / "transactions_overview.json"
            save_df_as_json(trans_df, str(outp))
            logging.info("Created %s", outp)

            line_df = append_metadata(line_df, store_number, sequence_id, biz_begin, biz_end)
            mapping_line = {
                "Transaction ID": "transaction_id",
                "Description": "description",
                "Quantity": "quantity",
                "Amount ($)": "amount",
                "Sales Tax": "sales_tax",
                "Credit Card": "credit_card"
            }
            line_df = rename_for_api(line_df, mapping_line)
            outp = json_path / "transaction_line_items.json"
            save_df_as_json(line_df, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in transactions: %s", e)

    # Item Totals from ISM
    if ism_file:
        try:
            raw_item_df, agg_item_df = create_item_totals_dfs_from_ism(ism_file)
            raw_item_df = append_metadata(raw_item_df, store_number, sequence_id, biz_begin, biz_end)
            mapping_item = {
                "UPC": "upc",
                "Item Description": "item_description",
                "Quantity Sold": "quantity_sold",
                "Sales Amount ($)": "sales_amount"
            }
            raw_item_df = rename_for_api(raw_item_df, mapping_item)
            outp = json_path / "item_totals_raw.json"
            save_df_as_json(raw_item_df, str(outp))
            logging.info("Created %s", outp)
            
            agg_item_df = append_metadata(agg_item_df, store_number, sequence_id, biz_begin, biz_end)
            agg_item_df = rename_for_api(agg_item_df, mapping_item)
            outp = json_path / "aggregated_item_totals.json"
            save_df_as_json(agg_item_df, str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in item totals (ISM): %s", e)

    # Department Sales from MCM
    if mcm_file:
        try:
            dept_df = create_department_sales_df_from_mcm(mcm_file)
            if "date" not in dept_df.columns:
                dept_df["date"] = biz_end.split()[0] if biz_end else ""
            dept_df = append_metadata(dept_df, store_number, sequence_id, biz_begin, biz_end)
            mapping_dept = {
                "date": "date",
                "Department Number": "department_number",
                "Department Name": "department_name",
                "Department Sales": "department_sales"
            }
            dept_df = rename_for_api(dept_df, mapping_dept)
            outp = json_path / "department_sales_totals_only.json"
            cols = ["date", "department_number", "department_name", "department_sales",
                    "storeNumber", "sequenceId", "transactionDateTime", "businessDateBegin", "businessDateEnd"]
            save_df_as_json(dept_df[cols], str(outp))
            logging.info("Created %s", outp)
        except Exception as e:
            logging.error("Error in department sales (MCM): %s", e)

    logging.info("All JSON reports created in: %s", json_dir)

# ================================
# 3) API SENDING FUNCTIONS
# ================================

def load_json_from_dir(filename, json_dir):
    file_path = Path(json_dir) / filename
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error("Error reading file %s: %s", file_path, e)
        return None

def send_fuel_by_grade(json_dir):
    data = load_json_from_dir("fuel_by_grade.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/fuel_by_grade"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "fuel_grade": record.get("fuel_grade", ""),
            "volume": record.get("volume", 0.0),
            "sales": record.get("sales", 0.0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (fuel_by_grade): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

# (Other sending functions for fuel_dispenser_data, daily_fuel_sales, aggregated_item_totals,
# loyalty_data_detailed, loyalty_data_overview, store_summary, daily_total_sales,
# transaction_line_items, transactions_overview would be defined similarly.)

def send_all_reports(json_dir):
    reports = [
        ("fuel_by_grade.json", send_fuel_by_grade),
        # Add additional tuples for other reports as needed:
        # ("fuel_dispenser_data.json", send_fuel_dispenser_data),
        # ("daily_fuel_sales.json", send_daily_fuel_sales),
        # ("aggregated_item_totals.json", send_aggregated_item_totals),
        # ("loyalty_data_detailed.json", send_loyalty_data_detailed),
        # ("loyalty_data_overview.json", send_loyalty_data_overview),
        # ("store_summary.json", send_store_summary),
        # ("daily_total_sales.json", send_daily_total_sales),
        # ("transaction_line_items.json", send_transaction_line_items),
        # ("transactions_overview.json", send_transactions_overview)
    ]
    for report_name, send_func in reports:
        send_json_file(report_name, send_func, json_dir)

# ================================
# 4) SENT LOG FUNCTIONS & JSON ARCHIVING
# ================================

def load_sent_log(json_dir):
    log_path = Path(json_dir) / "sent_log.json"
    if log_path.exists():
        try:
            with open(log_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error("Error loading sent log: %s", e)
            return {}
    return {}

def save_sent_log(json_dir, log_data):
    log_path = Path(json_dir) / "sent_log.json"
    try:
        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2)
    except Exception as e:
        logging.error("Error saving sent log: %s", e)

def send_json_file(report_name, send_func, json_dir):
    """
    Checks if the report file has already been sent (by comparing modification time).
    If not, calls send_func to send the report, updates the sent log, and archives the file.
    """
    log_data = load_sent_log(json_dir)
    file_path = Path(json_dir) / report_name
    if not file_path.exists():
        logging.info("%s does not exist; skipping.", report_name)
        return
    file_mtime = os.path.getmtime(file_path)
    log_entry = log_data.get(report_name)
    if log_entry and log_entry.get("file_mtime") == file_mtime and log_entry.get("sent") is True:
        logging.info("%s already sent; skipping.", report_name)
        return
    try:
        send_func(json_dir)
        log_data[report_name] = {
            "file_mtime": file_mtime,
            "sent": True,
            "sent_at": datetime.datetime.now().isoformat()
        }
        save_sent_log(json_dir, log_data)
        logging.info("Sent %s successfully.", report_name)
        # Archive the file: move it to the "archive" subfolder of the day folder.
        archive_folder = Path(json_dir) / "archive"
        archive_folder.mkdir(exist_ok=True)
        archive_path = archive_folder / report_name
        shutil.move(str(file_path), str(archive_path))
        logging.info("Archived %s to %s.", report_name, archive_path)
    except Exception as e:
        logging.error("Error sending %s: %s", report_name, e)

# ================================
# 5) FOLDER SELECTION (Unprocessed Day Folders)
# ================================

def list_day_folders():
    day_folders = []
    base = Path(ROOT_DIR)
    for year_dir in base.iterdir():
        if year_dir.is_dir() and year_dir.name.isdigit():
            for month_dir in year_dir.iterdir():
                if month_dir.is_dir() and month_dir.name.isdigit():
                    for day_dir in month_dir.iterdir():
                        if day_dir.is_dir() and day_dir.name.isdigit():
                            try:
                                dt_obj = datetime.datetime.strptime(f"{year_dir.name}-{month_dir.name}-{day_dir.name}", "%Y-%m-%d")
                                day_folders.append((dt_obj, day_dir))
                            except Exception:
                                continue
    day_folders.sort(key=lambda x: x[0], reverse=True)
    return day_folders

def folder_has_valid_log(day_folder):
    sent_log = day_folder / "sent_log.json"
    return sent_log.exists()

def select_unprocessed_folders():
    day_folders = list_day_folders()
    unprocessed = []
    last_processed_index = None
    for idx, (dt_obj, folder) in enumerate(day_folders):
        if folder_has_valid_log(folder):
            last_processed_index = idx
            break
    if last_processed_index is None:
        unprocessed = [folder for dt_obj, folder in day_folders]
    else:
        start_index = max(0, last_processed_index - 7)
        for idx in range(start_index, len(day_folders)):
            dt_obj, folder = day_folders[idx]
            if not folder_has_valid_log(folder):
                unprocessed.append(folder)
    unprocessed.sort(key=lambda f: f.parts[-1])
    return unprocessed

# ================================
# 6) MAIN PROCESSING LOGIC
# ================================

def main():
    write_log("Starting integrated process.")

    # Ensure today's folder exists.
    today = datetime.datetime.now()
    year = today.strftime("%Y")
    month = today.strftime("%m")
    day = today.strftime("%d")
    ensure_day_folder(ROOT_DIR, year, month, day)

    # Fetch XML files from network shares.
    cookie = get_session_cookie()
    if not cookie:
        write_log("Unable to obtain session cookie. Exiting.")
        return
    try:
        fetch_ruby_previous_close_reports(cookie)
    finally:
        release_session_cookie(cookie)

    # Determine unprocessed day folders.
    unprocessed_folders = select_unprocessed_folders()
    if not unprocessed_folders:
        write_log("No unprocessed folders found; processing today's folder by default.")
        unprocessed_folders = [Path(ROOT_DIR) / year / month / day]

    write_log("Processing the following unprocessed folders:")
    for folder in unprocessed_folders:
        write_log(f" - {folder}")

    # For each unprocessed folder, run transformation and API sending.
    for folder in unprocessed_folders:
        # In this version, XML files and JSON outputs are in the same day folder.
        xml_input_dir = str(folder)      # XML files are directly in the day folder.
        json_output_dir = str(folder)      # JSON files will also be written to the day folder.
        write_log(f"Processing folder: {folder}")
        try:
            run_all_reports(xml_input_dir, json_output_dir)
            send_all_reports(json_output_dir)
        except Exception as e:
            write_log(f"Error processing folder {folder}: {e}")

    write_log("Integrated process finished.")

if __name__ == "__main__":
    main()
