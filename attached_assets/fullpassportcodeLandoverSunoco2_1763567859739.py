#!/usr/bin/env python
"""
Integrated Script for:
  1. Fetching XML files from network shares
  2. Organizing them into a dated folder structure (DEST_BASE/YYYY/MM/DD)
  3. Transforming XML files into JSON reports
  4. Sending the JSON reports via API calls
  5. Using a per-folder log (sent_log.json) to avoid re-sending data
  6. Iterating over unprocessed day folders (including a configurable “look back” period)

This version uses updated fetch logic:
  - For MAIN_FOLDER files, an effective date is extracted from XML (<EndDate> or <BusinessDate>),
    with a fallback to the file’s creation time.
  - For FPM files, the script stores their creation time and effective date for later matching.
  - For CPJR and PJRARCHIVE files, a matching FPM file is located (based on creation time being
    within ±5 minutes), and its effective date is used to determine the destination folder.
"""

import os
import shutil
import xml.etree.ElementTree as ET
import datetime
import logging
import json
from pathlib import Path
import requests
import pandas as pd
from dateutil import parser as dtparser

# ================================
# CONFIGURATION
# ================================

# Network folders
MAIN_FOLDER = r"\\10.5.48.2\PPXMLData"        # Contains files with prefixes FGM, ISM, FPM, MCM, MSM, TPM, TLM
PJR_FOLDER  = r"\\10.5.48.2\PPXMLData\PJR"      # Contains CPJR files and PJR archive zips

# Local destination base folder (where files will be organized by date)
DEST_BASE = r"C:\birdiesloyalty"

# API base URL for sending JSON reports
API_BASE_URL = "https://loyalty.birdiesstore.com/api"

# Valid prefixes for files in the main folder
MAIN_PREFIXES = ["FGM", "ISM", "FPM", "MCM", "MSM", "TPM", "TLM"]

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# ================================
# GLOBAL VARIABLES
# ================================
# Global storage for FPM records for matching CPJR/PJRArchive files.
# Each record is a dict with keys: 'filename', 'creation_time', 'effective_date'
fpm_records = []

# ================================
# FETCHING FUNCTIONS (Updated Fetch Logic)
# ================================

def parse_xml_date(file_path):
    """
    Reads an XML file and attempts to parse the <EndDate> element.
    Falls back to <BusinessDate> if needed.
    Returns a date string in "YYYY-MM-DD" format or None.
    """
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        end_elem = root.find(".//EndDate")
        if end_elem is not None and end_elem.text:
            return end_elem.text.strip()
        business_elem = root.find(".//BusinessDate")
        if business_elem is not None and business_elem.text:
            return business_elem.text.strip()
        return None
    except Exception as e:
        logging.error("Error parsing XML file %s: %s", os.path.basename(file_path), e)
        return None

def copy_file_to_date_folder(src_file, year, month, day, subfolder="general"):
    """
    Copies src_file into:
       DEST_BASE\YYYY\MM\DD\XMLFILES\subfolder
    If the destination folder does not exist, it is created.
    Skips copying if a file with the same name already exists.
    """
    dest_dir = os.path.join(DEST_BASE, year, month, day, "XMLFILES", subfolder)
    os.makedirs(dest_dir, exist_ok=True)
    filename = os.path.basename(src_file)
    dest_path = os.path.join(dest_dir, filename)
    if os.path.exists(dest_path):
        logging.info("Skipping (already exists): %s", dest_path)
    else:
        shutil.copy2(src_file, dest_path)
        logging.info("Copied %s -> %s", src_file, dest_path)

def process_main_folder(folder_path):
    """
    Processes the MAIN_FOLDER:
      - Looks for files with valid prefixes.
      - For each file, attempts to extract an effective date from XML (<EndDate> or <BusinessDate>).
        Falls back to the file's creation time if needed.
      - Copies the file into DEST_BASE/YYYY/MM/DD/XMLFILES/general based on the effective date.
      - For FPM files, records their creation_time and effective_date into the global fpm_records.
    """
    if not os.path.isdir(folder_path):
        logging.warning("Main folder does not exist: %s", folder_path)
        return
    logging.info("Processing MAIN_FOLDER: %s", folder_path)
    prefix_set = [p.upper() for p in MAIN_PREFIXES]
    for filename in os.listdir(folder_path):
        fullpath = os.path.join(folder_path, filename)
        if not os.path.isfile(fullpath):
            continue
        upper_name = filename.upper()
        if any(upper_name.startswith(pref) for pref in prefix_set):
            file_ctime = os.path.getctime(fullpath)
            # Attempt to extract the effective date from XML
            xml_date_str = parse_xml_date(fullpath)
            if xml_date_str:
                try:
                    dt_obj = datetime.datetime.strptime(xml_date_str, "%Y-%m-%d")
                except ValueError:
                    logging.error("Invalid date format '%s' in %s; using creation date", xml_date_str, filename)
                    dt_obj = datetime.datetime.fromtimestamp(file_ctime)
            else:
                logging.warning("No valid XML date in %s; using creation date", filename)
                dt_obj = datetime.datetime.fromtimestamp(file_ctime)
            effective_date = dt_obj.date()  # effective date used for destination folder
            year = dt_obj.strftime("%Y")
            month = dt_obj.strftime("%m")
            day = dt_obj.strftime("%d")
            logging.info("Using effective date %s for file %s", effective_date, filename)
            copy_file_to_date_folder(fullpath, year, month, day, subfolder="general")
            # If the file is an FPM file, record its creation time and effective date for later matching.
            if upper_name.startswith("FPM"):
                record = {
                    'filename': filename,
                    'creation_time': file_ctime,
                    'effective_date': effective_date
                }
                fpm_records.append(record)
    logging.info("Done processing MAIN_FOLDER.")

def find_matching_fpm_record(cpjr_ctime):
    """
    Searches the global fpm_records for a record whose creation_time is within ±300 seconds
    of the given CPJR (or PJRArchive) file's creation time.
    Returns the record with the smallest time difference, or None if no match is found.
    """
    best_record = None
    best_diff = 301  # threshold in seconds
    for rec in fpm_records:
        diff = abs(rec['creation_time'] - cpjr_ctime)
        if diff <= 300 and diff < best_diff:
            best_diff = diff
            best_record = rec
    return best_record

def process_pjr_folder(folder_path):
    """
    Processes the PJR_FOLDER:
      - Looks for files starting with "CPJR" or "PJRARCHIVE".
      - For each file, obtains its creation time.
      - Finds a matching FPM record (within ±5 minutes) using the global fpm_records.
      - If a match is found, uses the effective date from the FPM record to determine the destination folder.
      - Copies CPJR files into the "general" subfolder and PJRARCHIVE files into the "pjrzip" subfolder.
    """
    if not os.path.isdir(folder_path):
        logging.warning("PJR folder does not exist: %s", folder_path)
        return
    logging.info("Processing PJR_FOLDER: %s", folder_path)
    for filename in os.listdir(folder_path):
        fullpath = os.path.join(folder_path, filename)
        if not os.path.isfile(fullpath):
            continue
        upper_name = filename.upper()
        if not (upper_name.startswith("CPJR") or upper_name.startswith("PJRARCHIVE")):
            continue
        try:
            file_ctime = os.path.getctime(fullpath)
        except Exception as e:
            logging.error("Error getting creation time for %s: %s", filename, e)
            continue
        logging.info("Processing file: %s, creation time: %s", filename, datetime.datetime.fromtimestamp(file_ctime).strftime("%Y-%m-%d %H:%M:%S"))
        matching_fpm = find_matching_fpm_record(file_ctime)
        if not matching_fpm:
            logging.warning("No matching FPM file found for %s; skipping", filename)
            continue
        # Use the effective date from the matching FPM record to determine the destination folder.
        eff_date = matching_fpm['effective_date']
        year_str = eff_date.strftime("%Y")
        month_str = eff_date.strftime("%m")
        day_str = eff_date.strftime("%d")
        logging.info("Match found for %s: FPM file %s with effective date %s", filename, matching_fpm['filename'], eff_date)
        if upper_name.startswith("CPJR"):
            copy_file_to_date_folder(fullpath, year_str, month_str, day_str, subfolder="general")
        elif upper_name.startswith("PJRARCHIVE"):
            copy_file_to_date_folder(fullpath, year_str, month_str, day_str, subfolder="pjrzip")
    logging.info("Done processing PJR_FOLDER.")

# ================================
# FOLDER STRUCTURE & SELECTION FUNCTIONS (Unchanged)
# ================================

def ensure_day_folder(year, month, day):
    """
    Ensures that the folder for a given day exists, including subfolders:
      - JSONFILES
      - XMLFILES/general
      - XMLFILES/pjrzip
    Returns the Path to the day folder.
    """
    day_folder = Path(DEST_BASE) / year / month / day
    (day_folder / "JSONFILES").mkdir(parents=True, exist_ok=True)
    (day_folder / "XMLFILES" / "general").mkdir(parents=True, exist_ok=True)
    (day_folder / "XMLFILES" / "pjrzip").mkdir(parents=True, exist_ok=True)
    return day_folder

def list_day_folders():
    """
    Walks the DEST_BASE folder and returns a list of tuples:
      (date_object, day_folder_path)
    Sorted in reverse chronological order.
    """
    day_folders = []
    base = Path(DEST_BASE)
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
    """
    Checks if the day folder’s JSONFILES contains a sent_log.json.
    """
    json_dir = day_folder / "JSONFILES"
    sent_log = json_dir / "sent_log.json"
    return sent_log.exists()

def select_unprocessed_folders():
    """
    Scans the day folders and returns a list of folders that do not yet have a valid log.
    In this example, it iterates backwards (most recent first) until it finds one that has been processed.
    Then, it “looks back” up to seven days before that to catch any missing days.
    Returns the unprocessed folders (sorted in chronological order for processing).
    """
    day_folders = list_day_folders()
    unprocessed = []
    last_processed_index = None

    for idx, (dt_obj, folder) in enumerate(day_folders):
        if folder_has_valid_log(folder):
            last_processed_index = idx
            break

    if last_processed_index is None:
        # No folder processed yet – process all.
        unprocessed = [folder for dt_obj, folder in day_folders]
    else:
        # Process all folders from (last_processed_index - 7) upward.
        start_index = max(0, last_processed_index - 7)
        for idx in range(start_index, len(day_folders)):
            dt_obj, folder = day_folders[idx]
            if not folder_has_valid_log(folder):
                unprocessed.append(folder)
    # Sort unprocessed folders in ascending order (oldest first)
    unprocessed.sort(key=lambda f: f.parts[-1])
    return unprocessed

# ================================
# TRANSFORMATION FUNCTIONS (Unchanged)
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
    dir_path = Path(directory)
    prefix = prefix.lower()
    for file in dir_path.iterdir():
        if file.is_file() and file.name.lower().startswith(prefix):
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
    for fin_event in root.findall('.//FinancialEvent'):
        fdetail = fin_event.find('./FinancialEventDetail/SafeDropDetail')
        if fdetail is not None:
            drop_amt_elem = fdetail.find('./DropAmount')
            env_elem = fdetail.find('./EnvelopeID')
            if (drop_amt_elem is not None and drop_amt_elem.text == '0' and
                env_elem is not None and 'cancel' in env_elem.text.lower()):
                no_sale_count += 1

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
        event_seq = sale_event.findtext('EventSequenceID', "")
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
                            "EventSequenceID": event_seq,
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

        cc_last4 = ""
        tender_info_elem = sale_event.find('.//TenderInfo')
        if tender_info_elem is not None:
            tender_code = tender_info_elem.findtext('Tender/TenderCode', "").lower()
            if "cash" not in tender_code:
                account_id = tender_info_elem.findtext('.//AccountInfo/AccountID', "")
                if account_id:
                    cc_last4 = account_id[-4:]
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

            if reported_ppg > 0:
                unit_price = reported_ppg
            elif qty > 0:
                unit_price = amt / qty
            else:
                unit_price = 0.0

            desc = f_line.findtext('Description', "Fuel")
            fuel_vol += qty
            fuel_money += amt
            if unit_price > 0:
                fuel_price = unit_price
            parent_line = f_line.find('..')
            line_status = parent_line.get('status', "normal") if parent_line is not None else "normal"
            line_rows.append({
                "Transaction ID": trans_id,
                "Transaction DateTime": event_dt,
                "Line Status": line_status,
                "UPC": "",
                "Description": desc,
                "Unit Price ($)": unit_price,
                "Quantity": qty,
                "Amount ($)": unit_price,
                "Sales Tax": 0.0,
                "Credit Card": cc_last4,
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
            parent_line = i_line.find('..')
            line_status = parent_line.get('status', "normal") if parent_line is not None else "normal"
            line_rows.append({
                "Transaction ID": trans_id,
                "Transaction DateTime": event_dt,
                "Line Status": line_status,
                "UPC": upc,
                "Description": desc,
                "Unit Price ($)": unit_price,
                "Quantity": qty,
                "Amount ($)": amt,
                "Sales Tax": 0.0,
                "Credit Card": cc_last4,
                "Transaction Total ($)": total_amt,
                "EventSequenceID": ev_seq,
                "Cashier": cashier
            })

        for ttax in sale_event.findall('.//TransactionTax'):
            try:
                tax_amt = float(ttax.findtext('TaxCollectedAmount', "0") or 0)
            except Exception:
                tax_amt = 0.0
            parent_line = ttax.find('..')
            line_status = parent_line.get('status', "normal") if parent_line is not None else "normal"
            line_rows.append({
                "Transaction ID": trans_id,
                "Transaction DateTime": event_dt,
                "Line Status": line_status,
                "UPC": "",
                "Description": "Sales Tax",
                "Unit Price ($)": 0.0,
                "Quantity": 0.0,
                "Amount ($)": tax_amt,
                "Sales Tax": tax_amt,
                "Credit Card": cc_last4,
                "Transaction Total ($)": total_amt,
                "EventSequenceID": ev_seq,
                "Cashier": cashier
            })

        tax_total = 0.0
        for ttax in sale_event.findall('.//TransactionTax'):
            try:
                tax_total += float(ttax.findtext('TaxCollectedAmount', "0") or 0)
            except Exception:
                pass
        if total_amt == 0:
            total_amt = fuel_money + merch_money + tax_total

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
        amt = 0.0
        qty = 0.0
        tcount = 0
        if stot is not None:
            amt_e = stot.find('SalesAmount')
            qty_e = stot.find('SalesQuantity')
            tc_e = stot.find('TransactionCount')
            if amt_e is not None and amt_e.text:
                amt = float(amt_e.text)
            if qty_e is not None and qty_e.text:
                qty = float(qty_e.text)
            if tc_e is not None and tc_e.text:
                tcount = float(tc_e.text)
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
        position_summaries = d.findall('.//FGMPositionSummary')
        if position_summaries:
            vol_sum = 0.0
            amt_sum = 0.0
            for p in position_summaries:
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

    if cpjr_file:
        try:
            trans_df, line_df = create_transactions_dfs(cpjr_file)
            trans_df = append_metadata(trans_df, store_number, sequence_id, biz_begin, biz_end)
            trans_df["description"] = ""  
            trans_df["cashier_name"] = trans_df["Cashier"]
            mapping_trans = {
                "Transaction ID": "transaction_id",
                "Transaction DateTime": "date_time",
                "Cashier": "cashier",
                "description": "description",
                "cashier_name": "cashier_name",
                "Fuel Volume (USG)": "fuel_volume",
                "Fuel PPG ($)": "fuel_ppg",
                "Fuel Amount ($)": "fuel_amount",
                "Merchandise Amount ($)": "merchandise_amount",
                "Total Amount ($)": "total_amount"
            }
            trans_df = rename_for_api(trans_df, mapping_trans)
            trans_df["transactionDateTime"] = trans_df["date_time"]

            outp = json_path / "transactions_overview.json"
            save_df_as_json(trans_df, str(outp))
            logging.info("Created %s", outp)

            line_df = append_metadata(line_df, store_number, sequence_id, biz_begin, biz_end)
            trans_date_map = dict(zip(trans_df["transaction_id"], trans_df["date_time"]))
            line_df["transactionDateTime"] = line_df["Transaction ID"].map(trans_date_map)
            line_df = line_df[["Transaction ID", "Description", "Quantity", "Amount ($)", "Sales Tax", 
                                 "Credit Card", "storeNumber", "sequenceId", "transactionDateTime", 
                                 "businessDateBegin", "businessDateEnd", "date"]]
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
# API SENDING FUNCTIONS (Unchanged)
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

def send_fuel_dispenser_data(json_dir):
    data = load_json_from_dir("fuel_dispenser_data.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/fuel_dispenser_data"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "dispenser": record.get("dispenser", ""),
            "count": record.get("count", 0),
            "amount": record.get("amount", 0.0),
            "volume": record.get("volume", 0.0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (fuel_dispenser_data): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_daily_fuel_sales(json_dir):
    data = load_json_from_dir("daily_fuel_sales.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/daily_fuel_sales"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "date": record.get("date", ""),
            "total_fuel_volume": record.get("total_fuel_volume", 0.0),
            "total_fuel_revenue": record.get("total_fuel_revenue", 0.0)
        }
        logging.info("Sending payload (daily_fuel_sales): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_aggregated_item_totals(json_dir):
    data = load_json_from_dir("aggregated_item_totals.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/aggregated_item_totals"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "upc": record.get("upc", ""),
            "item_description": record.get("item_description", ""),
            "quantity_sold": record.get("quantity_sold", 0),
            "sales_amount": record.get("sales_amount", 0.0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (aggregated_item_totals): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_loyalty_data_detailed(json_dir):
    data = load_json_from_dir("loyalty_data_detailed.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/loyalty_data_detailed"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "eventsequenceid": record.get("eventsequenceid", ""),
            "transactionid": record.get("transactionid", ""),
            "businessdate": record.get("businessdate", ""),
            "loyaltyname": record.get("loyaltyname", ""),
            "loyaltyamount": record.get("loyaltyamount", 0),
            "loyaltyppudiscount": record.get("loyaltyppudiscount", 0),
            "originalppu": record.get("originalppu", 0),
            "date": record.get("date", record.get("businessDateEnd", ""))
        }
        logging.info("Sending payload (loyalty_data_detailed): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_loyalty_data_overview(json_dir):
    data = load_json_from_dir("loyalty_data_overview.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/loyalty_data_overview"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "loyaltyname": record.get("loyaltyname", ""),
            "totalloyaltytransactions": record.get("totalloyaltytransactions", 0),
            "totalloyaltyamount": record.get("totalloyaltyamount", 0),
            "totalppudiscount": record.get("totalppudiscount", 0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (loyalty_data_overview): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_store_summary(json_dir):
    data = load_json_from_dir("store_summary.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/store_summary"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "store_name": record.get("store_name", ""),
            "number_of_voids": record.get("number_of_voids", 0),
            "void_amount": record.get("void_amount", 0.0),
            "number_of_no_sales": record.get("number_of_no_sales", 0),
            "no_sales_amount": record.get("no_sales_amount", 0.0),
            "number_of_error_corrects": record.get("number_of_error_corrects", 0),
            "error_correct_amount": record.get("error_correct_amount", 0.0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (store_summary): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_daily_total_sales(json_dir):
    data = load_json_from_dir("daily_total_sales.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/daily_total_sales"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "date": record.get("date", ""),
            "fuel_sales": record.get("fuel_sales", 0.0),
            "merchandise_sales": record.get("merchandise_sales", 0.0),
            "total_sales": record.get("total_sales", 0.0)
        }
        logging.info("Sending payload (daily_total_sales): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_transaction_line_items(json_dir):
    data = load_json_from_dir("transaction_line_items.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/transaction_line_items"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "transaction_id": record.get("transaction_id", ""),
            "description": record.get("description", ""),
            "quantity": record.get("quantity", 0),
            "amount": record.get("amount", 0.0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (transaction_line_items): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_transactions_overview(json_dir):
    data = load_json_from_dir("transactions_overview.json", json_dir)
    if data is None:
        return
    url = f"{API_BASE_URL}/transactions_overview"
    for record in data:
        payload = {
            "storeNumber": record.get("storeNumber", ""),
            "sequenceId": record.get("sequenceId", ""),
            "transactionDateTime": record.get("transactionDateTime", ""),
            "businessDateBegin": record.get("businessDateBegin", ""),
            "businessDateEnd": record.get("businessDateEnd", ""),
            "transaction_id": record.get("transaction_id", ""),
            "date_time": record.get("date_time", ""),
            "cashier": record.get("cashier", ""),
            "description": record.get("description", ""),
            "cashier_name": record.get("cashier_name", ""),
            "fuel_volume": record.get("fuel_volume", 0.0),
            "fuel_ppg": record.get("fuel_ppg", 0.0),
            "fuel_amount": record.get("fuel_amount", 0.0),
            "merchandise_amount": record.get("merchandise_amount", 0.0),
            "total_amount": record.get("total_amount", 0.0),
            "date": record.get("date", "")
        }
        logging.info("Sending payload (transactions_overview): %s", payload)
        try:
            response = requests.post(url, json=payload)
            logging.info("POST %s => %s: %s", url, response.status_code, response.text)
        except requests.RequestException as e:
            logging.error("Error sending data to %s: %s", url, e)

def send_all_reports(json_dir):
    reports = [
        ("fuel_by_grade.json", send_fuel_by_grade),
        ("fuel_dispenser_data.json", send_fuel_dispenser_data),
        ("daily_fuel_sales.json", send_daily_fuel_sales),
        ("aggregated_item_totals.json", send_aggregated_item_totals),
        ("loyalty_data_detailed.json", send_loyalty_data_detailed),
        ("loyalty_data_overview.json", send_loyalty_data_overview),
        ("store_summary.json", send_store_summary),
        ("daily_total_sales.json", send_daily_total_sales),
        ("transaction_line_items.json", send_transaction_line_items),
        ("transactions_overview.json", send_transactions_overview)
    ]
    for report_name, send_func in reports:
        send_json_file(report_name, send_func, json_dir)

# ================================
# SENT LOG FUNCTIONS (Unchanged)
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
    If not, calls send_func to send the report and updates the sent log.
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
    except Exception as e:
        logging.error("Error sending %s: %s", report_name, e)

# ================================
# MAIN PROCESSING LOGIC
# ================================
def main():
    logging.info("Starting integrated process.")

    # Ensure today's folder exists
    today = datetime.datetime.now()
    year = today.strftime("%Y")
    month = today.strftime("%m")
    day = today.strftime("%d")
    ensure_day_folder(year, month, day)

    # Fetch XML files from the network shares using updated fetch logic
    process_main_folder(MAIN_FOLDER)
    process_pjr_folder(PJR_FOLDER)

    # Determine unprocessed day folders (by scanning DEST_BASE)
    unprocessed_folders = select_unprocessed_folders()
    if not unprocessed_folders:
        logging.info("No unprocessed folders found; processing today's folder by default.")
        unprocessed_folders = [Path(DEST_BASE) / year / month / day]

    logging.info("Processing the following unprocessed folders:")
    for folder in unprocessed_folders:
        logging.info(" - %s", folder)

    # For each unprocessed folder, run the transformation and API-sending steps
    for folder in unprocessed_folders:
        xml_input_dir = str(folder / "XMLFILES" / "general")
        json_output_dir = str(folder / "JSONFILES")
        logging.info("Processing folder: %s", folder)
        try:
            run_all_reports(xml_input_dir, json_output_dir)
            send_all_reports(json_output_dir)
        except Exception as e:
            logging.error("Error processing folder %s: %s", folder, e)

    logging.info("Integrated process finished.")

if __name__ == "__main__":
    main()
