# fetch/scanner.py
# Scan network folders for XML files

import os
import logging
from pathlib import Path
from config import MAIN_FOLDER, PJR_FOLDER, REQUIRED_XML_PREFIXES

logger = logging.getLogger('BirdiesSalesCollection')

def scan_main_folder():
    """
    Scan main folder for required XML files.
    
    Returns:
        list: Paths to XML files
    """
    files = []
    
    try:
        if not os.path.exists(MAIN_FOLDER):
            logger.error(f"Main folder does not exist: {MAIN_FOLDER}")
            return files
        
        for filename in os.listdir(MAIN_FOLDER):
            # Check if file matches required prefixes
            if any(filename.upper().startswith(prefix) for prefix in REQUIRED_XML_PREFIXES):
                if filename.upper().endswith('.XML'):
                    full_path = os.path.join(MAIN_FOLDER, filename)
                    files.append(full_path)
                    logger.debug(f"Found XML file: {filename}")
        
        logger.info(f"Scanned main folder: found {len(files)} XML files")
        
    except PermissionError:
        logger.error(f"Permission denied accessing {MAIN_FOLDER}")
    except Exception as e:
        logger.error(f"Error scanning main folder: {e}")
    
    return files

def scan_pjr_folder():
    """
    Scan PJR folder for CPJR files.
    
    Returns:
        list: Paths to CPJR files
    """
    cpjr_files = []
    
    try:
        if not os.path.exists(PJR_FOLDER):
            logger.error(f"PJR folder does not exist: {PJR_FOLDER}")
            return cpjr_files
        
        for filename in os.listdir(PJR_FOLDER):
            if filename.upper().startswith("CPJR") and filename.upper().endswith('.XML'):
                full_path = os.path.join(PJR_FOLDER, filename)
                cpjr_files.append(full_path)
                logger.debug(f"Found CPJR file: {filename}")
        
        logger.info(f"Scanned PJR folder: found {len(cpjr_files)} CPJR files")
        
    except PermissionError:
        logger.error(f"Permission denied accessing {PJR_FOLDER}")
    except Exception as e:
        logger.error(f"Error scanning PJR folder: {e}")
    
    return cpjr_files

def scan_all_folders():
    """
    Scan both main and PJR folders.
    
    Returns:
        dict: Dictionary with 'main' and 'pjr' file lists
    """
    logger.info("Starting folder scan...")
    
    results = {
        'main': scan_main_folder(),
        'pjr': scan_pjr_folder()
    }
    
    total_files = len(results['main']) + len(results['pjr'])
    logger.info(f"Total files found: {total_files}")
    
    return results
