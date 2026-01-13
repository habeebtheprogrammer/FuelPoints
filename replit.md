# Birdies Admin Portal

## Overview

The Birdies Admin Portal is a web-based system designed to manage a gas station loyalty program. It enables administrators to manage customers, store locations, item groups, and promotional offers. The system features a robust loyalty ID generation mechanism, integration with a PostgreSQL database, and a comprehensive sales analytics system for processing POS data. The project's ambition is to provide a central, efficient platform for managing loyalty and sales operations across Birdies gas stations.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions

The admin portal features a modern, professional UI with a left sidebar navigation, prominently displaying the Birdies logo and icon-labeled navigation buttons. It uses a deep blue primary color (#1E3A8A) for active states, card-based layouts, and includes a light/dark mode toggle. Modal dialogs are used for interactions, and error handling is comprehensive.

### Technical Implementations

The frontend is built with **React v19.1.0** and **Vite v7.1.9**, utilizing functional components and `fetch` API. The backend uses **Express v5.1.0**, **Drizzle ORM v0.44.6** with **Neon-backed PostgreSQL**, and a REST API for authentication.

### Customer Authentication

*   **New Users (Jan 2026+)**: Use 4-digit PIN for authentication
*   **Legacy Users**: Continue using password (bcrypt hashed)
*   **Login Flow**: System checks if user has PIN first, then falls back to password
*   **Required Fields**: First name, last name, phone, date of birth, zip code, PIN

### Feature Specifications

*   **Customer Management**: View customer data, loyalty IDs, points balances, and detailed purchase history with clickable transaction receipts.
*   **Rewards System**: Tracks points accumulation and transaction history (5 pts/$ earning, 100 pts = $1 redemption).
*   **Promotions Management**: Create flexible promotions including "Multi-Pack" (e.g., "2 for $5"), "Amount-Off" (e.g., "$1.80 off"), and "Buy X Get Y Free" options. Promotions can be loyalty-restricted, location-targeted, and date-ranged. Includes UPC conflict detection that warns admins when item groups contain UPCs already used in other promotions or punch cards.
*   **Punch Card Loyalty System**: Multi-visit reward program allowing customers to earn punches on specific item groups. Features include:
    *   Configurable punch cards linked to item groups (e.g., "Buy 10 coffees, get 1 free")
    *   Reward types: free item, percentage off, or dollar amount off
    *   Per-customer punch tracking with history
    *   POS integration endpoints for recording punches and redeeming rewards
    *   Admin dashboard with metrics (total punches, redemptions, customers close to reward)
    *   Isolated from existing loyalty points system to prevent breaking production
*   **Loyalty ID Generation**: GS1-128 compliant 22-digit IDs.
*   **Users Management**: CRUD operations for admin user accounts.
*   **Locations Management**: CRUD operations for store locations including PDI store number, POS ID, address, and POS type. Mobile app shows distance-sorted locations using Google Maps Geocoding API with server-side caching.
*   **POS Status Dashboard**: Real-time monitoring of online/offline status for all locations, with auto-refresh.
*   **Item Groups Management**: Create and manage item groups, linking with UPCs from a 19,023-item pricebook.
*   **Pricebook Management**: View and search product catalog by UPC or description.
*   **POS Loyalty Integration**: APIs for customer lookup, promotion evaluation, points calculation, and transaction finalization, supporting dual lookup and optional points redemption.
*   **Sales Analytics System**: Processes daily XML reports from Gilbarco Passport POS systems and Verifone Commander POS data.
    *   **Architecture**: Store-side Python ETL uploads raw XML, parsed server-side into analytics tables. Idempotent parsing logic for FGM, ISM, and MCM XML files ensures data integrity.
    *   **Features**: Raw XML storage, automatic parsing, flexible querying, aggregated sales summaries, and historical data retention.
    *   **Verifone Integration**: Comprehensive parser suite for Verifone Commander POS data (CPJR, FGM) with unified reporting, department category mapping (NACS standard), and support for all main sales reports.
*   **Birdies Loyalty Reports System**: Dedicated section for live TCP loyalty transaction reporting with 6 reports: Transactions, Failed Lookups, Promotion Usage, Points Activity, Customer Activity, Anomaly Alerts.

### System Design Choices

The architecture separates the frontend (React/Vite on port 5000) from the backend API (Express/Drizzle on port 3001), with API requests proxied by the frontend. Security is prioritized with hashed passwords. The system focuses solely on the web-based admin portal. Sales analytics are designed for robustness with idempotent XML processing.

### Verifone EPS Loyalty Edge Agent

The `store_deployment/verifone_workingedgecode.py` is the production-validated Verifone EPS Loyalty Host implementation, speaking PCATS XML over TCP. It handles `GetLoyaltyOnlineStatusRequest`, `GetRewardsRequest`, `FinalizeRewardsRequest`, `CancelTransactionRequest` by connecting to backend APIs for customer lookup, promotion evaluation, points calculation, and transaction finalization. It uses ticket-level `amountOff` discounts for reliable application.

### Verifone POS Management Utilities

Located in `store_deployment/verifone_utilities/`, these Python scripts provide direct POS management:
*   **pricebook_pull.py**: Retrieves the complete pricebook from Verifone Commander/Ruby via NAXML.
*   **pricebook_change.py**: Updates individual item prices on the POS using NAXML ItemMaintenance.
*   **promotion_pull.py**: Downloads all active promotions (MixMatch, Combo, ItemList) from the POS.

## External Dependencies

*   **Express**: v5.1.0
*   **Drizzle ORM**: v0.44.6
*   **@neondatabase/serverless**: v1.0.2
*   **TypeScript/TSX**
*   **cors**: v2.8.5
*   **bcrypt**
*   **React**: v19.1.0
*   **React DOM**: v19.1.0
*   **Vite**: v7.1.9
*   **@vitejs/plugin-react**: v5.0.4