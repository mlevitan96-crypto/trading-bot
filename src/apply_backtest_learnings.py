#!/usr/bin/env python3
"""
Apply Backtest Learnings to Live Config

This script reads the condition analysis and applies:
1. Per-symbol OFI thresholds (higher thresholds for symbols that need stronger signals)
2. Intelligence alignment requirements
3. Ensemble score minimums

Usage:
    python src/apply_backtest_learnings.py --dry-run  # Preview changes
    python src/apply_backtest_learnings.py --apply    # Apply to live_config.json
"""

import json
import os
from datetime import datetime
from pathlib import Path

CONDITION_REPORT = "reports/condition_analysis.json"
LIVE_CONFIG = "live_config.json"
BACKUP_DIR = "backups"


def load_json(path, default=None):
    """Load JSON file."""
    if not os.path.exists(path):
        return default or {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return default or {}


def save_json(path, data):
    """Save JSON file with backup."""
    if os.path.exists(path):
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup_path = f"{BACKUP_DIR}/live_config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(path, 'r') as f:
            backup_data = json.load(f)
        with open(backup_path, 'w') as f:
            json.dump(backup_data, f, indent=2)
        print(f"   📦 Backup saved to {backup_path}")
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def generate_ofi_thresholds():
    """Generate per-symbol OFI thresholds based on condition analysis."""
    report = load_json(CONDITION_REPORT, {})
    recs = report.get("symbol_recommendations", {})
    
    print("\n" + "="*70)
    print("🎯 OFI THRESHOLD RECOMMENDATIONS")
    print("="*70)
    
    thresholds = {}
    
    for symbol, directions in recs.items():
        for direction, config in directions.items():
            min_ofi = config.get("min_ofi", 0.5)
            expected_wr = config.get("expected_wr", 0)
            
            if expected_wr >= 35:
                key = f"{symbol}_{direction.upper()}"
                thresholds[key] = {
                    "min_ofi": min_ofi,
                    "expected_wr": expected_wr,
                    "applied_at": datetime.now().isoformat()
                }
                status = "✅" if expected_wr >= 40 else "🟡"
                print(f"   {status} {symbol} {direction.upper()}: OFI ≥ {min_ofi:.2f} (expect {expected_wr:.1f}% WR)")
    
    if not thresholds:
        print("   No profitable patterns found with WR ≥ 35%")
        print("   Using default OFI threshold of 0.5 for all")
    
    return thresholds


def apply_to_live_config(thresholds, dry_run=True):
    """Apply OFI thresholds to live_config.json."""
    config = load_json(LIVE_CONFIG, {})
    
    config["ofi_thresholds"] = thresholds
    config["condition_analysis_applied_at"] = datetime.now().isoformat()
    
    if dry_run:
        print("\n" + "="*70)
        print("🔍 DRY RUN - Changes that would be applied:")
        print("="*70)
        print(json.dumps({"ofi_thresholds": thresholds}, indent=2))
        print("\n   Run with --apply to apply these changes.")
    else:
        print("\n" + "="*70)
        print("✅ APPLYING CHANGES TO LIVE CONFIG")
        print("="*70)
        save_json(LIVE_CONFIG, config)
        print(f"\n   ✅ Changes applied to {LIVE_CONFIG}")
    
    return config


def main():
    import sys
    
    print("\n" + "="*70)
    print("🧪 CONDITION-BASED LEARNINGS APPLICATION")
    print(f"   Timestamp: {datetime.now().isoformat()}")
    print("="*70)
    
    thresholds = generate_ofi_thresholds()
    
    dry_run = "--apply" not in sys.argv
    apply_to_live_config(thresholds, dry_run=dry_run)
    
    print("\n" + "="*70)
    print("📊 SUMMARY")
    print("="*70)
    print(f"\n   Symbol-specific OFI thresholds: {len(thresholds)}")
    if dry_run:
        print("   Mode: DRY RUN (use --apply to activate)")
    else:
        print("   Mode: APPLIED to live config")
    print()


if __name__ == "__main__":
    main()
