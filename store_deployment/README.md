# Birdies Sales Data Collection System

## Overview

This system automatically collects daily XML reports from your Gilbarco Passport POS system and uploads them to the Birdies backend API for analytics and reporting.

## What It Does

- **Scans** network folders for Passport XML reports (CPJR, FGM, ISM, MCM)
- **Organizes** files into date-based folders (YYYY/MM/DD)
- **Uploads** raw XML files to the backend API for safe storage
- **Tracks** what's been uploaded to avoid duplicates
- **Logs** all activities for troubleshooting

## Requirements

- **Windows Computer** (back office PC recommended)
- **Python 3.8+** installed
- **Network Access** to `\\10.5.48.2\PPXMLData`
- **Internet Connection** to upload data to backend API

## Installation

### Step 1: Extract Files

Extract this entire folder to a location on your store computer, such as:
```
C:\BirdiesDataCollection\
```

### Step 2: Run Installer

1. Right-click `install.bat`
2. Select "Run as Administrator"
3. Follow the prompts

The installer will:
- Check for Python
- Install required packages
- Create necessary folders

### Step 3: Configure for Your Store

1. Open `config.py` in a text editor (Notepad++)
2. **CRITICAL:** Change `PDI_STORE_NUMBER` to match your store:
   ```python
   PDI_STORE_NUMBER = "1200"  # CHANGE THIS!
   ```
3. Verify `API_BASE_URL` is correct (should be set to production URL)
4. Save the file

### Step 4: Test the Configuration

Run the collection script manually to test:

```batch
python main.py
```

Check the log file at `C:\birdiesloyalty\logs\sales_collection.log` for any errors.

## Scheduled Automation

To run automatically every day:

### Using Windows Task Scheduler

1. Open **Task Scheduler** (search in Start menu)
2. Click **Create Basic Task**
3. Name: "Birdies Sales Data Collection"
4. Trigger: **Daily** at **1:00 AM**
5. Action: **Start a Program**
   - Program: `C:\Python3X\python.exe` (adjust to your Python path)
   - Arguments: `main.py`
   - Start in: `C:\BirdiesDataCollection\store_deployment\`
6. Check "Run with highest privileges"
7. Save the task

## File Structure

```
store_deployment/
├── main.py                 # Main orchestration script
├── config.py               # Configuration (EDIT THIS!)
├── requirements.txt        # Python dependencies
├── install.bat             # Installer script
├── README.md               # This file
├── fetch/
│   ├── scanner.py          # Scans network folders
│   └── organizer.py        # Organizes files by date
├── send/
│   └── api_client.py       # Uploads to API
└── utils/
    ├── logger.py           # Logging system
    └── xml_tools.py        # XML utilities
```

## Data Folders

The system creates these folders automatically:

```
C:\birdiesloyalty\
├── sales_data/             # Organized XML files
│   └── YYYY/MM/DD/
│       ├── XMLFILES/
│       │   └── general/    # Raw XML files
│       └── JSONFILES/
│           └── sent_log.json  # Upload tracking
└── logs/
    └── sales_collection.log   # System logs
```

## Troubleshooting

### "Cannot access network folder"

- Verify you can access `\\10.5.48.2\PPXMLData` from Windows Explorer
- Check network connectivity
- Ensure proper permissions

### "API connection failed"

- Check internet connection
- Verify `API_BASE_URL` in `config.py`
- Check firewall settings

### "No XML files found"

- Verify POS is generating daily XML reports
- Check that reports are being saved to network share
- Verify `MAIN_FOLDER` and `PJR_FOLDER` paths in `config.py`

### Check the Logs

All activity is logged to:
```
C:\birdiesloyalty\logs\sales_collection.log
```

Open this file to see detailed information about what the script is doing.

## Configuration Options

Edit `config.py` to customize:

| Setting | Description | Default |
|---------|-------------|---------|
| `PDI_STORE_NUMBER` | Your store's PDI number | **MUST CHANGE** |
| `API_BASE_URL` | Backend API URL | Production URL |
| `LOOKBACK_DAYS` | Days to check for unprocessed data | 7 |
| `BATCH_SIZE` | Records per API call | 100 |
| `MAX_RETRIES` | Retry attempts for failed uploads | 3 |
| `LOG_LEVEL` | Logging verbosity | INFO |

## What Gets Uploaded

For each business day, the system uploads:

1. **Raw XML Files** (for audit trail):
   - CPJR (Complete Transaction Journal)
   - FGM (Fuel Grade Movement)
   - ISM (Inside Store Merchandise)
   - MCM (Merchandise Category)

2. **Metadata**:
   - Business date
   - File name
   - File size
   - Upload timestamp

## Data Security

- All data is sent over HTTPS
- Raw XML files are stored securely in the backend database
- Local copies are kept for reference
- No sensitive credit card data is transmitted (POS sanitizes this)

## Support

For issues or questions:

1. Check the log file first
2. Verify configuration settings
3. Contact IT support with log file attached

## Version History

- **v1.0** - Initial release
  - Raw XML upload
  - Automatic file organization
  - Retry logic and error handling
  - Comprehensive logging
