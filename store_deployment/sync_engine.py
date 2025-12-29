#!/usr/bin/env python3
"""
Unified sync engine for both Passport and Verifone POS systems
"""

import os
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings()

log = logging.getLogger(__name__)

class SyncEngine:
    """Main sync engine that handles both POS types"""
    
    def __init__(self, config):
        self.config = config
        self.pos_type = config.get('store.pos_type')
        self.store_number = config.get('store.pdi_number')
        self.backend_url = config.get('backend.api_url')
        self.upload_endpoint = config.get('backend.upload_endpoint')
        
    def sync(self):
        """Run sync based on POS type"""
        log.info(f"Starting sync for store {self.store_number} ({self.pos_type})")
        
        try:
            if self.pos_type == 'passport':
                return self._sync_passport()
            elif self.pos_type == 'verifone':
                return self._sync_verifone()
            else:
                log.error(f"Unknown POS type: {self.pos_type}")
                return False
        except Exception as e:
            log.error(f"Sync failed: {e}", exc_info=True)
            return False
    
    def _sync_passport(self):
        """Sync from Gilbarco Passport (network share)"""
        log.info("Syncing from Passport network share")
        
        network_path = Path(self.config.get('passport.network_path'))
        pjr_path = Path(self.config.get('passport.pjr_path'))
        lookback_days = self.config.get('passport.lookback_days', 7)
        
        # Check if network path is accessible
        if not network_path.exists():
            log.error(f"Network path not accessible: {network_path}")
            return False
        
        files_uploaded = 0
        errors = 0
        
        # Find XML files from the last N days
        cutoff_date = datetime.now() - timedelta(days=lookback_days)
        
        # Scan for XML files
        for xml_file in network_path.glob('**/*.xml'):
            try:
                # Check file modification time
                mtime = datetime.fromtimestamp(xml_file.stat().st_mtime)
                if mtime < cutoff_date:
                    continue
                
                # Upload to backend
                if self._upload_xml_file(xml_file):
                    files_uploaded += 1
                else:
                    errors += 1
                    
            except Exception as e:
                log.error(f"Error processing {xml_file}: {e}")
                errors += 1
        
        log.info(f"Passport sync complete: {files_uploaded} uploaded, {errors} errors")
        return errors == 0
    
    def _sync_verifone(self):
        """Sync from Verifone Commander (HTTP API)"""
        log.info("Syncing from Verifone Commander API")
        
        api_url = self.config.get('verifone.api_url')
        username = self.config.get('verifone.username')
        password = self.config.get('verifone.password')
        verify_ssl = self.config.get('verifone.verify_ssl', False)
        
        # Get authentication cookie
        cookie = self._verifone_authenticate(api_url, username, password, verify_ssl)
        if not cookie:
            log.error("Verifone authentication failed")
            return False
        
        try:
            files_uploaded = 0
            errors = 0
            
            # Determine which files to fetch
            lookback_days = self.config.get('sync.initial_fetch_days', 14)
            
            # Fetch different report types
            reports_to_fetch = [
                ('vfueltotals', {}, 'FGM'),                          # Fuel totals
                ('vrubyrept', {'reptname': 'plu'}, 'ISM'),          # Item sales (PLU)
                ('vrubyrept', {'reptname': 'category'}, 'MCM'),     # Category sales
                ('vposjournal', {}, 'CPJR'),                        # Transaction journal
            ]
            
            for report_cmd, extra_params, report_type in reports_to_fetch:
                try:
                    xml_content = self._verifone_fetch_report(
                        api_url, cookie, report_cmd, extra_params, verify_ssl
                    )
                    
                    if xml_content:
                        # Upload to backend
                        if self._upload_xml_content(xml_content, report_type):
                            files_uploaded += 1
                        else:
                            errors += 1
                except Exception as e:
                    log.error(f"Error fetching {report_type}: {e}")
                    errors += 1
            
            log.info(f"Verifone sync complete: {files_uploaded} uploaded, {errors} errors")
            return errors == 0
            
        finally:
            # Release cookie
            self._verifone_release_cookie(api_url, cookie, verify_ssl)
    
    def _verifone_authenticate(self, api_url, username, password, verify_ssl):
        """Get Verifone authentication cookie"""
        try:
            url = f"{api_url}/cgi-bin/CGILink"
            params = {
                'cmd': 'validate',
                'user': username,
                'passwd': password
            }
            
            response = requests.get(url, params=params, verify=verify_ssl, timeout=30)
            response.raise_for_status()
            
            root = ET.fromstring(response.text)
            cookie_elem = root.find('.//cookie')
            
            if cookie_elem is not None and cookie_elem.text:
                return cookie_elem.text.strip()
            
            return None
        except Exception as e:
            log.error(f"Authentication failed: {e}")
            return None
    
    def _verifone_release_cookie(self, api_url, cookie, verify_ssl):
        """Release Verifone authentication cookie"""
        try:
            url = f"{api_url}/cgi-bin/CGILink"
            params = {
                'cmd': 'releaseCredential',
                'cookie': cookie
            }
            requests.get(url, params=params, verify=verify_ssl, timeout=10)
        except:
            pass
    
    def _verifone_fetch_report(self, api_url, cookie, report_cmd, extra_params, verify_ssl):
        """Fetch a report from Verifone"""
        try:
            url = f"{api_url}/cgi-bin/CGILink"
            params = {
                'cmd': report_cmd,
                'cookie': cookie
            }
            
            # Add extra parameters (e.g., reptname for vrubyrept)
            params.update(extra_params)
            
            response = requests.get(url, params=params, verify=verify_ssl, timeout=60)
            response.raise_for_status()
            
            return response.text
        except Exception as e:
            log.error(f"Error fetching {report_cmd}: {e}")
            return None
    
    def _upload_xml_file(self, xml_path):
        """Upload XML file to backend"""
        try:
            with open(xml_path, 'rb') as f:
                files = {
                    'file': (xml_path.name, f, 'application/xml')
                }
                data = {
                    'storeNumber': self.store_number,
                    'posType': self.pos_type
                }
                
                url = f"{self.backend_url}{self.upload_endpoint}"
                timeout = self.config.get('backend.timeout_seconds', 60)
                
                response = requests.post(url, files=files, data=data, timeout=timeout)
                response.raise_for_status()
                
                log.info(f"Uploaded: {xml_path.name}")
                return True
        except Exception as e:
            log.error(f"Upload failed for {xml_path.name}: {e}")
            return False
    
    def _upload_xml_content(self, xml_content, report_type):
        """Upload XML content to backend"""
        try:
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{self.store_number}_{report_type}_{timestamp}.xml"
            
            files = {
                'file': (filename, xml_content.encode('utf-8'), 'application/xml')
            }
            data = {
                'storeNumber': self.store_number,
                'posType': self.pos_type
            }
            
            url = f"{self.backend_url}{self.upload_endpoint}"
            timeout = self.config.get('backend.timeout_seconds', 60)
            
            response = requests.post(url, files=files, data=data, timeout=timeout)
            response.raise_for_status()
            
            log.info(f"Uploaded: {filename}")
            return True
        except Exception as e:
            log.error(f"Upload failed for {report_type}: {e}")
            return False
