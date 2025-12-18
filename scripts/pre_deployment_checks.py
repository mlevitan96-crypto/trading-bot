#!/usr/bin/env python3
"""
Pre-Deployment Safety Checks
Run this before deploying to validate system readiness.

Usage:
    python3 scripts/pre_deployment_checks.py [--env-file PATH] [--slot PATH]
    
Returns exit code 0 if all checks pass, 1 if deployment should be blocked.
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root to path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.deployment_safety_checks import run_deployment_checks


def main():
    parser = argparse.ArgumentParser(description="Pre-deployment safety checks")
    parser.add_argument("--env-file", type=str, help="Path to .env file")
    parser.add_argument("--slot", type=str, help="Deployment slot path (A or B)")
    
    args = parser.parse_args()
    
    # Determine .env file path
    if args.env_file:
        env_file = Path(args.env_file)
    elif args.slot:
        # If slot specified, check for .env in that slot
        slot_path = Path(args.slot)
        env_file = slot_path / ".env"
    else:
        # Default: use project root
        env_file = _project_root / ".env"
    
    print(f"📄 Using .env file: {env_file}")
    if not env_file.exists():
        print(f"⚠️  Warning: .env file not found at {env_file}")
        print("   Will use environment variables only\n")
    
    # Run checks
    results = run_deployment_checks(env_file if env_file.exists() else None)
    
    # Exit with appropriate code
    if results["passed"]:
        print("✅ Deployment checks passed - safe to proceed")
        return 0
    else:
        print("❌ Deployment checks failed - aborting deployment")
        return 1


if __name__ == "__main__":
    sys.exit(main())
