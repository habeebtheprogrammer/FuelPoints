# Birdies Edge Agents

This folder contains the POS edge agent scripts for connecting Birdies locations to the loyalty backend.

## 📁 File Organization

### **Store-Specific Deployments (PRODUCTION)**

These files are configured for specific store locations and ready to deploy:

- **`hollywood_verifone.py`** - Hollywood location (PDI 1310)
  - POS Type: Verifone EPS Commander
  - Features: Amount-off promotions, points redemption, TCP keep-alive
  - Port: 9000

- **`mechanicsville_passport.py`** - Mechanicsville location (PDI 1340)
  - POS Type: Gilbarco Passport
  - Features: Multi-pack & amount-off promotions, points redemption
  - Port: 9000

### **Templates (FOR NEW STORES)**

Use these as starting points when adding new locations:

- **`passport_template.py`** - Template for Gilbarco Passport POS systems
  - Copy this file and update the store configuration section
  
- **`verifone_template.py`** - Template for Verifone EPS POS systems
  - Copy this file and update the store configuration section

## 🚀 Deployment Instructions

### 1. Copy to Store PC
Download the appropriate file for your location and copy to the store's edge PC.

### 2. Update Configuration (if needed)
Edit the configuration section at the top of the file:
```python
# Store / backend identity
PDI_STORE_NUMBER = "1310"  # Your store's PDI number
POS_ID = "24379"           # POS ID from backend
HOST = "0.0.0.0"           # Network interface to bind
PORT = 9000                # Loyalty port
```

### 3. Run the Edge Agent
```bash
python3 hollywood_verifone.py
# or
python3 mechanicsville_passport.py
```

### 4. Verify Connection
Check the logs for:
- ✓ TCP keep-alive configured (Verifone only)
- ✓ Heartbeat sent to backend
- ✓ Listening on 0.0.0.0:9000

## 📋 System Requirements

- Python 3.7+
- Network connectivity to backend: `https://salmanloyalty.replit.app`
- Direct network connection to POS (Passport or EPS Commander)
- Port 9000 available

## 🔧 Troubleshooting

**Connection Issues:**
- Verify firewall allows port 9000
- Check POS network configuration
- Ensure backend URL is accessible

**Promotion Not Applying:**
- Verify promotions are active in admin portal
- Check item group UPCs match POS format
- Review edge agent logs for API responses

**Points Not Working:**
- Confirm customer exists in backend
- Verify loyalty ID or phone number format
- Check points balance in admin portal

## 📚 Documentation

- **Passport POS Integration**: See `/docs` folder
- **Verifone EPS Integration**: See `attached_assets/EPS_Loyalty_Host_Implement_Guide_v102final 2_unlocked_1763665480604.pdf`
- **Backend API**: See `server/index.ts` for API endpoints
