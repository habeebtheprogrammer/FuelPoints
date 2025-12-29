# Birdies Rewards Mobile App

A modern React Native (Expo) mobile app for the Birdies loyalty program.

## Features

- **Phone Login**: Customers sign in with their registered phone number
- **Points Dashboard**: View current points balance and equivalent dollar value
- **Punch Cards**: Track punch card progress and rewards
- **Digital Barcode**: Code 128 barcode for scanning at checkout (10-12 digit numeric loyalty ID)
- **Transaction History**: View past purchases and points activity
- **Profile Management**: View account details and settings

## Getting Started

### Prerequisites

- Node.js 18+
- Expo CLI: `npm install -g expo-cli`
- Expo Go app on your phone (for testing)

### Installation

```bash
cd mobile
npm install
```

### Running the App

```bash
# Start development server
npm start

# Run on iOS simulator
npm run ios

# Run on Android emulator
npm run android
```

### Testing on Physical Device

1. Download "Expo Go" from App Store / Google Play
2. Run `npm start` in the mobile directory
3. Scan the QR code with Expo Go

## Tech Stack

- **Expo SDK 52**
- **expo-router** - File-based navigation
- **expo-linear-gradient** - Beautiful gradient UI
- **react-native-barcode-builder** - Code 128 barcode generation
- **AsyncStorage** - Local session persistence

## API Integration

The app connects to the Birdies backend at `https://salmanloyalty.replit.app`:

- `POST /api/pos/customer-lookup` - Login with phone number
- `GET /api/punch-cards/customer/:id` - Fetch punch card status
- `GET /api/transactions/customer/:id` - Fetch transaction history

## Barcode Format

- **Symbology**: Code 128
- **Content**: 10-12 digit numeric loyalty ID
- **Source**: Customer's `loyaltyId` field from the database
