# main.py
# Main orchestration script for Birdies Sales Data Collection

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Import configuration
from config import (
    PDI_STORE_NUMBER, LOG_FILE, LOG_LEVEL, MAX_LOG_SIZE, 
    LOG_BACKUP_COUNT, LOOKBACK_DAYS, SENT_LOG, DEST_BASE
)

# Import modules
from utils.logger import setup_logger
from utils.xml_tools import extract_business_date, read_xml_content, validate_xml
from fetch.scanner import scan_all_folders
from fetch.organizer import organize_files, find_unprocessed_days, create_date_folder
from send.api_client import upload_raw_xml, test_connection, process_xml

def load_sent_log(date_folder):
    """Load sent log for a specific date folder."""
    sent_log_path = date_folder / "JSONFILES" / "sent_log.json"
    
    if sent_log_path.exists():
        try:
            with open(sent_log_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading sent log: {e}")
            return {}
    
    return {}

def save_sent_log(date_folder, log_data):
    """Save sent log for a specific date folder."""
    json_folder = date_folder / "JSONFILES"
    json_folder.mkdir(parents=True, exist_ok=True)
    
    sent_log_path = json_folder / "sent_log.json"
    
    try:
        with open(sent_log_path, 'w') as f:
            json.dump(log_data, f, indent=2)
        logger.debug(f"Saved sent log to {sent_log_path}")
    except Exception as e:
        logger.error(f"Error saving sent log: {e}")

def process_xml_files(date_str, date_folder):
    """
    Process XML files for a specific date - upload raw XML to API.
    
    Args:
        date_str: Business date in YYYY-MM-DD format
        date_folder: Path to date folder
    
    Returns:
        bool: True if successful
    """
    logger.info(f"Processing XML files for {date_str}")
    
    # Load sent log to track what's been uploaded
    sent_log = load_sent_log(date_folder)
    
    if not sent_log.get('uploaded_files'):
        sent_log['uploaded_files'] = []
    
    # Get XML files from folder
    xml_folder = date_folder / "XMLFILES" / "general"
    
    if not xml_folder.exists():
        logger.warning(f"XML folder does not exist: {xml_folder}")
        return False
    
    xml_files = list(xml_folder.glob("*.xml")) + list(xml_folder.glob("*.XML"))
    
    if not xml_files:
        logger.warning(f"No XML files found in {xml_folder}")
        return False
    
    logger.info(f"Found {len(xml_files)} XML files to process")
    
    success_count = 0
    error_count = 0
    
    for xml_file in xml_files:
        filename = xml_file.name
        
        # Skip if already uploaded
        if filename in sent_log['uploaded_files']:
            logger.debug(f"Already uploaded: {filename}")
            continue
        
        # Determine report type from filename
        filename_upper = filename.upper()
        if filename_upper.startswith('CPJR'):
            report_type = 'CPJR'
        elif filename_upper.startswith('FGM'):
            report_type = 'FGM'
        elif filename_upper.startswith('MCM'):
            report_type = 'MCM'
        elif filename_upper.startswith('ISM'):
            report_type = 'ISM'
        else:
            logger.warning(f"Unknown report type for {filename}, skipping")
            continue
        
        # Validate XML
        if not validate_xml(xml_file):
            logger.error(f"Invalid XML file: {filename}")
            error_count += 1
            continue
        
        # Read XML content
        xml_content = read_xml_content(xml_file)
        
        if not xml_content:
            logger.error(f"Could not read XML content: {filename}")
            error_count += 1
            continue
        
        # Upload to API
        logger.info(f"Uploading {filename} ({len(xml_content)} bytes)")
        
        success, response = upload_raw_xml(
            pdi_store_number=PDI_STORE_NUMBER,
            report_type=report_type,
            business_date=date_str,
            file_name=filename,
            xml_content=xml_content
        )
        
        if success:
            logger.info(f"Successfully uploaded {filename}")
            sent_log['uploaded_files'].append(filename)
            success_count += 1
            
            # Save progress after each successful upload
            save_sent_log(date_folder, sent_log)
        else:
            logger.error(f"Failed to upload {filename}: {response.get('error', 'Unknown error')}")
            error_count += 1
    
    # Mark as complete if all files uploaded
    if error_count == 0 and success_count > 0:
        sent_log['upload_complete'] = True
        sent_log['completed_at'] = datetime.now().isoformat()
        save_sent_log(date_folder, sent_log)
        logger.info(f"Completed upload for {date_str}: {success_count} files uploaded")
        
        # Now trigger XML processing on the backend
        logger.info(f"Triggering XML processing for {date_str}")
        process_success, process_response = process_xml(date_str)
        
        if process_success:
            logger.info(f"XML processing completed successfully for {date_str}")
            sent_log['processing_complete'] = True
            sent_log['processing_completed_at'] = datetime.now().isoformat()
            save_sent_log(date_folder, sent_log)
            return True
        else:
            logger.error(f"XML processing failed for {date_str}: {process_response.get('error', 'Unknown error')}")
            return False
    elif success_count > 0:
        logger.warning(f"Partial success for {date_str}: {success_count} uploaded, {error_count} errors")
        return False
    else:
        logger.error(f"No files uploaded for {date_str}")
        return False

def main():
    """Main execution function."""
    global logger
    
    # Setup logging
    logger = setup_logger(LOG_FILE, LOG_LEVEL, MAX_LOG_SIZE, LOG_BACKUP_COUNT)
    
    logger.info("=" * 80)
    logger.info("Birdies Sales Data Collection - Starting")
    logger.info(f"Store: {PDI_STORE_NUMBER}")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 80)
    
    # Test API connection
    logger.info("Testing API connection...")
    if not test_connection():
        logger.error("Cannot connect to API - aborting")
        return False
    
    # Step 1: Scan network folders for new XML files
    logger.info("Step 1: Scanning network folders for XML files...")
    try:
        scanned_files = scan_all_folders()
        all_files = scanned_files['main'] + scanned_files['pjr']
        
        if not all_files:
            logger.warning("No XML files found in network folders")
        else:
            logger.info(f"Found {len(all_files)} XML files in network folders")
            
            # Step 2: Organize files into date folders
            logger.info("Step 2: Organizing files into date folders...")
            organized = organize_files(all_files)
            logger.info(f"Organized into {len(organized)} date folders")
    
    except Exception as e:
        logger.error(f"Error during file scanning/organizing: {e}")
    
    # Step 3: Find unprocessed days
    logger.info(f"Step 3: Finding unprocessed days (looking back {LOOKBACK_DAYS} days)...")
    unprocessed_days = find_unprocessed_days(LOOKBACK_DAYS)
    
    if not unprocessed_days:
        logger.info("No unprocessed days found - all caught up!")
        logger.info("=" * 80)
        logger.info("Birdies Sales Data Collection - Complete")
        logger.info("=" * 80)
        return True
    
    logger.info(f"Found {len(unprocessed_days)} unprocessed days")
    
    # Step 4: Process each unprocessed day
    success_days = 0
    failed_days = 0
    
    for date_str, date_folder in unprocessed_days:
        logger.info(f"Processing date: {date_str}")
        
        try:
            if process_xml_files(date_str, date_folder):
                success_days += 1
            else:
                failed_days += 1
        
        except Exception as e:
            logger.error(f"Error processing {date_str}: {e}")
            failed_days += 1
    
    # Summary
    logger.info("=" * 80)
    logger.info("Processing Summary:")
    logger.info(f"  Successfully processed: {success_days} days")
    logger.info(f"  Failed or partial:     {failed_days} days")
    logger.info("=" * 80)
    logger.info("Birdies Sales Data Collection - Complete")
    logger.info("=" * 80)
    
    return failed_days == 0

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
