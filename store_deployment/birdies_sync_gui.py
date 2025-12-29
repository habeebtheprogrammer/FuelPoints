#!/usr/bin/env python3
"""
Birdies Sales Sync - Simple GUI Application
No NSSM needed - just run this EXE!
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config_manager import ConfigManager
from sync_engine import SyncEngine

class BirdiesSyncGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Birdies Sales Sync")
        self.root.geometry("900x1000")
        self.root.resizable(True, True)
        
        # Start maximized to fit any screen size
        self.root.state('zoomed')
        
        self.config_manager = ConfigManager("config.json")
        self.config_manager.load()
        
        self.sync_thread = None
        self.is_syncing = False
        self.stop_sync_flag = False
        self.is_manual_sync_running = False
        self.is_sync_in_progress = False  # Shared flag to prevent any sync overlap
        
        # Store POS type mappings
        self.store_pos_types = {
            "0300": "verifone", "0400": "verifone", "0500": "verifone",
            "0710": "passport", "0800": "passport", "0900": "verifone",
            "1100": "passport", "1200": "passport", "1300": "verifone",
            "1310": "verifone", "1320": "verifone", "1330": "verifone",
            "1340": "passport", "1350": "verifone", "1360": "verifone",
            "1370": "passport", "1400": "passport", "1500": "passport",
            "1600": "verifone", "1700": "passport", "1810": "passport",
            "1900": "verifone", "2000": "passport", "2100": "verifone",
        }
        
        self.setup_ui()
        self.setup_logging()
        self.load_config()
        
    def setup_ui(self):
        """Create the GUI layout"""
        
        # Header
        header = tk.Frame(self.root, bg="#1E3A8A", height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        title_label = tk.Label(
            header,
            text="Birdies Sales Sync",
            font=("Arial", 18, "bold"),
            bg="#1E3A8A",
            fg="white"
        )
        title_label.pack(pady=15)
        
        # Main content frame
        content = tk.Frame(self.root, padx=20, pady=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        # Configuration Frame
        config_frame = ttk.LabelFrame(content, text="Configuration", padding=15)
        config_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Store Number
        row = 0
        ttk.Label(config_frame, text="Store Number:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.store_var = tk.StringVar()
        self.store_var.trace('w', self.on_store_changed)
        store_combo = ttk.Combobox(
            config_frame,
            textvariable=self.store_var,
            values=[
                "0300 - Lanham Sunoco",
                "0400 - Arena Sunoco",
                "0500 - Aspen Hill Citgo",
                "0710 - Brinkley Sunoco",
                "0800 - Enterprise Sunoco",
                "0900 - Highbridge Exxon",
                "1100 - Landmark Sunoco",
                "1200 - Landover Sunoco",
                "1300 - Charlotte Hall Shell",
                "1310 - Hollywood Shell",
                "1320 - Hugesville Corner Express",
                "1330 - Leonardtown Shell",
                "1340 - Mechanicsville Shell",
                "1350 - Korner Carryout",
                "1360 - Prince Frederick Shell",
                "1370 - 228 Shell",
                "1400 - Silver Hill",
                "1500 - Rosecroft",
                "1600 - Landover Shell",
                "1700 - South Dakota Sunoco",
                "1810 - Kenilworth Sunoco",
                "1900 - Twinbrook Sunoco",
                "2000 - Emmitsburg Exxon",
                "2100 - Edgewater Birdies",
            ],
            width=35
        )
        store_combo.grid(row=row, column=1, sticky=tk.W, pady=5)
        
        # POS Type
        row += 1
        ttk.Label(config_frame, text="POS Type:").grid(row=row, column=0, sticky=tk.W, pady=5)
        self.pos_type_var = tk.StringVar(value="verifone")
        self.pos_type_var.trace('w', self.on_pos_type_changed)
        pos_frame = tk.Frame(config_frame)
        pos_frame.grid(row=row, column=1, sticky=tk.W, pady=5)
        ttk.Radiobutton(pos_frame, text="Passport", variable=self.pos_type_var, value="passport").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(pos_frame, text="Verifone", variable=self.pos_type_var, value="verifone").pack(side=tk.LEFT, padx=5)
        
        # Passport Settings
        row += 1
        self.passport_frame = ttk.LabelFrame(config_frame, text="Passport Settings", padding=10)
        self.passport_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        ttk.Label(self.passport_frame, text="Network Path IP:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.passport_ip_var = tk.StringVar()
        ttk.Entry(self.passport_frame, textvariable=self.passport_ip_var, width=20).grid(row=0, column=1, sticky=tk.W, pady=3)
        ttk.Label(self.passport_frame, text="(e.g., 10.5.48.2) - will map to \\\\IP\\PPXMLData", font=("Arial", 8), foreground="gray").grid(row=1, column=1, sticky=tk.W)
        
        # Verifone Settings
        self.verifone_frame = ttk.LabelFrame(config_frame, text="Verifone Settings", padding=10)
        self.verifone_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        ttk.Label(self.verifone_frame, text="IP Address:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.vf_ip_var = tk.StringVar()
        ttk.Entry(self.verifone_frame, textvariable=self.vf_ip_var, width=20).grid(row=0, column=1, sticky=tk.W, pady=3)
        
        ttk.Label(self.verifone_frame, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.vf_user_var = tk.StringVar()
        ttk.Entry(self.verifone_frame, textvariable=self.vf_user_var, width=20).grid(row=1, column=1, sticky=tk.W, pady=3)
        
        ttk.Label(self.verifone_frame, text="Password:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.vf_pass_var = tk.StringVar()
        ttk.Entry(self.verifone_frame, textvariable=self.vf_pass_var, width=20, show="•").grid(row=2, column=1, sticky=tk.W, pady=3)
        
        # Sync Schedule Settings
        row += 1
        schedule_frame = ttk.LabelFrame(config_frame, text="Sync Schedule", padding=10)
        schedule_frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=10)
        
        # Daily sync time
        ttk.Label(schedule_frame, text="Daily Sync Time:").grid(row=0, column=0, sticky=tk.W, pady=3)
        time_frame = tk.Frame(schedule_frame)
        time_frame.grid(row=0, column=1, sticky=tk.W, pady=3)
        self.sync_hour_var = tk.StringVar(value="03")
        self.sync_minute_var = tk.StringVar(value="00")
        ttk.Entry(time_frame, textvariable=self.sync_hour_var, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        ttk.Entry(time_frame, textvariable=self.sync_minute_var, width=3).pack(side=tk.LEFT)
        ttk.Label(time_frame, text="(24-hour format, e.g., 03:00 for 3 AM)", font=("Arial", 8), foreground="gray").pack(side=tk.LEFT, padx=5)
        
        # Retry settings
        ttk.Label(schedule_frame, text="If files not ready:").grid(row=1, column=0, sticky=tk.W, pady=3)
        retry_label = tk.Label(schedule_frame, text="", font=("Arial", 8), foreground="gray")
        retry_label.grid(row=1, column=1, sticky=tk.W)
        
        ttk.Label(schedule_frame, text="Retry Interval:").grid(row=2, column=0, sticky=tk.W, pady=3)
        retry_frame = tk.Frame(schedule_frame)
        retry_frame.grid(row=2, column=1, sticky=tk.W, pady=3)
        self.retry_interval_var = tk.StringVar(value="60")
        ttk.Entry(retry_frame, textvariable=self.retry_interval_var, width=5).pack(side=tk.LEFT)
        ttk.Label(retry_frame, text="minutes").pack(side=tk.LEFT, padx=5)
        
        ttk.Label(schedule_frame, text="Max Retries:").grid(row=3, column=0, sticky=tk.W, pady=3)
        max_retry_frame = tk.Frame(schedule_frame)
        max_retry_frame.grid(row=3, column=1, sticky=tk.W, pady=3)
        self.max_retries_var = tk.StringVar(value="6")
        ttk.Entry(max_retry_frame, textvariable=self.max_retries_var, width=5).pack(side=tk.LEFT)
        ttk.Label(max_retry_frame, text="times (e.g., 6 retries = up to 6 hours)", font=("Arial", 8), foreground="gray").pack(side=tk.LEFT, padx=5)
        
        # Buttons
        row += 1
        button_frame = tk.Frame(config_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=10)
        
        ttk.Button(button_frame, text="Save Config", command=self.save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Test Connection", command=self.test_connection).pack(side=tk.LEFT, padx=5)
        
        # Status Frame
        status_frame = ttk.LabelFrame(content, text="Status", padding=15)
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.status_label = tk.Label(
            status_frame,
            text="Status: Stopped",
            font=("Arial", 12, "bold"),
            fg="gray"
        )
        self.status_label.pack()
        
        self.next_sync_label = tk.Label(
            status_frame,
            text="Next sync: Not scheduled",
            font=("Arial", 9),
            fg="#666"
        )
        self.next_sync_label.pack(pady=5)
        
        button_row = tk.Frame(status_frame)
        button_row.pack(pady=10)
        
        self.sync_button = ttk.Button(
            button_row,
            text="Start Scheduled Sync",
            command=self.toggle_sync
        )
        self.sync_button.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(
            button_row,
            text="Run Sync Now",
            command=self.run_sync_now
        ).pack(side=tk.LEFT, padx=5)
        
        # Auto-start checkbox
        self.autostart_var = tk.BooleanVar()
        ttk.Checkbutton(
            status_frame,
            text="Run on Windows startup",
            variable=self.autostart_var,
            command=self.toggle_autostart
        ).pack()
        
        # Log Frame
        log_frame = ttk.LabelFrame(content, text="Activity Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=12,
            width=70,
            font=("Consolas", 9),
            bg="#f8f9fa",
            fg="#212529"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Initially show correct settings
        self.on_pos_type_changed()
        
    def on_store_changed(self, *args):
        """Auto-select POS type when store is chosen"""
        store_text = self.store_var.get()
        if ' - ' in store_text:
            store_num = store_text.split(' - ')[0].strip()
            if store_num in self.store_pos_types:
                self.pos_type_var.set(self.store_pos_types[store_num])
        
    def on_pos_type_changed(self, *args):
        """Show/hide settings based on POS type"""
        pos_type = self.pos_type_var.get()
        
        if pos_type == 'passport':
            self.passport_frame.grid()
            self.verifone_frame.grid_remove()
        else:
            self.passport_frame.grid_remove()
            self.verifone_frame.grid()
    
    def setup_logging(self):
        """Setup logging to GUI text widget"""
        
        class GUIHandler(logging.Handler):
            def __init__(self, text_widget):
                super().__init__()
                self.text_widget = text_widget
                
            def emit(self, record):
                msg = self.format(record)
                def append():
                    self.text_widget.insert(tk.END, msg + '\n')
                    self.text_widget.see(tk.END)
                self.text_widget.after(0, append)
        
        # Setup logger
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        # Add GUI handler
        gui_handler = GUIHandler(self.log_text)
        gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', '%H:%M:%S'))
        logger.addHandler(gui_handler)
        
        # Also log to file
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_dir / f"sync_{datetime.now().strftime('%Y%m%d')}.log")
        file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(file_handler)
        
    def load_config(self):
        """Load saved configuration"""
        if self.config_manager.config:
            # Load store info
            store_num = self.config_manager.get('store.pdi_number', '')
            store_name = self.config_manager.get('store.name', '')
            if store_num:
                self.store_var.set(f"{store_num} - {store_name}" if store_name else store_num)
            
            # Load POS type
            pos_type = self.config_manager.get('store.pos_type', 'verifone')
            self.pos_type_var.set(pos_type)
            
            # Load Passport settings - extract IP from full path
            network_path = self.config_manager.get('passport.network_path', '')
            if network_path:
                # Extract IP from \\10.5.48.2\PPXMLData format
                network_path = network_path.replace('\\\\', '').replace('\\PPXMLData', '').replace('\\ppxmldata', '')
            self.passport_ip_var.set(network_path)
            
            # Load Verifone settings
            self.vf_ip_var.set(self.config_manager.get('verifone.api_url', '').replace('https://', ''))
            self.vf_user_var.set(self.config_manager.get('verifone.username', ''))
            self.vf_pass_var.set(self.config_manager.get('verifone.password', ''))
            
            # Load schedule settings
            sync_time = self.config_manager.get('sync.daily_sync_time', '03:00')
            if ':' in sync_time:
                hour, minute = sync_time.split(':')
                self.sync_hour_var.set(hour.zfill(2))
                self.sync_minute_var.set(minute.zfill(2))
            
            self.retry_interval_var.set(str(self.config_manager.get('sync.retry_interval_minutes', 60)))
            self.max_retries_var.set(str(self.config_manager.get('sync.max_retries', 6)))
            
            logging.info("Configuration loaded")
        
    def save_config(self):
        """Save configuration"""
        try:
            # Parse store number
            store_text = self.store_var.get()
            store_num = store_text.split(' - ')[0].strip() if ' - ' in store_text else store_text.strip()
            store_name = store_text.split(' - ')[1].strip() if ' - ' in store_text else ''
            
            if not store_num:
                messagebox.showerror("Error", "Please select a store number")
                return
            
            # Create or update config
            if not self.config_manager.config:
                self.config_manager.create_default(store_num, store_name, self.pos_type_var.get())
            
            # Update values
            self.config_manager.set('store.pdi_number', store_num)
            self.config_manager.set('store.name', store_name)
            pos_type = self.pos_type_var.get()
            self.config_manager.set('store.pos_type', pos_type)
            
            # Passport settings
            if pos_type == 'passport':
                passport_ip = self.passport_ip_var.get().strip()
                if not passport_ip:
                    messagebox.showerror("Error", "Please enter the network path IP for Passport")
                    return
                # Construct full path: \\IP\PPXMLData
                network_path = f"\\\\{passport_ip}\\PPXMLData"
                self.config_manager.set('passport.network_path', network_path)
            
            # Verifone settings
            elif pos_type == 'verifone':
                vf_ip = self.vf_ip_var.get().strip()
                vf_user = self.vf_user_var.get().strip()
                vf_pass = self.vf_pass_var.get().strip()
                
                if not all([vf_ip, vf_user, vf_pass]):
                    messagebox.showerror("Error", "Please enter IP address, username, and password for Verifone")
                    return
                
                self.config_manager.set('verifone.api_url', f"https://{vf_ip}")
                self.config_manager.set('verifone.username', vf_user)
                self.config_manager.set('verifone.password', vf_pass)
                self.config_manager.set('verifone.password_set_date', datetime.now().date().isoformat())
            
            # Sync schedule settings
            try:
                sync_hour = int(self.sync_hour_var.get())
                sync_minute = int(self.sync_minute_var.get())
                if 0 <= sync_hour <= 23 and 0 <= sync_minute <= 59:
                    sync_time = f"{sync_hour:02d}:{sync_minute:02d}"
                    self.config_manager.set('sync.daily_sync_time', sync_time)
                else:
                    messagebox.showerror("Error", "Invalid time format. Hour must be 0-23, minute must be 0-59")
                    return
            except ValueError:
                messagebox.showerror("Error", "Invalid time format. Please enter numbers only")
                return
            
            try:
                retry_interval = int(self.retry_interval_var.get())
                max_retries = int(self.max_retries_var.get())
                self.config_manager.set('sync.retry_interval_minutes', retry_interval)
                self.config_manager.set('sync.max_retries', max_retries)
            except ValueError:
                messagebox.showerror("Error", "Retry settings must be numbers")
                return
            
            # Save to file
            self.config_manager.save()
            
            messagebox.showinfo("Success", "Configuration saved!")
            logging.info("✓ Configuration saved")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
            logging.error(f"Failed to save config: {e}")
    
    def test_connection(self):
        """Test connection to POS"""
        try:
            pos_type = self.pos_type_var.get()
            
            if pos_type == 'verifone':
                from test_verifone_connection import test_verifone_connection
                
                ip = self.vf_ip_var.get().strip()
                username = self.vf_user_var.get().strip()
                password = self.vf_pass_var.get().strip()
                
                if not all([ip, username, password]):
                    messagebox.showerror("Error", "Please enter IP, username, and password")
                    return
                
                logging.info("Testing Verifone connection...")
                success, message, details = test_verifone_connection(ip, username, password)
                
                if success:
                    messagebox.showinfo("Success", "✓ Connection test passed!\n\nAll systems operational.")
                    logging.info("✓ Connection test passed")
                else:
                    messagebox.showerror("Connection Failed", f"Connection test failed:\n\n{message}")
                    logging.error(f"Connection test failed: {message}")
                    
            elif pos_type == 'passport':
                passport_ip = self.passport_ip_var.get().strip()
                
                if not passport_ip:
                    messagebox.showerror("Error", "Please enter the network path IP")
                    return
                
                # Construct full path
                network_path = f"\\\\{passport_ip}\\PPXMLData"
                logging.info(f"Testing Passport network path: {network_path}")
                
                # Test if path is accessible
                from pathlib import Path
                test_path = Path(network_path)
                
                if test_path.exists() and test_path.is_dir():
                    messagebox.showinfo("Success", f"✓ Network path is accessible!\n\nFull path: {network_path}")
                    logging.info("✓ Network path test passed")
                else:
                    messagebox.showerror("Connection Failed", f"Network path not accessible:\n\n{network_path}\n\nMake sure:\n1. The server {passport_ip} is reachable\n2. The PPXMLData share exists\n3. You have network permissions")
                    logging.error(f"Network path not accessible: {network_path}")
                
        except Exception as e:
            messagebox.showerror("Error", f"Connection test error: {e}")
            logging.error(f"Connection test error: {e}")
    
    def toggle_sync(self):
        """Start or stop sync"""
        if self.is_syncing:
            self.stop_sync()
        else:
            self.start_sync()
    
    def start_sync(self):
        """Start scheduled sync in background thread"""
        if not self.config_manager.is_valid():
            messagebox.showerror("Error", "Please configure and save settings first")
            return
        
        self.is_syncing = True
        self.stop_sync_flag = False
        
        self.status_label.config(text="Status: Waiting for scheduled time...", fg="orange")
        self.sync_button.config(text="Stop Scheduled Sync")
        
        logging.info("=== Scheduled Sync Started ===")
        
        # Start sync thread
        self.sync_thread = threading.Thread(target=self.sync_worker, daemon=True)
        self.sync_thread.start()
    
    def stop_sync(self):
        """Stop scheduled sync"""
        self.stop_sync_flag = True
        self.is_syncing = False
        
        self.status_label.config(text="Status: Stopped", fg="gray")
        self.sync_button.config(text="Start Scheduled Sync")
        self.next_sync_label.config(text="Next sync: Not scheduled")
        
        logging.info("=== Scheduled Sync Stopped ===")
    
    def run_sync_now(self):
        """Run sync immediately (manual trigger)"""
        if not self.config_manager.is_valid():
            messagebox.showerror("Error", "Please configure and save settings first")
            return
        
        # Prevent overlapping syncs (check both manual and scheduled syncs)
        if self.is_sync_in_progress:
            messagebox.showwarning("Sync In Progress", "A sync is already running. Please wait for it to complete.")
            return
        
        logging.info("=== Manual Sync Triggered ===")
        
        # Run in separate thread so GUI doesn't freeze
        def manual_sync():
            self.is_sync_in_progress = True
            try:
                def update_status():
                    self.status_label.config(text="Status: Syncing now...", fg="blue")
                self.root.after(0, update_status)
                
                engine = SyncEngine(self.config_manager)
                success = engine.sync()
                
                if success:
                    logging.info("✓ Manual sync completed successfully")
                    self.root.after(0, lambda: messagebox.showinfo("Success", "Sync completed successfully!"))
                else:
                    logging.error("✗ Manual sync failed")
                    self.root.after(0, lambda: messagebox.showerror("Error", "Sync failed. Check the activity log for details."))
                    
            except Exception as e:
                logging.error(f"Manual sync error: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", f"Sync error: {e}"))
            finally:
                self.is_sync_in_progress = False
                # Restore previous status
                def restore_status():
                    if self.is_syncing:
                        self.status_label.config(text="Status: Waiting for scheduled time...", fg="orange")
                    else:
                        self.status_label.config(text="Status: Stopped", fg="gray")
                self.root.after(0, restore_status)
        
        threading.Thread(target=manual_sync, daemon=True).start()
    
    def sync_worker(self):
        """Background scheduled sync worker with retry logic"""
        
        # Track if this is the first iteration (for catch-up logic)
        first_run = True
        
        while self.is_syncing and not self.stop_sync_flag:
            try:
                # Get schedule settings (reload each iteration to pick up config changes)
                sync_time = self.config_manager.get('sync.daily_sync_time', '03:00')
                retry_interval = self.config_manager.get('sync.retry_interval_minutes', 60)
                max_retries = self.config_manager.get('sync.max_retries', 6)
                
                # Calculate next sync time
                now = datetime.now()
                sync_hour, sync_minute = map(int, sync_time.split(':'))
                todays_sync = now.replace(hour=sync_hour, minute=sync_minute, second=0, microsecond=0)
                
                # Determine when to run next
                if first_run and todays_sync < now:
                    # First run and today's sync time already passed - run catch-up sync immediately
                    next_sync = now
                    logging.info("Catch-up sync: Today's scheduled time has passed, running immediately")
                    first_run = False
                elif todays_sync > now:
                    # Today's sync time hasn't happened yet
                    next_sync = todays_sync
                    first_run = False
                else:
                    # Today's sync already happened, schedule for tomorrow
                    next_sync = todays_sync + timedelta(days=1)
                    first_run = False
                
                # Update next sync label
                def update_label():
                    self.next_sync_label.config(text=f"Next sync: {next_sync.strftime('%Y-%m-%d %I:%M %p')}")
                self.root.after(0, update_label)
                
                logging.info(f"Next sync scheduled for: {next_sync.strftime('%Y-%m-%d %H:%M')}")
                
                # Wait until scheduled time (check every minute)
                while self.is_syncing and not self.stop_sync_flag and datetime.now() < next_sync:
                    time.sleep(60)  # Check every minute
                
                if self.stop_sync_flag:
                    break
                
                # Wait for any manual sync to complete before starting scheduled sync
                while self.is_sync_in_progress and self.is_syncing and not self.stop_sync_flag:
                    logging.info("Manual sync in progress, waiting before scheduled sync...")
                    time.sleep(5)  # Poll every 5 seconds
                
                if self.stop_sync_flag:
                    break
                
                # Run scheduled sync with retry logic
                logging.info("=== Running Scheduled Sync ===")
                
                self.is_sync_in_progress = True
                try:
                    def update_status():
                        self.status_label.config(text="Status: Running scheduled sync...", fg="blue")
                    self.root.after(0, update_status)
                    
                    success = False
                    retry_count = 0
                    
                    while not success and retry_count <= max_retries and self.is_syncing and not self.stop_sync_flag:
                        if retry_count > 0:
                            logging.info(f"Retry {retry_count}/{max_retries} after {retry_interval} minutes...")
                            # Wait for retry interval
                            for _ in range(retry_interval * 60):
                                if self.stop_sync_flag:
                                    break
                                time.sleep(1)
                            
                            if self.stop_sync_flag:
                                break
                        
                        # Run sync
                        engine = SyncEngine(self.config_manager)
                        success = engine.sync()
                        
                        if success:
                            logging.info("✓ Sync completed successfully")
                        else:
                            retry_count += 1
                            if retry_count <= max_retries:
                                logging.warning(f"✗ Sync failed. Will retry in {retry_interval} minutes... ({retry_count}/{max_retries})")
                            else:
                                logging.error(f"✗ Sync failed after {max_retries} retries. Giving up until tomorrow.")
                finally:
                    self.is_sync_in_progress = False
                    
                # Return to waiting state
                if self.is_syncing and not self.stop_sync_flag:
                    def update_status():
                        self.status_label.config(text="Status: Waiting for scheduled time...", fg="orange")
                    self.root.after(0, update_status)
                        
            except Exception as e:
                logging.error(f"Sync worker error: {e}")
                time.sleep(300)  # Wait 5 minutes on error
    
    def toggle_autostart(self):
        """Toggle Windows startup"""
        enabled = self.autostart_var.get()
        
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "BirdiesSalesSync"
            
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            
            if enabled:
                # Add to startup
                exe_path = sys.executable if getattr(sys, 'frozen', False) else __file__
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
                logging.info("✓ Added to Windows startup")
                messagebox.showinfo("Success", "App will now start automatically with Windows")
            else:
                # Remove from startup
                try:
                    winreg.DeleteValue(key, app_name)
                    logging.info("✓ Removed from Windows startup")
                    messagebox.showinfo("Success", "Removed from Windows startup")
                except FileNotFoundError:
                    pass
            
            winreg.CloseKey(key)
            
        except Exception as e:
            logging.error(f"Autostart error: {e}")
            messagebox.showerror("Error", f"Failed to update startup settings: {e}")

def main():
    root = tk.Tk()
    app = BirdiesSyncGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()
