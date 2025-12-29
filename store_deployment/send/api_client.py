# send/api_client.py
# API client with retry logic and error handling

import requests
import logging
import time
from config import API_BASE_URL, API_TIMEOUT, MAX_RETRIES, RETRY_DELAY

logger = logging.getLogger('BirdiesSalesCollection')

def post_with_retry(endpoint, payload, max_retries=MAX_RETRIES):
    """
    POST to API endpoint with exponential backoff retry logic.
    
    Args:
        endpoint: API endpoint (without base URL)
        payload: JSON payload
        max_retries: Maximum number of retry attempts
    
    Returns:
        tuple: (success: bool, response_data: dict)
    """
    url = f"{API_BASE_URL}/{endpoint}"
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"POST to {url} (attempt {attempt + 1}/{max_retries})")
            
            response = requests.post(
                url,
                json=payload,
                timeout=API_TIMEOUT,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"API call successful: {endpoint}")
                try:
                    return True, response.json()
                except:
                    return True, {}
            
            elif response.status_code in [400, 404]:
                # Client errors - don't retry
                logger.error(f"API client error {response.status_code}: {response.text}")
                return False, {'error': response.text}
            
            else:
                # Server errors - retry
                logger.warning(f"API server error {response.status_code}, will retry")
                if attempt < max_retries - 1:
                    delay = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error(f"Max retries exceeded for {endpoint}")
                    return False, {'error': 'Max retries exceeded'}
        
        except requests.exceptions.Timeout:
            logger.warning(f"Request timeout for {endpoint} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
            else:
                logger.error(f"Max retries exceeded due to timeouts")
                return False, {'error': 'Timeout'}
        
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for {endpoint} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                delay = RETRY_DELAY * (2 ** attempt)
                time.sleep(delay)
            else:
                logger.error(f"Max retries exceeded due to connection errors")
                return False, {'error': 'Connection error'}
        
        except Exception as e:
            logger.error(f"Unexpected error calling {endpoint}: {e}")
            return False, {'error': str(e)}
    
    return False, {'error': 'Failed after retries'}

def upload_raw_xml(pdi_store_number, report_type, business_date, file_name, xml_content):
    """
    Upload raw XML file to API.
    
    Args:
        pdi_store_number: PDI store number
        report_type: Type of report (CPJR, FGM, etc.)
        business_date: Business date in YYYY-MM-DD format
        file_name: Original filename
        xml_content: XML content as string
    
    Returns:
        tuple: (success: bool, response_data: dict)
    """
    payload = {
        'pdiStoreNumber': pdi_store_number,
        'reportType': report_type,
        'businessDate': business_date,
        'fileName': file_name,
        'xmlContent': xml_content
    }
    
    logger.info(f"Uploading raw XML: {file_name} ({len(xml_content)} bytes)")
    return post_with_retry('raw-xml/upload', payload)

def upload_batch_data(endpoint, data_list, batch_key):
    """
    Upload batch data to API.
    
    Args:
        endpoint: API endpoint
        data_list: List of data records
        batch_key: Key name for the batch (e.g., 'transactions')
    
    Returns:
        tuple: (success: bool, response_data: dict)
    """
    from config import BATCH_SIZE
    
    if not data_list:
        logger.info(f"No data to upload for {endpoint}")
        return True, {}
    
    total_records = len(data_list)
    logger.info(f"Uploading {total_records} records to {endpoint}")
    
    # Split into batches
    for i in range(0, total_records, BATCH_SIZE):
        batch = data_list[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (total_records + BATCH_SIZE - 1) // BATCH_SIZE
        
        logger.info(f"Uploading batch {batch_num}/{total_batches} ({len(batch)} records)")
        
        payload = {batch_key: batch}
        success, response = post_with_retry(endpoint, payload)
        
        if not success:
            logger.error(f"Failed to upload batch {batch_num} to {endpoint}")
            return False, response
    
    logger.info(f"Successfully uploaded all {total_records} records to {endpoint}")
    return True, {}

def process_xml(business_date):
    """
    Trigger XML processing on the backend for a specific date.
    
    Args:
        business_date: Business date in YYYY-MM-DD format
    
    Returns:
        tuple: (success: bool, response_data: dict)
    """
    payload = {'businessDate': business_date}
    logger.info(f"Triggering XML processing for {business_date}")
    return post_with_retry('process-xml', payload)

def test_connection():
    """
    Test API connection.
    
    Returns:
        bool: True if connection successful
    """
    try:
        # Try to reach the API summary endpoint
        url = f"{API_BASE_URL}/summary"
        response = requests.get(url, timeout=10)
        
        if response.status_code in [200, 404]:  # 404 is ok, means API is up
            logger.info("API connection test successful")
            return True
        else:
            logger.warning(f"API returned status {response.status_code}")
            return False
    
    except Exception as e:
        logger.error(f"API connection test failed: {e}")
        return False
