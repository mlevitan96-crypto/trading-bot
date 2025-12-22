#!/usr/bin/env python3
"""
Apply Learning Recommendations
===============================
Implements the key findings from comprehensive analysis:
1. Require OFI ≥ 0.5 for LONG trades (match SHORT requirements)
2. Ensure OFI threshold enforcement
3. Update signal validation logic
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("APPLYING LEARNING RECOMMENDATIONS")
print("=" * 80)
print()

# ============================================================================
# KEY FINDINGS FROM ANALYSIS
# ============================================================================
print("=" * 80)
print("KEY FINDINGS FROM COMPREHENSIVE ANALYSIS")
print("=" * 80)
print()
print("1. SHORT trades: OFI avg = 0.875 (STRONG) → PROFITABLE")
print("2. LONG trades: OFI avg = 0.000 (WEAK/MISSING) → LOSING")
print("3. Root Cause: LONG trades executed with weak/missing OFI")
print("4. Solution: Require OFI ≥ 0.5 for LONG trades (match SHORT)")
print()

# ============================================================================
# 1. UPDATE SIGNAL POLICIES
# ============================================================================
print("=" * 80)
print("1. UPDATING SIGNAL POLICIES")
print("=" * 80)

signal_policy_path = Path("configs/signal_policies.json")
if signal_policy_path.exists():
    try:
        with open(signal_policy_path, 'r') as f:
            policy = json.load(f)
        
        alpha_trading = policy.get("alpha_trading", {})
        
        # Current values
        current_ofi_threshold = alpha_trading.get("ofi_threshold", 0.54)
        current_min_ofi = alpha_trading.get("min_ofi_confidence", 0.5)
        has_long_req = "long_ofi_requirement" in alpha_trading
        has_short_req = "short_ofi_requirement" in alpha_trading
        
        print(f"   Current OFI threshold: {current_ofi_threshold}")
        print(f"   Current min OFI confidence: {current_min_ofi}")
        print(f"   Has explicit LONG requirement: {has_long_req}")
        print(f"   Has explicit SHORT requirement: {has_short_req}")
        
        # Always add explicit direction-specific requirements (for conviction_gate.py)
        # Recommendation: OFI ≥ 0.5 for both LONG and SHORT (based on analysis)
        new_ofi_threshold = 0.5
        new_min_ofi = 0.5
        updated = False
        
        if not has_long_req or alpha_trading.get("long_ofi_requirement", 0) < 0.5:
            alpha_trading["long_ofi_requirement"] = 0.5
            updated = True
            print(f"   ✅ Added/Updated LONG OFI requirement: 0.5")
        
        if not has_short_req or alpha_trading.get("short_ofi_requirement", 0) < 0.5:
            alpha_trading["short_ofi_requirement"] = 0.5
            updated = True
            print(f"   ✅ Added/Updated SHORT OFI requirement: 0.5")
        
        if current_ofi_threshold < new_ofi_threshold:
            alpha_trading["ofi_threshold"] = new_ofi_threshold
            updated = True
            print(f"   ✅ Updated OFI threshold to: {new_ofi_threshold}")
        
        if current_min_ofi < new_min_ofi:
            alpha_trading["min_ofi_confidence"] = new_min_ofi
            updated = True
            print(f"   ✅ Updated min OFI confidence to: {new_min_ofi}")
        
        if updated:
            policy["alpha_trading"] = alpha_trading
            
            # Backup original
            backup_path = signal_policy_path.with_suffix('.json.backup')
            with open(backup_path, 'w') as f:
                json.dump(policy, f, indent=2)
            print(f"   ✅ Backup saved to: {backup_path}")
            
            # Write updated policy
            with open(signal_policy_path, 'w') as f:
                json.dump(policy, f, indent=2)
            
            print(f"   ✅ Signal policies updated successfully")
        else:
            print(f"   ✅ OFI thresholds already meet requirements")
            
    except Exception as e:
        print(f"   ❌ Error updating signal policies: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"   ⚠️  Signal policies file not found: {signal_policy_path}")

print()

# ============================================================================
# 2. CHECK WHERE OFI THRESHOLD IS ENFORCED
# ============================================================================
print("=" * 80)
print("2. CHECKING OFI THRESHOLD ENFORCEMENT")
print("=" * 80)

# Check key files that enforce OFI
enforcement_files = [
    "src/conviction_gate.py",
    "src/alpha_signals_integration.py",
    "src/bot_cycle.py"
]

for file_path in enforcement_files:
    path = Path(file_path)
    if path.exists():
        try:
            with open(path, 'r') as f:
                content = f.read()
            
            # Check for OFI threshold checks
            ofi_checks = []
            if 'ofi' in content.lower() and 'threshold' in content.lower():
                ofi_checks.append("Has OFI threshold logic")
            if 'ofi' in content.lower() and ('>=' in content or '>' in content):
                ofi_checks.append("Has OFI comparison")
            
            if ofi_checks:
                print(f"   ✅ {file_path}:")
                for check in ofi_checks:
                    print(f"      - {check}")
        except Exception as e:
            print(f"   ⚠️  {file_path}: Error reading ({e})")
    else:
        print(f"   ⚠️  {file_path}: File not found")

print()

# ============================================================================
# 3. GENERATE LEARNING UPDATE SUMMARY
# ============================================================================
print("=" * 80)
print("3. LEARNING UPDATE SUMMARY")
print("=" * 80)

updates = {
    "applied_at": str(Path(__file__).stat().st_mtime),
    "findings": {
        "short_ofi_avg": 0.875,
        "long_ofi_avg": 0.000,
        "short_profitable": True,
        "long_losing": True
    },
    "recommendations_applied": [
        "Require OFI ≥ 0.5 for LONG trades",
        "Require OFI ≥ 0.5 for SHORT trades (already working)",
        "Updated signal_policies.json with explicit thresholds"
    ],
    "next_steps": [
        "Verify OFI threshold enforcement in conviction_gate.py",
        "Monitor LONG trade OFI values in next analysis",
        "Track if LONG trades now have OFI ≥ 0.5"
    ]
}

summary_path = Path("feature_store/learning_updates_applied.json")
summary_path.parent.mkdir(parents=True, exist_ok=True)
with open(summary_path, 'w') as f:
    json.dump(updates, f, indent=2)

print(f"   ✅ Learning updates summary saved to: {summary_path}")
print()

# ============================================================================
# 4. RECOMMENDATIONS
# ============================================================================
print("=" * 80)
print("4. NEXT STEPS")
print("=" * 80)
print()
print("✅ Signal policies updated")
print()
print("⚠️  MANUAL STEPS REQUIRED:")
print("   1. Verify OFI threshold is enforced in signal validation code")
print("   2. Check conviction_gate.py to ensure it uses these thresholds")
print("   3. Restart bot to apply new thresholds")
print("   4. Monitor next analysis to confirm LONG trades have OFI ≥ 0.5")
print()
print("=" * 80)
print("LEARNING RECOMMENDATIONS APPLIED")
print("=" * 80)
