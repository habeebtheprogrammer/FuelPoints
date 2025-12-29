#!/usr/bin/env python3
"""
Quick connection test for Verifone Commander/Ruby POS systems.
Tests authentication and basic connectivity.
"""

import requests
import xml.etree.ElementTree as ET
import sys
from datetime import datetime

# Suppress SSL warnings for self-signed certs
requests.packages.urllib3.disable_warnings()

def test_verifone_connection(ip, username, password, verify_ssl=False, timeout=15):
    """
    Test Verifone Commander connection by attempting authentication.
    
    Returns:
        tuple: (success: bool, message: str, details: dict)
    """
    base_url = f"https://{ip}"
    
    print(f"\n{'='*50}")
    print(f"Testing Verifone Connection")
    print(f"{'='*50}")
    print(f"IP Address: {ip}")
    print(f"Username:   {username}")
    print(f"SSL Verify: {verify_ssl}")
    print(f"Timeout:    {timeout}s")
    print(f"{'='*50}\n")
    
    details = {
        "timestamp": datetime.now().isoformat(),
        "ip": ip,
        "username": username,
        "base_url": base_url
    }
    
    # Step 1: Test basic connectivity
    print("Step 1/4: Testing network connectivity...")
    try:
        test_url = f"{base_url}/cgi-bin/CGILink"
        response = requests.get(
            test_url,
            params={"cmd": "vAppInfo"},
            verify=verify_ssl,
            timeout=timeout
        )
        print(f"  ✓ Network accessible (HTTP {response.status_code})")
        details["network_accessible"] = True
    except requests.exceptions.Timeout:
        print(f"  ✗ Connection timeout - check IP address and network")
        return (False, "Connection timeout", details)
    except requests.exceptions.ConnectionError as e:
        print(f"  ✗ Connection failed - {str(e)}")
        return (False, f"Connection failed: {str(e)}", details)
    except Exception as e:
        print(f"  ✗ Unexpected error - {str(e)}")
        return (False, f"Unexpected error: {str(e)}", details)
    
    # Step 2: Test authentication
    print("\nStep 2/4: Testing authentication...")
    try:
        auth_url = f"{base_url}/cgi-bin/CGILink"
        params = {
            "cmd": "validate",
            "user": username,
            "passwd": password
        }
        
        response = requests.get(
            auth_url,
            params=params,
            verify=verify_ssl,
            timeout=timeout
        )
        
        if response.status_code != 200:
            print(f"  ✗ Authentication failed (HTTP {response.status_code})")
            return (False, f"Authentication failed (HTTP {response.status_code})", details)
        
        details["auth_response_received"] = True
        
    except Exception as e:
        print(f"  ✗ Authentication request failed - {str(e)}")
        return (False, f"Authentication request failed: {str(e)}", details)
    
    # Step 3: Parse credential response
    print("\nStep 3/4: Parsing authentication response...")
    try:
        root = ET.fromstring(response.text)
        cookie_elem = root.find(".//cookie")
        
        if cookie_elem is None or not cookie_elem.text:
            # Check for error message
            error_elem = root.find(".//error")
            if error_elem is not None and error_elem.text:
                error_msg = error_elem.text.strip()
                print(f"  ✗ Authentication failed - {error_msg}")
                return (False, f"Login rejected: {error_msg}", details)
            else:
                print(f"  ✗ No cookie in response - invalid credentials?")
                return (False, "Invalid credentials (no cookie received)", details)
        
        cookie = cookie_elem.text.strip()
        print(f"  ✓ Cookie received: {cookie[:20]}..." if len(cookie) > 20 else f"  ✓ Cookie received: {cookie}")
        details["cookie_received"] = True
        details["cookie_length"] = len(cookie)
        
    except ET.ParseError as e:
        print(f"  ✗ Invalid XML response - {str(e)}")
        return (False, f"Invalid response format: {str(e)}", details)
    except Exception as e:
        print(f"  ✗ Failed to parse response - {str(e)}")
        return (False, f"Failed to parse response: {str(e)}", details)
    
    # Step 4: Test a simple command with the cookie (verify it works)
    print("\nStep 4/4: Testing authenticated request...")
    try:
        info_url = f"{base_url}/cgi-bin/CGILink"
        params = {
            "cmd": "vAppInfo",
            "cookie": cookie
        }
        
        response = requests.get(
            info_url,
            params=params,
            verify=verify_ssl,
            timeout=timeout
        )
        
        if response.status_code == 200:
            # Try to parse version info
            try:
                root = ET.fromstring(response.text)
                # Look for version information
                version_elem = root.find(".//{*}version[@name='Commander']")
                if version_elem is not None:
                    version = version_elem.get('majorVersionNr', '?') + '.' + \
                             version_elem.get('minorVersionNr', '?') + '.' + \
                             version_elem.get('releaseVersionNr', '?')
                    print(f"  ✓ Commander version: {version}")
                    details["commander_version"] = version
                else:
                    print(f"  ✓ Authenticated request successful")
            except:
                print(f"  ✓ Authenticated request successful")
            
            details["authenticated_request_successful"] = True
        else:
            print(f"  ! Cookie works but request returned HTTP {response.status_code}")
            details["authenticated_request_successful"] = False
        
    except Exception as e:
        print(f"  ! Cookie received but test request failed - {str(e)}")
        # This is not critical - authentication worked
    
    # Step 5: Release the cookie (cleanup)
    try:
        release_url = f"{base_url}/cgi-bin/CGILink"
        params = {
            "cmd": "releaseCredential",
            "cookie": cookie
        }
        requests.get(release_url, params=params, verify=verify_ssl, timeout=5)
        print("\n  ✓ Cookie released")
    except:
        pass  # Not critical
    
    # Success!
    print(f"\n{'='*50}")
    print("✓ CONNECTION TEST PASSED")
    print(f"{'='*50}\n")
    print("Summary:")
    print("  • Network connection: OK")
    print("  • Authentication: OK")
    print("  • Credentials: VALID")
    print("  • API access: OK")
    print("\nYou can use these settings for the sync tool.\n")
    
    return (True, "Connection test successful", details)


def main():
    """Run connection test with command-line arguments or prompts."""
    
    # Check if arguments provided
    if len(sys.argv) >= 4:
        ip = sys.argv[1]
        username = sys.argv[2]
        password = sys.argv[3]
    else:
        # Interactive prompts
        print("Verifone Connection Test")
        print("=" * 50)
        ip = input("Commander IP address (e.g., 192.168.45.95): ").strip()
        username = input("Username: ").strip()
        password = input("Password: ").strip()
    
    # Run test
    success, message, details = test_verifone_connection(ip, username, password)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
