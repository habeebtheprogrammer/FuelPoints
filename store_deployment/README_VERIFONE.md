# Verifone Store Deployment Guide

## Overview

This deployment package allows Verifone stores (Ruby2/Topaz/EPS with Commander Site Controller) to automatically upload XML sales data to the Birdies Loyalty server.

## Architecture

```
┌─────────────────────────┐
│  Verifone POS System    │
│  (Ruby2/Topaz/EPS)      │
└──────────┬──────────────┘
           │ Generates XML
           ▼
┌─────────────────────────┐
│  Commander Site         │
│  Controller             │
│  - Exports XML files    │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  verifone_file_         │
│  uploader.py            │
│  - Monitors directory   │
│  - Uploads XML files    │
└──────────┬──────────────┘
           │ HTTP POST
           ▼
┌─────────────────────────┐
│  Birdies Server         │
│  - Stores raw XML       │
│  - Parses XML           │
│  - Generates reports    │
└─────────────────────────┘
```

## Files Supported

The uploader monitors for these Verifone XML report types:

### Transaction Reports (mapped to CPJR)
- `vposjournal*.xml` - POS transaction journal (main transaction data)
- `vtransset*.xml` - Transaction sets

### Fuel Reports (mapped to FGM)
- `vfueltotals*.xml` - Fuel sales totals by grade/pump
- `vfueltotalsz*.xml` - Compressed fuel totals

### Merchandise Reports
- `vrubyrept_department*.xml` - Department sales (mapped to MCM)
- `vrubyrept_category*.xml` - Category sales (mapped to MCM)
- `vrubyrept_plu*.xml` - PLU item sales (mapped to ISM)
- `vrubyrept_allprod*.xml` - All products (mapped to ISM)

### Additional Reports (tracked as MISC)
- `vrubyrept_summary*.xml` - Store summary
- `vrubyrept_loyalty*.xml` - Loyalty totals
- `vrubyrept_fpDispenser*.xml` - Fuel dispenser details
- And many more (see URL Reference Guide)

## Installation

### Prerequisites
- Windows PC with Python 3.7+
- Network access to Commander Site Controller
- Network access to Birdies server

### Setup Steps

1. **Install Python** (if not already installed)
   - Download from https://www.python.org/downloads/
   - During installation, check "Add Python to PATH"

2. **Install Required Packages**
   ```bash
   pip install requests
   ```

3. **Configure the Script**
   
   Edit `verifone_file_uploader.py`:
   
   ```python
   # Set your store number
   PDI_STORE_NUMBER = "1310"  # Hollywood = 1310
   
   # Set your POS type
   POS_TYPE = "Verifone-Ruby"  # or "Verifone-EPS" or "Verifone-Topaz"
   
   # Set XML file directory (where Commander saves XML exports)
   XML_WATCH_DIR = r"C:\BirdiesData\XML"
   ```

4. **Configure Commander to Export XML**
   
   In Commander configuration:
   - Enable automatic XML export
   - Set export directory to `C:\BirdiesData\XML` (or your chosen path)
   - Configure daily export schedule (recommended: after business day close)

5. **Test the Uploader**
   ```bash
   python verifone_file_uploader.py
   ```
   
   You should see:
   ```
   ============================================================
   🚀 Birdies Loyalty - Verifone XML File Uploader
   ============================================================
   Store Number: 1310
   POS Type: Verifone-Ruby
   Backend: https://salmanloyalty.replit.app
   Mode: File Monitoring (C:\BirdiesData\XML)
   ============================================================
   ✅ File uploader started - monitoring for XML files...
   ```

## Running as a Service

### Option 1: Windows Task Scheduler (Recommended)

1. Open Task Scheduler
2. Create New Task:
   - **Name**: Birdies Verifone Uploader
   - **Trigger**: At system startup
   - **Action**: Start a program
     - Program: `python.exe`
     - Arguments: `C:\BirdiesData\verifone_file_uploader.py`
   - **Settings**: 
     - ✅ Run whether user is logged on or not
     - ✅ Run with highest privileges

### Option 2: NSSM (Non-Sucking Service Manager)

1. Download NSSM from https://nssm.cc/download
2. Install as service:
   ```bash
   nssm install BirdiesUploader "C:\Python39\python.exe" "C:\BirdiesData\verifone_file_uploader.py"
   nssm start BirdiesUploader
   ```

## How It Works

### File Monitoring Flow

1. **Scan**: Every 60 seconds, scans `XML_WATCH_DIR` for XML files
2. **Hash**: Calculates SHA256 hash of each file to detect duplicates
3. **Check**: Compares hash against `uploaded_files.json` log
4. **Upload**: If new file, uploads to server via POST `/api/sales/raw-xml/upload`
5. **Track**: Records uploaded file hash to prevent re-uploading
6. **Repeat**: Continues monitoring

### Server Processing

Once uploaded, the server:
1. Stores raw XML in `sales_raw_xml` table
2. Background job parses XML every 30 minutes
3. Extracts data into analytics tables
4. Reports become available in Sales Analytics dashboard

## Troubleshooting

### No files being uploaded

**Check 1**: Verify XML directory exists
```bash
dir C:\BirdiesData\XML
```

**Check 2**: Verify Commander is exporting XML files
- Check Commander configuration
- Look for XML files in export directory

**Check 3**: Check uploader logs
```
Found 0 XML file(s)  <- No files found
Found 5 XML file(s)  <- Files found
```

### Files found but not uploading

**Check 1**: Network connectivity
```bash
ping salmanloyalty.replit.app
```

**Check 2**: Server endpoint
```bash
curl https://salmanloyalty.replit.app/api/sales/raw-xml/upload
```

**Check 3**: Review error messages in console

### Files uploaded but not appearing in reports

1. Check Sales Analytics → Raw XML tab
2. Verify `processingStatus` is "processed" (not "pending" or "error")
3. If "pending", wait for next background processing job (runs every 30 minutes)
4. If "error", check server logs for parsing issues

## Comparison: Verifone vs Passport

| Feature | Verifone (This Script) | Passport (Existing) |
|---------|----------------------|-------------------|
| **Collection** | File monitoring | File monitoring |
| **# of Files** | 4+ reports | 4 reports (CPJR, FGM, MCM, ISM) |
| **Upload** | HTTP POST | HTTP POST |
| **Parsing** | Server-side | Server-side |
| **Format** | NAXML/Verifone XML | NAXML/Passport XML |

Both systems use the same server infrastructure - they just generate slightly different XML formats.

## Advanced: HTTP API Mode

If you want to fetch files directly from Commander HTTP API (like the old Leonardtown script):

```python
# Enable HTTP API mode
USE_HTTP_API = True
COMMANDER_IP = "192.168.45.8"
COMMANDER_USER = "BW"
COMMANDER_PASS = "Welcome1"
```

This would require implementing the HTTP API fetching logic based on the URL Reference Guide.

## File Formats

### Verifone vs Passport XML

**Verifone vposjournal:**
```xml
<nax:POSJournal xmlns:nax="http://www.naxml.org/POSBO/Vocabulary/2003-10-16">
  <nax:JournalHeader>
    <nax:BeginDate>2025-02-03</nax:BeginDate>
    <nax:EndDate>2025-02-04</nax:EndDate>
  </nax:JournalHeader>
  <nax:SaleEvent>
    <nax:TransactionLine>
      <nax:SalesAmount>68.96</nax:SalesAmount>
    </nax:TransactionLine>
  </nax:SaleEvent>
</nax:POSJournal>
```

**Passport CPJR:**
```xml
<NAXML-POSJournal>
  <JournalReport>
    <EventStartDate>2025-11-17</EventStartDate>
    <saleEvent>
      <TransactionDetailGroup>
        <TransactionLine>
          <ItemSalePrice>68.96</ItemSalePrice>
        </TransactionLine>
      </TransactionDetailGroup>
    </saleEvent>
  </JournalReport>
</NAXML-POSJournal>
```

Both are NAXML format - server parsers can be updated to handle both structures.

## Support

For issues:
1. Check logs in console output
2. Check `uploaded_files.json` for upload history
3. Check server Raw XML tab for upload status
4. Contact system administrator

## Next Steps

After deployment:
1. **Test**: Let it run for 24 hours and verify files upload
2. **Monitor**: Check Sales Analytics for data
3. **Verify**: Compare reports against POS totals
4. **Optimize**: Adjust `SCAN_INTERVAL` if needed (default 60s)
