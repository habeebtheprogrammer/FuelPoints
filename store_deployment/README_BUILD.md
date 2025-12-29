# Birdies Sales Sync - Build Instructions

## Overview

This unified executable syncs sales data from both **Gilbarco Passport** and **Verifone Ruby/Commander** POS systems to the Birdies backend.

## Files

- **birdies_sync.py** - Main application entry point
- **config_manager.py** - Configuration management
- **sync_engine.py** - Sync logic for both POS types
- **test_verifone_connection.py** - Connection testing utility
- **build_exe.py** - PyInstaller build script
- **requirements.txt** - Python dependencies

## Building the EXE

### Prerequisites

1. **Windows PC** with Python 3.8+ installed
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Build Steps

1. Navigate to the `store_deployment` directory:
   ```bash
   cd store_deployment
   ```

2. Run the build script:
   ```bash
   python build_exe.py
   ```

3. Find the EXE in `dist/BirdiesSalesSync.exe`

### Manual Build (alternative)

```bash
pyinstaller --onefile --name=BirdiesSalesSync --console birdies_sync.py
```

## Deployment

### First-Time Setup

1. Copy `BirdiesSalesSync.exe` to target PC (e.g., `C:\BirdiesSync\`)

2. Run setup wizard:
   ```bash
   BirdiesSalesSync.exe --setup
   ```

3. Follow prompts:
   - Enter PDI store number (1200, 1310, 1330, 1340)
   - Select POS type (Passport or Verifone)
   - Configure connection details
   - Set sync schedule

4. Test connection:
   ```bash
   BirdiesSalesSync.exe --test-connection
   ```

5. Run initial sync:
   ```bash
   BirdiesSalesSync.exe --run
   ```

### Install as Windows Service

#### Using NSSM (Recommended)

1. Download NSSM from https://nssm.cc/download

2. Install service:
   ```bash
   nssm install BirdiesSyncStore1330 "C:\BirdiesSync\BirdiesSalesSync.exe"
   nssm set BirdiesSyncStore1330 AppParameters "--service"
   nssm set BirdiesSyncStore1330 AppDirectory "C:\BirdiesSync"
   nssm set BirdiesSyncStore1330 Description "Birdies Sales Sync - Store 1330"
   nssm start BirdiesSyncStore1330
   ```

3. Verify service:
   ```bash
   nssm status BirdiesSyncStore1330
   ```

#### Manual Service Install

Or run in the background:
```bash
BirdiesSalesSync.exe --service
```

## Usage Commands

### Run Setup Wizard
```bash
BirdiesSalesSync.exe --setup
```

### Run Sync Once
```bash
BirdiesSalesSync.exe --run
```

### Run as Service (continuous loop)
```bash
BirdiesSalesSync.exe --service
```

### Show Status
```bash
BirdiesSalesSync.exe --status
```

### Test Connection
```bash
BirdiesSalesSync.exe --test-connection
```

### Custom Config File
```bash
BirdiesSalesSync.exe --config "custom_config.json" --run
```

## Configuration File

The setup wizard creates `config.json`:

```json
{
  "version": "1.0.0",
  "store": {
    "pdi_number": "1330",
    "name": "Hollywood",
    "pos_type": "verifone"
  },
  "verifone": {
    "api_url": "https://192.168.45.95",
    "username": "hollywood_api",
    "password": "encrypted_password",
    "verify_ssl": false,
    "password_set_date": "2025-11-23",
    "password_expiry_days": 90,
    "alert_thresholds": [30, 14, 7, 3]
  },
  "sync": {
    "initial_fetch_mode": "standard",
    "initial_fetch_days": 14,
    "interval_minutes": 15,
    "retry_attempts": 3,
    "retry_delay_minutes": 5
  },
  "backend": {
    "api_url": "https://salmanloyalty.replit.app",
    "upload_endpoint": "/api/sales/upload-xml",
    "timeout_seconds": 60
  },
  "logging": {
    "level": "INFO",
    "directory": "logs",
    "max_size_mb": 10,
    "retention_days": 30,
    "save_raw_xml": false,
    "xml_directory": "xml_archive"
  }
}
```

## Deployment Package

For each store, create a ZIP file:

```
BirdiesSync_Store1330.zip
├── BirdiesSalesSync.exe
├── nssm.exe (64-bit)
├── INSTALL.bat
├── UNINSTALL.bat
└── README.txt
```

### INSTALL.bat

```batch
@echo off
echo Installing Birdies Sales Sync Service...

:: Install service using NSSM
nssm.exe install BirdiesSyncStore1330 "%~dp0BirdiesSalesSync.exe"
nssm.exe set BirdiesSyncStore1330 AppParameters "--service"
nssm.exe set BirdiesSyncStore1330 AppDirectory "%~dp0"
nssm.exe set BirdiesSyncStore1330 Description "Birdies Sales Sync - Store 1330"
nssm.exe start BirdiesSyncStore1330

echo Service installed and started!
pause
```

### UNINSTALL.bat

```batch
@echo off
echo Removing Birdies Sales Sync Service...

nssm.exe stop BirdiesSyncStore1330
nssm.exe remove BirdiesSyncStore1330 confirm

echo Service removed!
pause
```

## Troubleshooting

### Connection Test Fails
```bash
BirdiesSalesSync.exe --test-connection
```
Check error messages for:
- Wrong IP address
- Incorrect credentials
- Firewall blocking connection
- SSL certificate issues

### View Logs
```bash
type logs\sync_20251123.log
```

### Password Expiry (Verifone)
The tool tracks password age and warns before expiration:
```bash
BirdiesSalesSync.exe --status
```

When password expires:
1. Reset password on Verifone POS
2. Update `config.json`:
   ```json
   "verifone": {
     "password": "new_password",
     "password_set_date": "2025-11-23"
   }
   ```
3. Restart service

### Manual Sync
```bash
BirdiesSalesSync.exe --run
```

### Check Service Status
```bash
nssm status BirdiesSyncStore1330
```

## POS Type Differences

### Gilbarco Passport
- **Access**: Network share (SMB)
- **Path**: `\\10.5.48.2\PPXMLData`
- **Lookback**: 7 days (network retention limit)
- **Files**: XML files in shared folder
- **No credentials** required (Windows auth)

### Verifone Ruby/Commander
- **Access**: HTTPS API
- **Endpoint**: `https://192.168.45.95/cgi-bin/CGILink`
- **Lookback**: 60 days (API retention)
- **Reports**: vfueltotals, vposjournal, vrubyrept/*
- **Credentials**: Username/password with cookie-based auth
- **Password**: Expires every 90 days

## Support

For issues:
1. Check logs in `logs/` directory
2. Run `--test-connection` to verify POS connectivity
3. Run `--status` to check configuration
4. Review `config.json` for correct settings

## Updates

To update the EXE:
1. Stop the service:
   ```bash
   nssm stop BirdiesSyncStore1330
   ```
2. Replace `BirdiesSalesSync.exe`
3. Start the service:
   ```bash
   nssm start BirdiesSyncStore1330
   ```
