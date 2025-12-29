#!/usr/bin/env python3
"""
Create complete deployment package for Birdies Sales Sync
Includes EXE, NSSM, scripts, and documentation
"""

import os
import sys
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

def create_deployment_package(store_number=None, output_dir="deployment_packages"):
    """Create a deployment ZIP package"""
    
    print("="*60)
    print("Birdies Sales Sync - Deployment Package Creator")
    print("="*60)
    print()
    
    # Check if EXE exists
    exe_path = Path("dist/BirdiesSalesSync.exe")
    if not exe_path.exists():
        print("✗ BirdiesSalesSync.exe not found in dist/")
        print("  Please build the EXE first: python build_exe.py")
        return False
    
    # Check if NSSM exists
    nssm_path = Path("nssm.exe")
    if not nssm_path.exists():
        print("⚠ nssm.exe not found")
        print("  Downloading NSSM...")
        from download_nssm import download_and_verify_nssm
        if not download_and_verify_nssm("."):
            print("✗ Failed to download NSSM")
            print("  Please download manually from https://nssm.cc")
            return False
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Determine package name
    if store_number:
        package_name = f"BirdiesSync_Store{store_number}"
    else:
        package_name = f"BirdiesSync_Universal"
    
    timestamp = datetime.now().strftime("%Y%m%d")
    zip_filename = f"{package_name}_{timestamp}.zip"
    zip_path = output_path / zip_filename
    
    print(f"Creating package: {zip_filename}")
    print()
    
    # Files to include
    files_to_include = {
        exe_path: "BirdiesSalesSync.exe",
        nssm_path: "nssm.exe",
        Path("INSTALL.bat"): "INSTALL.bat",
        Path("UNINSTALL.bat"): "UNINSTALL.bat",
        Path("download_nssm.py"): "download_nssm.py",  # Include for auto-download
    }
    
    # Create README
    readme_content = f"""Birdies Sales Sync - Installation Package
{'='*60}

Version: 1.0.0
Build Date: {datetime.now().strftime('%Y-%m-%d')}
{f'Store: {store_number}' if store_number else 'Universal Installer'}

INSTALLATION INSTRUCTIONS
{'='*60}

QUICK START:
  1. Extract all files to C:\\BirdiesSync\\
  2. Right-click INSTALL.bat
  3. Select "Run as Administrator"
  4. Follow setup wizard

FILES INCLUDED:
  • BirdiesSalesSync.exe  - Main sync application
  • nssm.exe              - Windows service installer
  • INSTALL.bat           - One-click installation
  • UNINSTALL.bat         - Service removal
  • download_nssm.py      - NSSM auto-downloader (backup)
  • README.txt            - This file

SYSTEM REQUIREMENTS:
  • Windows 10/11 or Windows Server 2016+
  • Network connectivity to POS and backend
  • Administrator privileges for service installation

SETUP WIZARD PROMPTS:
  • PDI Store Number (1200, 1310, 1330, 1340)
  • POS Type (Passport or Verifone)
  • Connection details (network path or IP/credentials)
  • Sync schedule (default: every 15 minutes)

VERIFICATION:
  After installation, check:
    BirdiesSalesSync.exe --status

TROUBLESHOOTING:
  • View logs: C:\\BirdiesSync\\logs\\
  • Test connection: BirdiesSalesSync.exe --test-connection
  • Manual sync: BirdiesSalesSync.exe --run

SUPPORT:
  Check logs first for detailed error messages.
  
{'='*60}
"""
    
    readme_path = Path("README_TEMP.txt")
    readme_path.write_text(readme_content)
    files_to_include[readme_path] = "README.txt"
    
    # Create ZIP
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for source, archive_name in files_to_include.items():
                if source.exists():
                    print(f"  Adding: {archive_name}")
                    zipf.write(source, archive_name)
                else:
                    print(f"  ⚠ Skipping (not found): {source}")
        
        # Clean up temp README
        if readme_path.exists():
            readme_path.unlink()
        
        # Get file size
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        
        print()
        print("="*60)
        print("✓ DEPLOYMENT PACKAGE CREATED")
        print("="*60)
        print(f"Package: {zip_path.absolute()}")
        print(f"Size: {size_mb:.2f} MB")
        print()
        print("NEXT STEPS:")
        print("  1. Copy ZIP to target PC")
        print("  2. Extract to C:\\BirdiesSync\\")
        print("  3. Run INSTALL.bat as Administrator")
        print()
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to create package: {e}")
        return False

def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Create deployment package")
    parser.add_argument('--store', '-s', help='Store number (optional, for labeling)')
    parser.add_argument('--output-dir', '-o', default='deployment_packages',
                        help='Output directory for ZIP files')
    
    args = parser.parse_args()
    
    success = create_deployment_package(args.store, args.output_dir)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
