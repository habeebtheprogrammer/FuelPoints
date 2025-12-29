# Store Deployment Guide

## Package Contents

This deployment package contains everything needed to set up automated daily sales data collection at a Birdies store location.

### Files Included

```
store_deployment/
├── install.bat              # Windows installer script
├── requirements.txt         # Python dependencies
├── config.py               # Store configuration
├── main.py                 # Main ETL orchestrator
├── test_connection.py      # API connection test
├── fetch/
│   ├── __init__.py
│   ├── scanner.py          # Network share scanner
│   └── organizer.py        # File organization utilities
├── send/
│   ├── __init__.py
│   └── api_client.py       # API upload client
├── utils/
│   ├── __init__.py
│   ├── logger.py           # Logging configuration
│   └── xml_tools.py        # XML parsing utilities
├── README.md               # Setup instructions
└── DEPLOYMENT_GUIDE.md     # This file
```

## Installation Steps

### Prerequisites

- Windows PC with Python 3.8 or higher installed
- Network access to \\10.5.48.2\PPXMLData
- Internet access to reach the Birdies API endpoint

### Quick Installation

1. **Extract Package**
   - Unzip the deployment package to `C:\BirdiesSalesCollection\`

2. **Configure Store Settings**
   - Edit `config.py`
   - Set `PDI_STORE_NUMBER` to your store's PDI number (e.g., "1200")
   - Verify `API_BASE_URL` points to production API
   - Confirm network paths are correct

3. **Run Installer**
   - Double-click `install.bat`
   - This will install Python dependencies

4. **Test Connection**
   - From the `C:\BirdiesSalesCollection` directory, run:
   ```
   python test_connection.py
   ```
   - This will test API connectivity and verify basic configuration
   - **Note**: Manual testing of network share access recommended:
     * Open Windows Explorer
     * Navigate to `\\10.5.48.2\PPXMLData`
     * Confirm you can see XML files

5. **Schedule Daily Task**
   - Open Windows Task Scheduler
   - Create new task:
     * **Name**: Birdies Sales Collection
     * **Trigger**: Daily at 1:00 AM
     * **Action**: Run `python C:\BirdiesSalesCollection\main.py`
     * **Run with highest privileges**: Checked

### Manual Installation

If you prefer manual setup:

```batch
REM Change to deployment directory
cd C:\BirdiesSalesCollection

REM 1. Install dependencies
pip install -r requirements.txt

REM 2. Edit config.py with your store number

REM 3. Test API connection
python test_connection.py

REM 4. Verify network access to \\10.5.48.2\PPXMLData

REM 5. Run manual collection (optional)
python main.py
```

**Important**: Always run scripts from the `C:\BirdiesSalesCollection` directory to avoid path-related errors.

## Configuration

### config.py Settings

```python
# Your Store's PDI Number
PDI_STORE_NUMBER = "1200"  # CHANGE THIS!

# API Endpoint (Production)
API_BASE_URL = "https://loyalty.birdiesstore.com/api/sales"

# Network Paths
NETWORK_SHARE_ROOT = r"\\10.5.48.2\PPXMLData"
```

### Important Configuration Notes

1. **PDI Store Number** - Must match your location's PDI number exactly
2. **API Endpoint** - Production URL for live deployment
3. **Network Share** - Passport POS exports XML files here daily
4. **File Patterns** - System collects CPJR, FGM, ISM, MCM files only

## Operation

### Daily Collection Process

1. **Midnight** - Passport POS generates daily XML reports
2. **1:00 AM** - Scheduled task runs `main.py`
3. **Collection** - Script scans network share for new XML files
4. **Upload** - Raw XML files uploaded to backend API
5. **Logging** - Results logged to `logs/sales_collection.log`

### What Gets Collected

- **CPJR** - Complete POS Journal Report (transactions)
- **FGM** - Fuel Grade Manifest (fuel sales)
- **ISM** - Item Sales Manifest (UPC sales)
- **MCM** - Merchandise Category Manifest (department sales)

### Manual Collection

To run collection manually:

```
cd C:\BirdiesSalesCollection
python main.py
```

## Troubleshooting

### Connection Issues

**Problem**: API connection fails  
**Solution**: 
- Verify internet connectivity
- Check firewall settings
- Run `python test_connection.py`

**Problem**: Network share inaccessible  
**Solution**:
- Verify network path: `\\10.5.48.2\PPXMLData`
- Check Windows network credentials
- Ensure Passport POS is running

### File Upload Issues

**Problem**: Files not uploading  
**Solution**:
- Check logs in `logs/sales_collection.log`
- Verify PDI_STORE_NUMBER is correct
- Ensure XML files exist on network share

### Scheduled Task Issues

**Problem**: Task doesn't run  
**Solution**:
- Open Task Scheduler
- Check task history for errors
- Verify task runs with highest privileges
- Test manual execution first

## Logs

### Log Location

```
C:\BirdiesSalesCollection\logs\sales_collection.log
```

### Log Rotation

- Logs rotate automatically when reaching 10 MB
- Keeps last 5 log files
- Older logs are deleted automatically

### Log Levels

- **DEBUG** - Detailed execution trace
- **INFO** - Normal operation events
- **WARNING** - Non-critical issues
- **ERROR** - Critical failures

### Sample Log Output

```
2025-11-19 01:00:00 - INFO - Starting sales collection for store 1200
2025-11-19 01:00:05 - INFO - Found 4 XML files for date 2025-11-18
2025-11-19 01:00:10 - INFO - Uploaded CPJR file successfully
2025-11-19 01:00:12 - INFO - Uploaded FGM file successfully
2025-11-19 01:00:15 - INFO - Collection complete - 4 files uploaded
```

## Monitoring

### Health Checks

1. **Daily Verification**
   - Check log file for errors
   - Verify upload timestamps
   - Confirm file counts

2. **Weekly Review**
   - Review log file for warnings
   - Check network connectivity
   - Verify scheduled task is active

3. **Monthly Maintenance**
   - Review log file size
   - Archive old logs if needed
   - Update configuration if store changes

### Success Indicators

- ✅ Log file shows daily uploads
- ✅ No ERROR entries in logs
- ✅ File counts match expected reports
- ✅ Network share accessible
- ✅ API connection successful

### Failure Indicators

- ❌ No log entries for days
- ❌ ERROR entries in logs
- ❌ Zero files uploaded
- ❌ Network share errors
- ❌ API connection timeouts

## Support

### Log Files to Provide

When requesting support, provide:
- Last 100 lines of `logs/sales_collection.log`
- Store PDI number
- Date range of issue
- Windows Task Scheduler task history

### Common Solutions

1. **Restart Computer** - Fixes most network issues
2. **Re-run Installer** - Fixes dependency issues
3. **Check Firewall** - Ensure API access allowed
4. **Verify Network** - Test `\\10.5.48.2\PPXMLData` access

## Uninstallation

To remove the sales collection system:

1. Delete scheduled task in Task Scheduler
2. Delete `C:\BirdiesSalesCollection\` folder
3. (Optional) Uninstall Python if not used for other purposes

## Updates

To update the deployment:

1. Stop or disable the scheduled task
2. Backup `config.py` (preserve your settings)
3. Extract new deployment package
4. Restore your `config.py`
5. Re-enable scheduled task

## Security Notes

- Package runs on local Windows PC
- Network credentials use Windows authentication
- API uses HTTPS for secure transmission
- No sensitive data stored locally (raw XML deleted after upload)
- Logs contain store number but no customer PII

## Version History

**v1.0 (November 2025)**
- Initial release
- Raw XML upload to backend API
- Automated daily collection
- Comprehensive logging
- Retry logic with exponential backoff
