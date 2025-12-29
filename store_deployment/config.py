# config.py
# Configuration for Birdies Sales Data Collection System

import os
from pathlib import Path

# ============================================
# NETWORK CONFIGURATION
# ============================================

# Network folders containing raw XML from Passport POS
MAIN_FOLDER = r"\\10.5.48.2\PPXMLData"
PJR_FOLDER = r"\\10.5.48.2\PPXMLData\PJR"

# ============================================
# LOCAL STORAGE CONFIGURATION
# ============================================

# Local destination for organized XML files
DEST_BASE = r"C:\birdiesloyalty"

# Log file location
LOG_FILE = r"C:\birdiesloyalty\logs\sales_collection.log"

# Sent log to track uploaded files
SENT_LOG = r"C:\birdiesloyalty\sent_log.json"

# ============================================
# API CONFIGURATION
# ============================================

# Backend API URL
API_BASE_URL = "https://salmanloyalty.replit.app/api/sales"
# When you move to your custom domain, change to: https://loyalty.birdiesstore.com/api/sales

# API timeout in seconds
API_TIMEOUT = 60

# Batch size for sending records (to avoid overwhelming the API)
BATCH_SIZE = 100

# ============================================
# STORE CONFIGURATION
# ============================================

# PDI Store Number - MUST BE CONFIGURED FOR EACH STORE
# This should match the pdi_store_number in your locations table
# Mechanicsville = "1340", Hollywood = "1310"
PDI_STORE_NUMBER = "1340"  # ⚠️ CHANGE THIS FOR EACH STORE

# ============================================
# FILE PROCESSING CONFIGURATION
# ============================================

# XML file types to process
REQUIRED_XML_PREFIXES = ["CPJR", "FGM", "MCM", "ISM"]

# XML files to skip (not needed for analytics)
IGNORED_PREFIXES = ["FPM", "MSM", "TPM", "TLM"]

# Number of days to look back for processing
LOOKBACK_DAYS = 7

# ============================================
# RETRY CONFIGURATION
# ============================================

# Maximum number of retry attempts for failed API calls
MAX_RETRIES = 3

# Initial retry delay in seconds (will use exponential backoff)
RETRY_DELAY = 2

# ============================================
# LOGGING CONFIGURATION
# ============================================

# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL = "INFO"

# Maximum log file size in bytes (10MB)
MAX_LOG_SIZE = 10 * 1024 * 1024

# Number of backup log files to keep
LOG_BACKUP_COUNT = 5
