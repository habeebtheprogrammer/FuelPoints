# Birdies Loyalty Edge Agent - Integration Guide

## Overview

The edge agent provides POS integration for the Birdies loyalty program, connecting your Passport POS to the cloud backend for real-time customer lookup, points tracking, and transaction recording.

## ✅ What's Implemented

### 1. Customer Lookup (Both Methods)
- **Loyalty Barcode Scan**: Cashier scans 22-digit loyalty barcode
- **Phone Number Entry**: Cashier enters customer phone number
- **Real-time API Call**: Backend lookup via `/api/pos/customer-lookup`
- **Display**: Shows customer name and points balance on POS screen

### 2. Error Handling
- **Customer Not Found**: "Customer not found. Please sign up at birdies.com"
- **System Errors**: Graceful fallback with error messages
- **No Identifier**: "Customer ID Required" if neither barcode nor phone provided

### 3. Points Earning
- **Automatic Calculation**: 5 points per $1 of eligible merchandise (floor rounding)
- **Lottery Exclusion**: Lottery items excluded from points calculation
- **Transaction Recording**: All transactions saved to backend database
- **Receipt Display**: Shows points earned and new balance on receipt

### 4. Points Redemption (Optional - Customer Prompted)
- **Redemption Calculation**: Automatically calculates recommended redemption based on:
  - Customer's points balance (minimum 100 points)
  - Transaction subtotal
  - Spend gate formula: `floor(subtotal / 20)` 
  - Maximum: $10 per transaction
- **Customer Prompt**: POS displays prompt like "Redeem $3.00 for 300 pts?"
- **Customer Choice**:
  - **YES**: Discount applied automatically, points deducted
  - **NO**: No discount, prompt not shown again in same transaction
- **InstantRewardFlag="no"**: Makes redemption optional, not automatic

### 5. Transaction Finalization
- **Points Award**: Automatically awards points based on eligible subtotal
- **Points Redemption**: Deducts points if customer accepted redemption prompt
- **Receipt Lines**: 
  - Points Redeemed (if customer said YES)
  - Points Earned (always)
  - New Balance
  - Thank you message

### 6. Session Management
- **Customer Session**: Stores customer info from lookup to finalization
- **Auto-Cleanup**: Clears session on transaction complete or cancel
- **Thread-Safe**: Handles one customer transaction at a time

## 🔄 Transaction Flow

```
1. Cashier scans loyalty barcode OR enters phone number
   └─> Edge agent calls backend customer-lookup API
   └─> POS displays: "Welcome [Name]! Points Balance: [X]"

2. Cashier scans items (normal POS operation)
   └─> POS calculates totals
   └─> Edge agent calculates recommended redemption
   └─> POS displays prompt: "Redeem $3.00 for 300 pts?"
   └─> Customer chooses:
       • YES → Discount applied to transaction
       • NO → No discount, continue with transaction

3. Cashier completes tender
   └─> POS sends FinalizeRewardsRequest to edge agent
   └─> Edge agent:
       • Calculates eligible subtotal (excludes lottery)
       • Calls backend finalize-transaction API
       • Awards points: 5 pts per $1
       • Deducts redeemed points (if customer said YES)
       • Records transaction in database
   └─> Receipt prints with loyalty details
```

## 📋 Business Rules Enforced

✅ **Earning Rate**: 5 points per $1 (floor rounding) - automatic  
✅ **Redemption**: Customer chooses YES/NO when prompted - optional  
✅ **Redemption Rate**: 100 points = $1.00  
✅ **Spend Gate**: Redemption = floor(subtotal / 20), max $10  
✅ **Lottery Exclusion**: Lottery items don't earn points  
✅ **Tobacco/Alcohol**: Included (earns points)  
✅ **Transaction Recording**: All transactions saved with timestamps  

## ⚙️ Configuration

### Edge Agent Settings (edge_agent.py)

```python
# Store identification
PDI_STORE_NUMBER = "1340"     # Your PDI store number
POS_ID = "24379"              # Your POS ID
POS_TYPE = "Passport"         # Passport or Verifone

# Network settings
HOST = "10.96.10.175"         # Your PC's Passport NIC IP
PORT = 9000                   # Loyalty port (configured on Passport MWS)
EXPECTED_POS_IP = "10.5.50.2" # Your Passport POS IP

# Backend
BACKEND_URL = "https://your-replit-app.picard.replit.dev"
```

## 🚀 Deployment

### Prerequisites
- Python 3.7+ installed on back office computer
- Network connectivity to POS and internet
- Passport MWS configured with loyalty port 9000

### Installation

1. **Copy edge_agent.py to back office computer**
   ```
   C:\Birdies\edge_agent.py
   ```

2. **Install Python dependencies**
   ```bash
   pip install requests
   ```

3. **Configure settings** (edit edge_agent.py)
   - Update store number, POS ID, IP addresses
   - Verify backend URL

4. **Run edge agent**
   ```bash
   python edge_agent.py
   ```

5. **Verify heartbeat**
   - Should see "✓ Heartbeat sent to backend" every 15 seconds
   - Check POS Status tab in admin portal to see store online

### Expected Console Output

```
[2025-10-10 03:45:12] Starting Birdies Loyalty Edge Agent
[2025-10-10 03:45:12] Store: 1340 | POS Type: Passport | POS ID: 24379
[2025-10-10 03:45:12] Backend: https://...
[2025-10-10 03:45:12] Listening on 10.96.10.175:9000
[2025-10-10 03:45:12] ✓ Heartbeat thread started
[2025-10-10 03:45:12] ✓ Heartbeat sent to backend (Store 1340)
[2025-10-10 03:45:27] ✓ Heartbeat sent to backend (Store 1340)
[2025-10-10 03:45:45] POS connected from 10.5.50.2:52314
[2025-10-10 03:45:45] ✓ Heartbeat sent to backend (Store 1340)
[2025-10-10 03:45:47] ✓ Customer found: John Doe (175 pts)
[2025-10-10 03:46:15] ✓ Transaction finalized: Earned 47 pts, New balance: 222 pts
```

## 🔍 Troubleshooting

### Customer Lookup Issues
- **"Customer not found"**: Customer needs to sign up at birdies.com
- **"System Error"**: Check network connectivity to backend
- **No response**: Verify edge agent is running and POS IP is correct

### Points Not Awarded
- **Check eligible subtotal**: Lottery items excluded
- **Verify transaction ID**: Check backend logs for transaction recording
- **Review receipt**: Should show "Points Earned" line

### Connection Issues
- **POS not connecting**: Verify HOST and PORT settings match Passport MWS config
- **Heartbeat failing**: Check internet connectivity and backend URL
- **IP mismatch**: Update EXPECTED_POS_IP to match your POS

## 📊 Monitoring

### POS Status Dashboard
- Navigate to "POS Status" tab in admin portal
- Shows real-time online/offline status
- Displays last seen timestamp, edge version, IP addresses
- Auto-refreshes every 15 seconds

### Transaction History
- Navigate to "Customers" tab in admin portal
- Click "View" on any customer
- See complete purchase history with points earned/redeemed

## ⚠️ Current Limitations

### Promotion Evaluation
**Status**: Backend API ready, POS integration pending

The backend has `/api/pos/evaluate-promotions` API that can:
- Match basket items to "X for $Y" promotions
- Calculate multi-bundle discounts
- Filter by location and date

**Limitation**: Passport POS doesn't send basket items in GetRewardsRequest. This requires:
- POS configuration changes to send basket data
- OR manual promotion application by cashier
- OR promotions handled separately on POS

### Points Redemption Calculation
**Status**: Backend API ready, manual redemption working

The backend has `/api/pos/calculate-redemption` API that implements:
- Spend gate formula: `floor(subtotal / 20)`
- Max redemption: $10 per transaction
- Recommended redemption amount

**Limitation**: Requires POS to send subtotal during GetRewardsRequest. Currently:
- Cashier can manually apply points redemption on POS
- Edge agent tracks redemption and updates balance
- Backend enforces redemption limits when finalized

## 🔄 Future Enhancements

1. **Basket-Level Promotions**: Configure POS to send basket items for real-time promotion evaluation
2. **Auto-Redemption Prompts**: Configure POS to send subtotal for recommended redemption display
3. **Multi-Tender Support**: Handle split payments with points redemption
4. **Returns Processing**: Reverse points on returns/voids

## 📞 Support

For integration support:
1. Check edge agent console logs for detailed error messages
2. Review admin portal POS Status for connectivity issues
3. Test customer lookup via admin portal API endpoints
4. Verify network configuration and firewall rules
