# Birdies Loyalty Edge Agent Setup

## Overview
The Edge Agent runs on the back office computer at each store location. It:
- Handles POS connections (keeps loyalty online at the register)
- Sends heartbeat pings to the Birdies backend server
- Tracks which locations are online

## Prerequisites
- Python 3.7 or higher installed on the back office PC
- Network access to the POS register
- Internet connection to reach the Birdies backend server
- Install required Python package: `pip install requests`

## Installation Steps

### 1. Download the Edge Agent
Copy `edge_agent.py` to your back office computer (e.g., in `C:\Birdies\`)

### 2. Configure the Script
Edit `edge_agent.py` and update these settings:

```python
# Local POS connection settings
HOST = "10.96.10.175"   # Your PC's network IP (the one POS connects to)
PORT = 9000             # Keep as 9000 (Loyalty port on Passport)
EXPECTED_POS_IP = "10.5.50.2"   # Your POS register IP

# Store identification
PDI_STORE_NUMBER = "1340"  # Your PDI store number (e.g., "1340", not "01340")
POS_ID = "24379"           # Your POS ID from admin portal
POS_TYPE = "Passport"      # "Passport" or "Verifone"

# Backend server settings
BACKEND_URL = "https://your-replit-app.repl.co"  # Your Replit app URL
HEARTBEAT_INTERVAL = 15  # Send heartbeat every 15 seconds
```

### 3. Run the Edge Agent

**Option A: Run in Terminal (for testing)**
```bash
cd C:\Birdies
python edge_agent.py
```

**Option B: Run as Windows Service (recommended for production)**
Use a tool like NSSM (Non-Sucking Service Manager) to run the script as a Windows service:

1. Download NSSM from https://nssm.cc/download
2. Install as service:
   ```
   nssm install BirdiesEdgeAgent "C:\Python\python.exe" "C:\Birdies\edge_agent.py"
   ```
3. Start the service:
   ```
   nssm start BirdiesEdgeAgent
   ```

### 4. Verify It's Working

You should see output like:
```
[2025-10-09 12:00:00] Starting Birdies Loyalty Edge Agent
[2025-10-09 12:00:00] Store: 1340 | POS Type: Passport | POS ID: 24379
[2025-10-09 12:00:00] Backend: https://your-app.repl.co
[2025-10-09 12:00:00] Listening on 10.96.10.175:9000
[2025-10-09 12:00:00] ✓ Heartbeat thread started
[2025-10-09 12:00:15] ✓ Heartbeat sent to backend (Store 1340)
```

When the POS connects, you'll see:
```
[2025-10-09 12:01:00] POS connected from 10.5.50.2:xxxxx
[2025-10-09 12:01:00] ← Received from POS:
<GetLoyaltyOnlineStatusRequest>...
[2025-10-09 12:01:00] → Sent to POS:
<GetLoyaltyOnlineStatusResponse>...
[2025-10-09 12:01:00] ✓ Heartbeat sent to backend (Store 1340)
```

## Viewing Online Locations

In the admin portal, you can view which locations are online:
- Go to your backend URL + `/api/pos/presence`
- Or check the admin dashboard (coming soon)

## Troubleshooting

### POS Not Connecting
1. Check IP addresses are correct
2. Verify port 9000 is open on the PC firewall
3. Make sure Passport MWS has loyalty configured with correct IP:PORT

### Heartbeats Not Reaching Backend
1. Verify internet connection
2. Check BACKEND_URL is correct
3. Test with: `curl https://your-app.repl.co/api/pos/heartbeat -X POST`

### Python Errors
1. Install missing packages: `pip install requests`
2. Verify Python 3.7+ is installed: `python --version`

## Next Steps

Once the edge agent is running and showing online:
1. Test a transaction at the register with a loyalty card
2. The system will show as "online" in the backend
3. Future updates will add:
   - Customer lookup by phone/barcode
   - Real-time promotion evaluation
   - Points redemption
   - Transaction recording
