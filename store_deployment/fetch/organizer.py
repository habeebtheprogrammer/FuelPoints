# fetch/organizer.py
# Organize XML files into date-based folder structure

import os
import shutil
import logging
from pathlib import Path
from config import DEST_BASE
from utils.xml_tools import extract_business_date

logger = logging.getLogger('BirdiesSalesCollection')

def create_date_folder(date_str):
    """
    Create date-based folder structure YYYY/MM/DD.
    
    Args:
        date_str: Date in YYYY-MM-DD format
    
    Returns:
        Path: Base folder path
    """
    try:
        year, month, day = date_str.split("-")
        base = Path(DEST_BASE) / year / month / day
        
        # Create subdirectories
        (base / "XMLFILES" / "general").mkdir(parents=True, exist_ok=True)
        (base / "JSONFILES").mkdir(parents=True, exist_ok=True)
        
        logger.debug(f"Created folder structure: {base}")
        return base
        
    except Exception as e:
        logger.error(f"Error creating date folder for {date_str}: {e}")
        return None

def copy_to_date_folder(file_path, date_str):
    """
    Copy file to appropriate date folder.
    
    Args:
        file_path: Source file path
        date_str: Date in YYYY-MM-DD format
    
    Returns:
        str: Destination path, or None if error
    """
    try:
        folder = create_date_folder(date_str)
        if not folder:
            return None
        
        filename = os.path.basename(file_path)
        dest = folder / "XMLFILES" / "general" / filename
        
        # Only copy if file doesn't already exist
        if not dest.exists():
            shutil.copy2(file_path, dest)
            logger.info(f"Copied {filename} to {date_str} folder")
        else:
            logger.debug(f"File already exists, skipping: {filename}")
        
        return str(dest)
        
    except Exception as e:
        logger.error(f"Error copying file {file_path} to {date_str}: {e}")
        return None

def organize_files(file_paths):
    """
    Organize multiple files into date folders.
    
    Args:
        file_paths: List of file paths
    
    Returns:
        dict: Mapping of business dates to organized file paths
    """
    organized = {}
    
    for file_path in file_paths:
        try:
            # Extract business date from XML
            date_str = extract_business_date(file_path)
            
            if not date_str:
                logger.warning(f"Could not determine date for {file_path}, skipping")
                continue
            
            # Copy to date folder
            dest_path = copy_to_date_folder(file_path, date_str)
            
            if dest_path:
                if date_str not in organized:
                    organized[date_str] = []
                organized[date_str].append(dest_path)
        
        except Exception as e:
            logger.error(f"Error organizing file {file_path}: {e}")
            continue
    
    logger.info(f"Organized {len(file_paths)} files into {len(organized)} date folders")
    return organized

def find_unprocessed_days(lookback_days=7):
    """
    Find date folders that haven't been uploaded yet.
    
    Args:
        lookback_days: Number of days to look back
    
    Returns:
        list: List of (date_str, folder_path) tuples
    """
    from datetime import datetime, timedelta
    import json
    
    unprocessed = []
    base_path = Path(DEST_BASE)
    
    if not base_path.exists():
        logger.warning(f"Destination base folder does not exist: {DEST_BASE}")
        return unprocessed
    
    # Check last N days
    today = datetime.now()
    
    for i in range(lookback_days):
        date = today - timedelta(days=i)
        date_str = date.strftime('%Y-%m-%d')
        year, month, day = date_str.split('-')
        
        folder_path = base_path / year / month / day
        
        if folder_path.exists():
            # Check if this folder has been uploaded
            json_folder = folder_path / "JSONFILES"
            sent_log_path = json_folder / "sent_log.json"
            
            if not sent_log_path.exists():
                unprocessed.append((date_str, folder_path))
                logger.debug(f"Found unprocessed day: {date_str}")
            else:
                # Check if upload is complete
                try:
                    with open(sent_log_path, 'r') as f:
                        sent_log = json.load(f)
                    
                    # If not all data types are marked as sent, include in unprocessed
                    if not sent_log.get('upload_complete', False):
                        unprocessed.append((date_str, folder_path))
                        logger.debug(f"Found partially processed day: {date_str}")
                
                except Exception as e:
                    logger.error(f"Error reading sent log for {date_str}: {e}")
                    unprocessed.append((date_str, folder_path))
    
    logger.info(f"Found {len(unprocessed)} unprocessed days in last {lookback_days} days")
    return unprocessed
