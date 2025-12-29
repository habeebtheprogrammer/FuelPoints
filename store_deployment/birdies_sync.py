#!/usr/bin/env python3
"""
Birdies Sales Sync - Unified EXE for Passport and Verifone POS systems
Main application entry point
"""

import sys
import os
import logging
import time
import argparse
from pathlib import Path
from datetime import datetime

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config_manager import ConfigManager
from sync_engine import SyncEngine
from test_verifone_connection import test_verifone_connection

# Application info
APP_NAME = "Birdies Sales Sync"
APP_VERSION = "1.0.0"

def setup_logging(config):
    """Setup logging based on configuration"""
    log_dir = Path(config.get('logging.directory', 'logs'))
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_level = config.get('logging.level', 'INFO')
    log_file = log_dir / f"sync_{datetime.now().strftime('%Y%m%d')}.log"
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger('birdies_sync')

def run_setup_wizard():
    """Interactive setup wizard"""
    print(f"\n{'='*60}")
    print(f"{APP_NAME} - Setup Wizard")
    print(f"Version {APP_VERSION}")
    print(f"{'='*60}\n")
    
    config = ConfigManager()
    
    # Store information
    print("Step 1: Store Information")
    print("-" * 60)
    store_number = input("PDI Store Number (e.g., 1200, 1310, 1330, 1340): ").strip()
    store_name = input("Store Name (optional, e.g., 'Mechanicsville'): ").strip()
    
    # POS type selection
    print("\nStep 2: POS System Type")
    print("-" * 60)
    print("1. Gilbarco Passport (network share)")
    print("2. Verifone Ruby/Commander (HTTP API)")
    pos_choice = input("Select POS type (1 or 2): ").strip()
    
    pos_type = 'passport' if pos_choice == '1' else 'verifone'
    
    # Create default config
    config.create_default(store_number, store_name, pos_type)
    
    # POS-specific configuration
    if pos_type == 'passport':
        print("\nStep 3: Passport Configuration")
        print("-" * 60)
        network_path = input(f"Network Path [{config.get('passport.network_path')}]: ").strip()
        if network_path:
            config.set('passport.network_path', network_path)
        
        lookback = input(f"Lookback days (1-7) [{config.get('passport.lookback_days')}]: ").strip()
        if lookback:
            config.set('passport.lookback_days', int(lookback))
    
    else:  # verifone
        print("\nStep 3: Verifone Configuration")
        print("-" * 60)
        api_ip = input("Commander IP address (e.g., 192.168.45.95): ").strip()
        username = input("Username: ").strip()
        password = input("Password: ").strip()
        
        config.set('verifone.api_url', f"https://{api_ip}")
        config.set('verifone.username', username)
        config.set('verifone.password', password)
        config.set('verifone.password_set_date', datetime.now().date().isoformat())
        
        # Test connection
        print("\nTesting connection...")
        success, message, details = test_verifone_connection(api_ip, username, password)
        
        if not success:
            print(f"\n⚠ Connection test failed: {message}")
            retry = input("Continue anyway? (y/n): ").strip().lower()
            if retry != 'y':
                print("Setup cancelled.")
                return False
    
    # Initial fetch strategy
    print("\nStep 4: Initial Data Fetch")
    print("-" * 60)
    print("1. Quick Start (3 days)")
    print("2. Standard (14 days) - Recommended")
    print("3. Full History (30 days)")
    fetch_choice = input("Select fetch strategy (1-3) [2]: ").strip() or '2'
    
    fetch_days_map = {'1': 3, '2': 14, '3': 30}
    config.set('sync.initial_fetch_days', fetch_days_map.get(fetch_choice, 14))
    
    # Sync interval
    print("\nStep 5: Sync Schedule")
    print("-" * 60)
    interval = input(f"Sync interval in minutes [{config.get('sync.interval_minutes')}]: ").strip()
    if interval:
        config.set('sync.interval_minutes', int(interval))
    
    # Backend API
    print("\nStep 6: Backend API")
    print("-" * 60)
    backend_url = input(f"API URL [{config.get('backend.api_url')}]: ").strip()
    if backend_url:
        config.set('backend.api_url', backend_url)
    
    # Save configuration
    config.save()
    
    print(f"\n{'='*60}")
    print("✓ Configuration saved successfully!")
    print(f"{'='*60}\n")
    print(f"Config file: {config.config_path.absolute()}")
    print(f"\nTo start syncing, run:")
    print(f"  {sys.argv[0]} --run")
    print(f"\nTo install as Windows service:")
    print(f"  {sys.argv[0]} --install-service")
    print()
    
    return True

def run_sync(config_manager):
    """Run sync operation"""
    log = setup_logging(config_manager)
    
    if not config_manager.is_valid():
        log.error("Invalid configuration. Run setup wizard first.")
        return False
    
    # Check password expiry for Verifone
    if config_manager.get('store.pos_type') == 'verifone':
        expiry_info = config_manager.check_password_expiry()
        if expiry_info and expiry_info['expired']:
            log.error("Verifone password has expired! Please reset and update config.")
            return False
        elif expiry_info and expiry_info['expires_in'] <= 7:
            log.warning(f"⚠ Verifone password expires in {expiry_info['expires_in']} days!")
    
    # Run sync
    engine = SyncEngine(config_manager)
    return engine.sync()

def run_service(config_manager):
    """Run as service (continuous loop)"""
    log = setup_logging(config_manager)
    
    log.info(f"{APP_NAME} v{APP_VERSION} starting...")
    log.info(f"Store: {config_manager.get('store.pdi_number')} - {config_manager.get('store.name')}")
    log.info(f"POS Type: {config_manager.get('store.pos_type')}")
    
    interval_minutes = config_manager.get('sync.interval_minutes', 15)
    
    while True:
        try:
            log.info("Starting sync cycle...")
            success = run_sync(config_manager)
            
            if success:
                log.info("Sync completed successfully")
            else:
                log.error("Sync failed")
            
            # Wait for next sync
            log.info(f"Next sync in {interval_minutes} minutes")
            time.sleep(interval_minutes * 60)
            
        except KeyboardInterrupt:
            log.info("Service stopped by user")
            break
        except Exception as e:
            log.error(f"Service error: {e}", exc_info=True)
            time.sleep(60)  # Wait 1 minute on error

def show_status(config_manager):
    """Show current status"""
    print(f"\n{APP_NAME} v{APP_VERSION}")
    print("=" * 60)
    
    if not config_manager.load():
        print("Status: Not configured")
        print("Run with --setup to configure")
        return
    
    print(f"Store: {config_manager.get('store.pdi_number')} - {config_manager.get('store.name')}")
    print(f"POS Type: {config_manager.get('store.pos_type')}")
    
    if config_manager.get('store.pos_type') == 'verifone':
        print(f"Verifone API: {config_manager.get('verifone.api_url')}")
        
        expiry_info = config_manager.check_password_expiry()
        if expiry_info:
            if expiry_info['expired']:
                print(f"Password: ❌ EXPIRED ({expiry_info['age_days']} days old)")
            elif expiry_info['expires_in'] <= 7:
                print(f"Password: ⚠ Expires in {expiry_info['expires_in']} days")
            else:
                print(f"Password: ✓ Valid ({expiry_info['expires_in']} days remaining)")
    else:
        print(f"Network Path: {config_manager.get('passport.network_path')}")
    
    print(f"Backend: {config_manager.get('backend.api_url')}")
    print(f"Sync Interval: {config_manager.get('sync.interval_minutes')} minutes")
    print("=" * 60)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    parser.add_argument('--run', action='store_true', help='Run sync once')
    parser.add_argument('--service', action='store_true', help='Run as service (continuous)')
    parser.add_argument('--status', action='store_true', help='Show status')
    parser.add_argument('--config', default='config.json', help='Config file path')
    parser.add_argument('--test-connection', action='store_true', help='Test POS connection')
    
    args = parser.parse_args()
    
    config = ConfigManager(args.config)
    
    # Setup wizard
    if args.setup:
        return 0 if run_setup_wizard() else 1
    
    # Load existing config
    if not config.load() and not args.status:
        print(f"No configuration found. Run with --setup first.")
        return 1
    
    # Status
    if args.status:
        show_status(config)
        return 0
    
    # Test connection
    if args.test_connection:
        if config.get('store.pos_type') == 'verifone':
            api_url = config.get('verifone.api_url')
            username = config.get('verifone.username')
            password = config.get('verifone.password')
            
            if api_url and username and password:
                ip = api_url.replace('https://', '').replace('http://', '')
                success, message, _ = test_verifone_connection(ip, username, password)
                return 0 if success else 1
            else:
                print("Verifone configuration incomplete")
                return 1
        else:
            print("Connection test only available for Verifone")
            return 1
    
    # Run sync
    if args.run:
        return 0 if run_sync(config) else 1
    
    # Run as service
    if args.service:
        run_service(config)
        return 0
    
    # No action specified
    parser.print_help()
    return 1

if __name__ == '__main__':
    sys.exit(main())
