# test_connection.py
# Simple script to test API connection and configuration

import os
import sys
from pathlib import Path

print("=" * 60)
print("Birdies Sales Data Collection - Connection Test")
print("=" * 60)
print()

# Test 1: Check Python version
print("1. Checking Python version...")
python_version = sys.version.split()[0]
print(f"   Python version: {python_version}")

major, minor = map(int, python_version.split('.')[:2])
if major >= 3 and minor >= 8:
    print("   ✓ Python version OK")
else:
    print("   ✗ Python 3.8+ required")
    sys.exit(1)

print()

# Test 2: Check dependencies
print("2. Checking dependencies...")
try:
    import requests
    print(f"   ✓ requests module installed (v{requests.__version__})")
except ImportError:
    print("   ✗ requests module not installed")
    print("   Run: pip install -r requirements.txt")
    sys.exit(1)

print()

# Test 3: Check configuration
print("3. Checking configuration...")
try:
    from config import PDI_STORE_NUMBER, API_BASE_URL, MAIN_FOLDER, PJR_FOLDER
    
    print(f"   PDI Store Number: {PDI_STORE_NUMBER}")
    
    if PDI_STORE_NUMBER == "1200":
        print("   ⚠ WARNING: PDI_STORE_NUMBER is still default (1200)")
        print("   Please edit config.py and set your actual store number")
    else:
        print("   ✓ PDI_STORE_NUMBER configured")
    
    print(f"   API URL: {API_BASE_URL}")
    print(f"   Main folder: {MAIN_FOLDER}")
    print(f"   PJR folder: {PJR_FOLDER}")
    
except Exception as e:
    print(f"   ✗ Error loading config: {e}")
    sys.exit(1)

print()

# Test 4: Check directories
print("4. Checking directories...")

dirs_to_check = [
    (r"C:\birdiesloyalty", "Data directory"),
    (r"C:\birdiesloyalty\sales_data", "Sales data directory"),
    (r"C:\birdiesloyalty\logs", "Logs directory")
]

for dir_path, description in dirs_to_check:
    if os.path.exists(dir_path):
        print(f"   ✓ {description}: {dir_path}")
    else:
        print(f"   ⚠ {description} does not exist: {dir_path}")
        print(f"     Creating...")
        try:
            os.makedirs(dir_path, exist_ok=True)
            print(f"     ✓ Created")
        except Exception as e:
            print(f"     ✗ Failed: {e}")

print()

# Test 5: Check network folders
print("5. Checking network folders...")

from config import MAIN_FOLDER, PJR_FOLDER

for folder in [MAIN_FOLDER, PJR_FOLDER]:
    if os.path.exists(folder):
        print(f"   ✓ Accessible: {folder}")
        try:
            files = os.listdir(folder)
            xml_files = [f for f in files if f.upper().endswith('.XML')]
            print(f"     Found {len(xml_files)} XML files")
        except Exception as e:
            print(f"     ⚠ Cannot list files: {e}")
    else:
        print(f"   ✗ Not accessible: {folder}")
        print(f"     Check network connectivity and permissions")

print()

# Test 6: Test API connection
print("6. Testing API connection...")

try:
    from send.api_client import test_connection
    
    if test_connection():
        print(f"   ✓ API is reachable: {API_BASE_URL}")
    else:
        print(f"   ✗ Cannot reach API: {API_BASE_URL}")
        print("     Check internet connection and API URL")

except Exception as e:
    print(f"   ✗ Error testing API: {e}")

print()
print("=" * 60)
print("Connection test complete!")
print("=" * 60)
print()
print("If all tests passed, you can run: python main.py")
print()
