#!/usr/bin/env python3
"""
Build script to create Windows EXE using PyInstaller
Optionally creates deployment package
"""

import os
import sys
import subprocess
from pathlib import Path

def build_exe(create_package=False):
    """Build executable using PyInstaller"""
    
    print("Building Birdies Sales Sync EXE...")
    print("=" * 60)
    
    # PyInstaller command
    # NOTE: We do NOT bundle NSSM with --add-binary
    # NSSM is included separately in the deployment package
    cmd = [
        'pyinstaller',
        '--onefile',                    # Single EXE file
        '--name=BirdiesSalesSync',      # Output name
        '--icon=NONE',                  # No icon (can add later)
        '--console',                    # Console application
        '--clean',                      # Clean build
        
        # Hidden imports
        '--hidden-import=requests',
        '--hidden-import=xml.etree.ElementTree',
        '--hidden-import=cryptography',
        
        # Main script
        'birdies_sync.py'
    ]
    
    print(f"Command: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd, check=True)
        
        print("\n" + "=" * 60)
        print("✓ Build completed successfully!")
        print("=" * 60)
        print("\nOutput:")
        print("  EXE: dist/BirdiesSalesSync.exe")
        
        exe_size = Path("dist/BirdiesSalesSync.exe").stat().st_size / (1024 * 1024)
        print(f"  Size: {exe_size:.2f} MB")
        
        print("\nUsage:")
        print("  BirdiesSalesSync.exe --setup      # Run setup wizard")
        print("  BirdiesSalesSync.exe --run        # Run sync once")
        print("  BirdiesSalesSync.exe --service    # Run as service")
        print("  BirdiesSalesSync.exe --status     # Show status")
        
        # Optionally create deployment package
        if create_package:
            print("\n" + "=" * 60)
            print("Creating deployment package...")
            print("=" * 60)
            from create_deployment_package import create_deployment_package
            create_deployment_package()
        else:
            print("\nTo create deployment package:")
            print("  python create_deployment_package.py")
        
        print()
        
        return 0
        
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Build failed: {e}")
        print("\nMake sure PyInstaller is installed:")
        print("  pip install pyinstaller")
        return 1
    except FileNotFoundError:
        print("\n✗ PyInstaller not found!")
        print("\nInstall it with:")
        print("  pip install pyinstaller")
        return 1

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', '-p', action='store_true',
                        help='Create deployment package after build')
    args = parser.parse_args()
    
    sys.exit(build_exe(create_package=args.package))
