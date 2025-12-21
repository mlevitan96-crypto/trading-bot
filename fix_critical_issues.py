#!/usr/bin/env python3
"""
Fix Critical Issues Found in Verification
==========================================
Fixes:
1. Signal weights normalization (weights are too high - 0.92+)
2. DataRegistry syntax error (if exists)
3. Enriched decisions (run data enrichment)
4. Check recent trades data issue
"""

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("FIXING CRITICAL ISSUES")
print("=" * 80)

# ============================================================================
# 1. FIX SIGNAL WEIGHTS (Normalize if corrupted)
# ============================================================================

print("\n1. FIXING SIGNAL WEIGHTS")
print("-" * 80)

signal_weights_file = Path("feature_store/signal_weights_gate.json")
if signal_weights_file.exists():
    try:
        with open(signal_weights_file, 'r') as f:
            data = json.load(f)
            weights = data.get("weights", {})
        
        # Check if weights are normalized (should sum to ~1.0)
        total = sum(weights.values())
        
        if total > 1.5:  # Weights are too high - need normalization
            print(f"   [FIXING] Weights sum to {total:.3f} (should be ~1.0)")
            print(f"   [FIXING] Normalizing weights...")
            
            # Normalize to sum to 1.0
            normalized = {k: round(v / total, 4) for k, v in weights.items()}
            
            # Update the file
            data["weights"] = normalized
            from datetime import datetime
            data["fix_applied"] = {
                "timestamp": datetime.now().isoformat(),
                "old_total": total,
                "reason": "Weights were not normalized - fixed by dividing by sum"
            }
            
            with open(signal_weights_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"   [OK] Weights normalized: {sum(normalized.values()):.4f}")
            print(f"   [OK] Sample weights after fix:")
            for signal, weight in list(normalized.items())[:5]:
                print(f"      {signal}: {weight:.4f}")
        else:
            print(f"   [OK] Weights are normalized (sum: {total:.4f})")
    except Exception as e:
        print(f"   [ERROR] Could not fix weights: {e}")
else:
    print(f"   [MISSING] Signal weights file does not exist")

# ============================================================================
# 2. FIX ENRICHED DECISIONS
# ============================================================================

print("\n2. FIXING ENRICHED DECISIONS")
print("-" * 80)

try:
    from src.data_enrichment_layer import enrich_recent_decisions
    
    print("   Running data enrichment...")
    enriched = enrich_recent_decisions(lookback_hours=168)  # Last 7 days
    
    if enriched:
        print(f"   [OK] Created {len(enriched)} enriched decisions")
    else:
        print(f"   [INFO] No enriched decisions created (may need more trade data)")
except Exception as e:
    print(f"   [ERROR] Data enrichment failed: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 3. CHECK RECENT TRADES DATA
# ============================================================================

print("\n3. CHECKING RECENT TRADES DATA")
print("-" * 80)

trades_file = Path("logs/positions_futures.json")
if trades_file.exists():
    try:
        with open(trades_file, 'r') as f:
            data = json.load(f)
            closed = data.get("closed_positions", [])
        
        if closed:
            # Check last 50 trades
            recent = closed[-50:]
            
            # Check if P&L field exists (try multiple field names)
            has_pnl_field = all(("pnl" in t or "net_pnl" in t or "profit_usd" in t) for t in recent)
            profit_values = [float(t.get("pnl", t.get("net_pnl", t.get("profit_usd", 0)))) for t in recent]
            non_zero_profits = [p for p in profit_values if p != 0]
            
            print(f"   Total closed trades: {len(closed)}")
            print(f"   Recent 50 trades:")
            print(f"      Has P&L field (pnl/net_pnl/profit_usd): {has_pnl_field}")
            print(f"      Non-zero profits: {len(non_zero_profits)}/{len(recent)}")
            
            if len(non_zero_profits) == 0:
                print(f"   [WARNING] All recent trades have $0.00 profit")
                print(f"   [INFO] This might indicate:")
                print(f"      - Trades are being recorded but P&L not calculated")
                print(f"      - Trades are test/paper trades with no real P&L")
                print(f"      - Data format issue")
            else:
                wins = sum(1 for p in profit_values if p > 0)
                wr = (wins / len(recent)) * 100
                total_pnl = sum(profit_values)
                print(f"      Win rate: {wr:.1f}%")
                print(f"      Total P&L: ${total_pnl:.2f}")
        else:
            print(f"   [INFO] No closed trades found")
    except Exception as e:
        print(f"   [ERROR] Could not check trades: {e}")

# ============================================================================
# 4. FIX DATAREGISTRY (if syntax error exists)
# ============================================================================

print("\n4. CHECKING DATAREGISTRY")
print("-" * 80)

try:
    from src.data_registry import DataRegistry as DR
    print(f"   [OK] DataRegistry imports successfully")
except SyntaxError as e:
    print(f"   [ERROR] DataRegistry syntax error: {e}")
    print(f"   [INFO] This needs manual fix - check line {e.lineno} in data_registry.py")
except Exception as e:
    print(f"   [WARNING] DataRegistry import error: {e}")
    print(f"   [INFO] This may be a false positive - check if it's actually broken")

# ============================================================================
# 5. SUMMARY
# ============================================================================

print("\n" + "=" * 80)
print("FIX COMPLETE")
print("=" * 80)
print("\nNext steps:")
print("1. Re-run verify_learning_and_performance.py to check fixes")
print("2. If signal weights still wrong, may need to reset to defaults")
print("3. If trades show $0 P&L, check trade recording logic")
