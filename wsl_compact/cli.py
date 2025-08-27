"""
WSL Compact CLI - Command-line interface for WSL2 VHDX compaction

This module provides a command-line interface to the core compaction functionality.
It can be used for automation, scripting, or testing without the GUI.
"""

import argparse
import sys
from pathlib import Path

from .core import (
    compact_wsl_vhd, 
    get_default_distro, 
    get_vhd_for_distro, 
    is_windows, 
    is_admin,
    relaunch_elevated,
    log_message
)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="WSL Compact CLI - Compact WSL2 VHDX files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compact Ubuntu with default settings
  python -m wsl_compact.cli --distro Ubuntu --user ubuntu

  # Dry run to see what would happen
  python -m wsl_compact.cli --distro Ubuntu --user ubuntu --dry-run

  # Specify custom VHD path
  python -m wsl_compact.cli --distro Ubuntu --user ubuntu --vhd "C:\\Users\\user\\AppData\\Local\\Packages\\...\\ext4.vhdx"

  # Don't relaunch after compaction
  python -m wsl_compact.cli --distro Ubuntu --user ubuntu --no-relaunch

Note: This tool must be run with administrator privileges on Windows.
        """
    )
    
    parser.add_argument(
        "--distro", 
        default="Ubuntu",
        help="WSL distro name (default: Ubuntu)"
    )
    
    parser.add_argument(
        "--user", 
        default="ubuntu",
        help="Username to logout before compaction (default: ubuntu)"
    )
    
    parser.add_argument(
        "--vhd",
        help="Path to VHDX file (if not specified, auto-detect from registry)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what actions would be taken without executing them"
    )
    
    parser.add_argument(
        "--no-relaunch",
        action="store_true",
        help="Don't relaunch the distro after compaction"
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="WSL Compact CLI 1.0.0"
    )
    
    args = parser.parse_args()
    
    # Check if running on Windows
    if not is_windows():
        print("ERROR: This tool must run on Windows.", file=sys.stderr)
        return 1
    
    # Check for admin privileges (unless dry run)
    if not args.dry_run and not is_admin():
        print("ERROR: This tool requires administrator privileges.", file=sys.stderr)
        print("Please run as administrator or use --dry-run to simulate.", file=sys.stderr)
        return 1
    
    # Determine VHD path
    vhd_path = args.vhd
    if not vhd_path:
        try:
            vhd_path = str(get_vhd_for_distro(args.distro))
            log_message(f"Auto-detected VHD path: {vhd_path}")
        except Exception as e:
            print(f"ERROR: Could not auto-detect VHD for distro '{args.distro}': {e}", file=sys.stderr)
            print("Please specify the VHD path manually with --vhd", file=sys.stderr)
            return 1
    
    # Log startup
    if args.dry_run:
        log_message("[DRY-RUN MODE] No actual changes will be made")
    else:
        log_message("WSL Compact CLI started")
    
    # Perform compaction
    try:
        result = compact_wsl_vhd(
            distro=args.distro,
            username=args.user,
            vhd_path=vhd_path,
            relaunch_after=not args.no_relaunch,
            dry_run=args.dry_run
        )
        
        if result.success:
            log_message(f"SUCCESS: {result.message}")
            return 0
        else:
            log_message(f"FAILED: {result.message}")
            return 1
            
    except KeyboardInterrupt:
        log_message("Operation cancelled by user")
        return 130
    except Exception as e:
        log_message(f"UNEXPECTED ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
