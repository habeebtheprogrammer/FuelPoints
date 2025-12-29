# utils/xml_tools.py
# XML parsing utilities

import os
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

logger = logging.getLogger('BirdiesSalesCollection')

def extract_business_date(xml_path):
    """
    Extract business date from XML file.
    
    Args:
        xml_path: Path to XML file
    
    Returns:
        str: Business date in YYYY-MM-DD format, or None if not found
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Try multiple possible date fields
        date_fields = [
            './/EndDate',
            './/BusinessDate',
            './/EventStartDate',
            './/ReportDate'
        ]
        
        for field in date_fields:
            date_elem = root.find(field)
            if date_elem is not None and date_elem.text:
                # Parse and normalize date
                date_str = date_elem.text.strip()
                
                # Try different date formats
                formats = ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y%m%d']
                for fmt in formats:
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        return dt.strftime('%Y-%m-%d')
                    except ValueError:
                        continue
                
                # If no format worked but we have a date string, log it
                logger.warning(f"Found date '{date_str}' but couldn't parse it")
        
        logger.warning(f"No business date found in {xml_path}")
        return None
        
    except ET.ParseError as e:
        logger.error(f"XML parsing error in {xml_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error extracting date from {xml_path}: {e}")
        return None

def validate_xml(xml_path):
    """
    Validate that an XML file is well-formed.
    
    Args:
        xml_path: Path to XML file
    
    Returns:
        bool: True if valid, False otherwise
    """
    try:
        ET.parse(xml_path)
        return True
    except ET.ParseError as e:
        logger.error(f"Invalid XML file {xml_path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error validating XML {xml_path}: {e}")
        return False

def get_xml_size(xml_path):
    """Get file size in bytes."""
    try:
        return os.path.getsize(xml_path)
    except Exception as e:
        logger.error(f"Error getting file size for {xml_path}: {e}")
        return 0

def read_xml_content(xml_path):
    """
    Read XML file content as string.
    
    Args:
        xml_path: Path to XML file
    
    Returns:
        str: XML content, or None if error
    """
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # Try with different encoding
        try:
            with open(xml_path, 'r', encoding='latin-1') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error reading XML file {xml_path} with latin-1: {e}")
            return None
    except Exception as e:
        logger.error(f"Error reading XML file {xml_path}: {e}")
        return None
