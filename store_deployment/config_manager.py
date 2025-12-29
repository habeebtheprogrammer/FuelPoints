#!/usr/bin/env python3
"""
Configuration management for Birdies Sales Sync
"""

import json
import os
from pathlib import Path
from datetime import datetime
from cryptography.fernet import Fernet
import base64

class ConfigManager:
    """Manages configuration for the sync tool"""
    
    DEFAULT_CONFIG = {
        "version": "1.0.0",
        "store": {
            "pdi_number": "",
            "name": "",
            "pos_type": ""  # "passport" or "verifone"
        },
        "passport": {
            "network_path": "\\\\10.5.48.2\\PPXMLData",
            "pjr_path": "\\\\10.5.48.2\\PPXMLData\\PJR",
            "lookback_days": 7
        },
        "verifone": {
            "api_url": "",
            "username": "",
            "password": "",
            "verify_ssl": False,
            "password_set_date": "",
            "password_expiry_days": 90,
            "alert_thresholds": [30, 14, 7, 3]
        },
        "sync": {
            "initial_fetch_mode": "standard",
            "initial_fetch_days": 14,
            "daily_sync_time": "03:00",
            "retry_interval_minutes": 60,
            "max_retries": 6
        },
        "backend": {
            "api_url": "https://salmanloyalty.replit.app",
            "upload_endpoint": "/api/sales/upload-xml",
            "timeout_seconds": 60
        },
        "alerts": {
            "email_enabled": False,
            "email_address": "",
            "alert_on_password_expiry": True,
            "alert_on_sync_failure": True
        },
        "logging": {
            "level": "INFO",
            "directory": "logs",
            "max_size_mb": 10,
            "retention_days": 30,
            "save_raw_xml": False,
            "xml_directory": "xml_archive"
        },
        "service": {
            "name": "",
            "display_name": "",
            "description": "",
            "auto_start": True
        }
    }
    
    def __init__(self, config_path="config.json"):
        self.config_path = Path(config_path)
        self.config = None
        self._encryption_key = None
        
    def load(self):
        """Load configuration from file"""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            return True
        return False
    
    def save(self):
        """Save configuration to file"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def create_default(self, store_number, store_name, pos_type):
        """Create default configuration"""
        self.config = self.DEFAULT_CONFIG.copy()
        self.config["store"]["pdi_number"] = store_number
        self.config["store"]["name"] = store_name
        self.config["store"]["pos_type"] = pos_type
        
        # Set service name based on store
        self.config["service"]["name"] = f"BirdiesSyncStore{store_number}"
        self.config["service"]["display_name"] = f"Birdies Sales Sync - {store_name} ({store_number})"
        self.config["service"]["description"] = f"Automated sales data sync for Birdies store {store_number}"
        
    def get(self, key_path, default=None):
        """Get config value by dot-notation path (e.g., 'store.pdi_number')"""
        if not self.config:
            return default
        
        keys = key_path.split('.')
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def set(self, key_path, value):
        """Set config value by dot-notation path"""
        if not self.config:
            self.config = self.DEFAULT_CONFIG.copy()
        
        keys = key_path.split('.')
        config = self.config
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        config[keys[-1]] = value
    
    def encrypt_password(self, password):
        """Encrypt password for storage"""
        if not self._encryption_key:
            # Use machine-specific key (simplified for demo)
            self._encryption_key = Fernet.generate_key()
        
        f = Fernet(self._encryption_key)
        return f.encrypt(password.encode()).decode()
    
    def decrypt_password(self, encrypted_password):
        """Decrypt password"""
        if not self._encryption_key:
            return encrypted_password
        
        try:
            f = Fernet(self._encryption_key)
            return f.decrypt(encrypted_password.encode()).decode()
        except:
            return encrypted_password
    
    def check_password_expiry(self):
        """Check if Verifone password is expiring soon"""
        if self.get('store.pos_type') != 'verifone':
            return None
        
        set_date_str = self.get('verifone.password_set_date')
        if not set_date_str:
            return None
        
        try:
            set_date = datetime.fromisoformat(set_date_str)
            expiry_days = self.get('verifone.password_expiry_days', 90)
            age_days = (datetime.now() - set_date).days
            expires_in = expiry_days - age_days
            
            return {
                'set_date': set_date,
                'age_days': age_days,
                'expires_in': expires_in,
                'expired': expires_in <= 0
            }
        except:
            return None
    
    def is_valid(self):
        """Check if configuration is valid"""
        if not self.config:
            return False
        
        # Check required fields
        if not self.get('store.pdi_number'):
            return False
        if not self.get('store.pos_type') in ['passport', 'verifone']:
            return False
        
        # Check POS-specific settings
        pos_type = self.get('store.pos_type')
        if pos_type == 'verifone':
            if not self.get('verifone.api_url'):
                return False
            if not self.get('verifone.username'):
                return False
            if not self.get('verifone.password'):
                return False
        
        return True
