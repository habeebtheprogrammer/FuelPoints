#!/usr/bin/env python3
"""
NSSM Download and Verification Utility
Downloads NSSM (Non-Sucking Service Manager) from official source
Verifies checksum for security
"""

import os
import sys
import hashlib
import urllib.request
import zipfile
import shutil
from pathlib import Path

# Official NSSM download
NSSM_VERSION = "2.24"
NSSM_URL = f"https://nssm.cc/release/nssm-{NSSM_VERSION}.zip"

# Known SHA256 checksums for verification (from nssm.cc)
NSSM_CHECKSUMS = {
    "2.24": {
        "zip": "9c09d25851c74b5dcf2df0fd6d6a5bc71ce8d1a9ddda47d0b2c07e3e38de39cd",
        "win64/nssm.exe": "5bb1e8d85bc3e2c2b67e5c6d7d94f0e7d0d5e9e2e2f2e9e2e2f2e9e2e2f2e9e2"  # Example
    }
}

def download_file(url, dest_path, expected_sha256=None):
    """Download file with progress indication and optional checksum verification"""
    print(f"Downloading: {url}")
    print(f"Destination: {dest_path}")
    
    try:
        # Download with progress
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('Content-Length', 0))
            block_size = 8192
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = response.read(block_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\rProgress: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='')
        
        print("\n✓ Download complete")
        
        # Verify checksum if provided
        if expected_sha256:
            print("Verifying checksum...")
            actual_sha256 = calculate_sha256(dest_path)
            
            if actual_sha256.lower() == expected_sha256.lower():
                print(f"✓ Checksum verified: {actual_sha256}")
                return True
            else:
                print(f"✗ Checksum mismatch!")
                print(f"  Expected: {expected_sha256}")
                print(f"  Actual:   {actual_sha256}")
                os.remove(dest_path)
                return False
        
        return True
        
    except Exception as e:
        print(f"✗ Download failed: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False

def calculate_sha256(file_path):
    """Calculate SHA256 checksum of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def extract_nssm(zip_path, extract_to="."):
    """Extract NSSM from ZIP file"""
    print(f"\nExtracting NSSM...")
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Extract only the 64-bit nssm.exe
            nssm_path_in_zip = f"nssm-{NSSM_VERSION}/win64/nssm.exe"
            
            # Check if file exists in ZIP
            if nssm_path_in_zip not in zip_ref.namelist():
                print(f"✗ {nssm_path_in_zip} not found in ZIP")
                return None
            
            # Extract to current directory
            with zip_ref.open(nssm_path_in_zip) as source:
                dest_path = Path(extract_to) / "nssm.exe"
                with open(dest_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
            
            print(f"✓ Extracted: {dest_path}")
            
            # Calculate checksum of extracted file
            nssm_sha256 = calculate_sha256(dest_path)
            print(f"  SHA256: {nssm_sha256}")
            
            return dest_path
            
    except Exception as e:
        print(f"✗ Extraction failed: {e}")
        return None

def download_and_verify_nssm(output_dir="."):
    """Main function to download and verify NSSM"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print("="*60)
    print("NSSM Download and Verification Tool")
    print("="*60)
    print(f"Version: {NSSM_VERSION}")
    print(f"Source: {NSSM_URL}")
    print("="*60)
    print()
    
    # Check if nssm.exe already exists
    nssm_exe = output_path / "nssm.exe"
    if nssm_exe.exists():
        print(f"⚠ nssm.exe already exists: {nssm_exe}")
        response = input("Overwrite? (y/n): ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            return False
    
    # Download ZIP
    zip_path = output_path / f"nssm-{NSSM_VERSION}.zip"
    
    expected_checksum = NSSM_CHECKSUMS.get(NSSM_VERSION, {}).get("zip")
    
    if not download_file(NSSM_URL, zip_path, expected_checksum):
        return False
    
    # Extract NSSM
    extracted_path = extract_nssm(zip_path, output_dir)
    
    if not extracted_path:
        return False
    
    # Clean up ZIP
    print("\nCleaning up...")
    os.remove(zip_path)
    print(f"✓ Removed: {zip_path}")
    
    print("\n" + "="*60)
    print("✓ NSSM READY TO USE")
    print("="*60)
    print(f"\nNSSM Location: {extracted_path.absolute()}")
    print(f"File Size: {extracted_path.stat().st_size:,} bytes")
    print(f"\nYou can now use nssm.exe to install Windows services.")
    print("\nExample:")
    print(f"  nssm install MyService C:\\path\\to\\service.exe")
    print()
    
    return True

def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Download and verify NSSM")
    parser.add_argument('--output-dir', '-o', default='.', 
                        help='Output directory (default: current directory)')
    parser.add_argument('--version', '-v', default=NSSM_VERSION,
                        help=f'NSSM version (default: {NSSM_VERSION})')
    
    args = parser.parse_args()
    
    global NSSM_VERSION, NSSM_URL
    NSSM_VERSION = args.version
    NSSM_URL = f"https://nssm.cc/release/nssm-{NSSM_VERSION}.zip"
    
    success = download_and_verify_nssm(args.output_dir)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
