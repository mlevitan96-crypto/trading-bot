#!/usr/bin/env python3
"""
Quick System Health Check - Verify signal and decision engines are working
"""

import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def check_signal_engine():
    """Check signal engine health."""
    print("=" * 70)
    print("SIGNAL ENGINE STATUS")
    print("=" * 70)
    
    try:
        from src.signal_integrity import get_status
        status = get_status()
        
        signal_status = status.get('signal_engine', 'unknown')
        print(f"  Status: {signal_status.upper()}")
        
        # Check files
        from src.infrastructure.path_registry import PathRegistry
        
        signals_file = Path(PathRegistry.get_path("logs", "signals.jsonl"))
        ensemble_file = Path(PathRegistry.get_path("logs", "ensemble_predictions.jsonl"))
        
        print(f"\n  Files:")
        print(f"    signals.jsonl: {signals_file}")
        print(f"      Exists: {signals_file.exists()}")
        if signals_file.exists():
            age = time.time() - signals_file.stat().st_mtime
            print(f"      Age: {age/60:.1f} minutes")
            if age < 600:
                print(f"      [OK] File is recent")
            else:
                print(f"      [WARNING] File is stale (>10 minutes)")
        
        print(f"    ensemble_predictions.jsonl: {ensemble_file}")
        print(f"      Exists: {ensemble_file.exists()}")
        if ensemble_file.exists():
            age = time.time() - ensemble_file.stat().st_mtime
            print(f"      Age: {age/60:.1f} minutes")
            if age < 600:
                print(f"      [OK] File is recent")
            else:
                print(f"      [WARNING] File is stale (>10 minutes)")
        
        return signal_status == 'green'
    except Exception as e:
        print(f"  [ERROR] Failed to check signal engine: {e}")
        return False


def check_decision_engine():
    """Check decision engine health."""
    print("\n" + "=" * 70)
    print("DECISION ENGINE STATUS")
    print("=" * 70)
    
    try:
        from src.infrastructure.path_registry import PathRegistry
        
        decisions_file = Path(PathRegistry.get_path("logs", "enriched_decisions.jsonl"))
        
        print(f"  File: {decisions_file}")
        print(f"    Exists: {decisions_file.exists()}")
        
        if decisions_file.exists():
            age = time.time() - decisions_file.stat().st_mtime
            print(f"    Age: {age/60:.1f} minutes")
            
            # Count lines
            try:
                with open(decisions_file, 'r') as f:
                    lines = sum(1 for _ in f)
                print(f"    Records: {lines}")
                
                if age < 1440:  # 24 hours
                    print(f"    [OK] File is recent")
                    return True
                else:
                    print(f"    [WARNING] File is stale (>24 hours)")
                    return False
            except Exception as e:
                print(f"    [ERROR] Failed to read file: {e}")
                return False
        else:
            print(f"    [WARNING] File does not exist yet")
            return False
            
    except Exception as e:
        print(f"  [ERROR] Failed to check decision engine: {e}")
        return False


def check_safety_layer():
    """Check safety layer status."""
    print("\n" + "=" * 70)
    print("SAFETY LAYER STATUS")
    print("=" * 70)
    
    try:
        from src.operator_safety import get_status
        status = get_status()
        
        safety_status = status.get('safety_layer', 'unknown')
        healing_status = status.get('self_healing', 'unknown')
        
        print(f"  Safety Layer: {safety_status.upper()}")
        print(f"  Self-Healing: {healing_status.upper()}")
        
        return safety_status == 'green' and healing_status == 'green'
    except Exception as e:
        print(f"  [ERROR] Failed to check safety layer: {e}")
        return False


def main():
    """Run all health checks."""
    print("\n" + "=" * 70)
    print("SYSTEM HEALTH CHECK")
    print("=" * 70)
    print()
    
    results = []
    results.append(("Signal Engine", check_signal_engine()))
    results.append(("Decision Engine", check_decision_engine()))
    results.append(("Safety Layer", check_safety_layer()))
    
    # Summary
    print("\n" + "=" * 70)
    print("HEALTH SUMMARY")
    print("=" * 70)
    
    all_healthy = True
    for component, healthy in results:
        status = "[HEALTHY]" if healthy else "[DEGRADED]"
        print(f"  {component}: {status}")
        if not healthy:
            all_healthy = False
    
    print("\n" + "=" * 70)
    if all_healthy:
        print("[SUCCESS] All systems healthy!")
    else:
        print("[WARNING] Some systems need attention")
    print("=" * 70)
    
    return 0 if all_healthy else 1


if __name__ == "__main__":
    sys.exit(main())

