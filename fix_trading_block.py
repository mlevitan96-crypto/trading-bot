#!/usr/bin/env python3
"""
Fix script to resolve trading block issues.
Run this on your DigitalOcean droplet to apply fixes.
"""

import json
import os
from pathlib import Path
from datetime import datetime

def backup_file(filepath):
    """Create a backup of a file before modifying."""
    p = Path(filepath)
    if p.exists():
        backup_path = f"{filepath}.backup_{int(datetime.now().timestamp())}"
        import shutil
        shutil.copy2(filepath, backup_path)
        print(f"✅ Backed up {filepath} to {backup_path}")
        return backup_path
    return None

def fix_signal_policies():
    """Fix alpha trading policy settings."""
    filepath = "configs/signal_policies.json"
    backup_file(filepath)
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    # Ensure alpha trading is enabled
    if "alpha_trading" not in data:
        data["alpha_trading"] = {}
    
    alpha = data["alpha_trading"]
    
    # Apply fixes
    alpha["enabled"] = True
    alpha["min_ofi_confidence"] = 0.3  # Lower from 0.5 for more signals
    alpha["min_ensemble_score"] = 0.05  # Keep at 0.05
    alpha["cooldown_seconds"] = 60  # Reduce from 120 to 60
    
    # Ensure all symbols are enabled
    if "enabled_symbols" not in alpha or len(alpha["enabled_symbols"]) == 0:
        alpha["enabled_symbols"] = [
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT",
            "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", "MATICUSDT", "TRXUSDT"
        ]
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Fixed {filepath}")
    print(f"   - alpha_trading.enabled = {alpha['enabled']}")
    print(f"   - min_ofi_confidence = {alpha['min_ofi_confidence']}")
    print(f"   - cooldown_seconds = {alpha['cooldown_seconds']}")
    print(f"   - enabled_symbols = {len(alpha['enabled_symbols'])} symbols")

def fix_live_config():
    """Fix live config symbol restrictions."""
    filepath = "live_config.json"
    backup_file(filepath)
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    if "runtime" not in data:
        data["runtime"] = {}
    
    runtime = data["runtime"]
    
    # Remove symbol restrictions
    if "allowed_symbols_mode" in runtime:
        if len(runtime["allowed_symbols_mode"]) > 0:
            print(f"   ⚠️ Removing symbol restrictions: {runtime['allowed_symbols_mode']}")
        runtime["allowed_symbols_mode"] = []
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Fixed {filepath}")
    print(f"   - runtime.allowed_symbols_mode = [] (all symbols allowed)")

def fix_execution_governor():
    """Fix execution governor ROI thresholds."""
    filepath = "logs/execution_governor.json"
    
    if not Path(filepath).exists():
        # Create default if doesn't exist
        data = {
            "roi_threshold": 0.0005,
            "max_trades_hour": 10,
            "updated_at": datetime.now().isoformat()
        }
    else:
        backup_file(filepath)
        with open(filepath, 'r') as f:
            data = json.load(f)
    
    # Lower ROI threshold for paper trading
    data["roi_threshold"] = 0.0005  # 0.05% instead of 0.5%
    data["max_trades_hour"] = 10  # Increase from 2
    data["updated_at"] = datetime.now().isoformat()
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Fixed {filepath}")
    print(f"   - roi_threshold = {data['roi_threshold']} ({data['roi_threshold']*100:.2f}%)")
    print(f"   - max_trades_hour = {data['max_trades_hour']}")

def fix_fee_arbiter():
    """Fix fee arbiter ROI gate."""
    filepath = "logs/fee_arbiter.json"
    
    if not Path(filepath).exists():
        data = {
            "roi_gate": 0.0005,
            "prefer_limit": True,
            "max_trades_hour": 10,
            "updated_at": datetime.now().isoformat()
        }
    else:
        backup_file(filepath)
        with open(filepath, 'r') as f:
            data = json.load(f)
    
    # Lower ROI gate for paper trading
    data["roi_gate"] = 0.0005  # 0.05% instead of 0.6%
    data["max_trades_hour"] = 10
    data["updated_at"] = datetime.now().isoformat()
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Fixed {filepath}")
    print(f"   - roi_gate = {data['roi_gate']} ({data['roi_gate']*100:.2f}%)")

def ensure_signal_resolution_running():
    """Check if signal resolution is scheduled and add if not."""
    print("\n[5] ENSURING SIGNAL RESOLUTION RUNS")
    print("-" * 80)
    
    # Check if resolver is started in bot_cycle or scheduler
    bot_cycle_path = Path("src/bot_cycle.py")
    scheduler_path = Path("src/scheduler_with_analysis.py")
    run_path = Path("src/run.py")
    
    resolver_imported = False
    resolver_called = False
    
    for filepath in [bot_cycle_path, scheduler_path, run_path]:
        if filepath.exists():
            with open(filepath, 'r') as f:
                content = f.read()
                if "signal_outcome_tracker" in content or "signal_tracker" in content:
                    resolver_imported = True
                if "resolve_pending_signals" in content:
                    resolver_called = True
    
    if not resolver_called:
        print("⚠️ Signal resolution not found in main loop")
        print("   Adding signal resolution to bot_cycle.py...")
        
        # Read bot_cycle.py
        with open(bot_cycle_path, 'r') as f:
            lines = f.readlines()
        
        # Find run_bot_cycle function and add resolver call
        in_function = False
        insert_index = None
        
        for i, line in enumerate(lines):
            if "def run_bot_cycle():" in line:
                in_function = True
            elif in_function and "initialize_portfolio()" in line:
                # Insert after initialize_portfolio (preferred location)
                insert_index = i + 1
                break
            elif in_function and line.strip().startswith("def ") and "run_bot_cycle" not in line:
                # Fallback: insert before next function definition
                insert_index = i
                break
        
        if insert_index:
            # Add import at top if not present
            import_added = False
            for i, line in enumerate(lines[:50]):
                if "from src.signal_outcome_tracker import" in line:
                    import_added = True
                    break
            
            if not import_added:
                # Find last import line
                last_import = 0
                for i, line in enumerate(lines[:100]):
                    if line.strip().startswith("import ") or line.strip().startswith("from "):
                        last_import = i
                
                lines.insert(last_import + 1, "from src.signal_outcome_tracker import signal_tracker\n")
                # Adjust insert_index since we added a line before it
                # Only adjust if the import was inserted before the resolver call position
                if last_import + 1 < insert_index:
                    insert_index += 1
            
            # Add resolver call
            resolver_call = "    # [SIGNAL RESOLUTION] Resolve pending signals every cycle\n    try:\n        signal_tracker.resolve_pending_signals()\n    except Exception as e:\n        print(f\"⚠️ Signal resolution error: {e}\")\n    \n"
            lines.insert(insert_index, resolver_call)
            
            # Write back
            backup_file(str(bot_cycle_path))
            with open(bot_cycle_path, 'w') as f:
                f.writelines(lines)
            
            print(f"✅ Added signal resolution to {bot_cycle_path}")
        else:
            print("⚠️ Could not find insertion point in bot_cycle.py")
            print("   Please manually add: signal_tracker.resolve_pending_signals() to run_bot_cycle()")
    else:
        print("✅ Signal resolution already scheduled")

def main():
    print("=" * 80)
    print("TRADING BOT FIX SCRIPT")
    print("=" * 80)
    print(f"Time: {datetime.now().isoformat()}\n")
    
    print("[1] FIXING SIGNAL POLICIES")
    print("-" * 80)
    fix_signal_policies()
    
    print("\n[2] FIXING LIVE CONFIG")
    print("-" * 80)
    fix_live_config()
    
    print("\n[3] FIXING EXECUTION GOVERNOR")
    print("-" * 80)
    fix_execution_governor()
    
    print("\n[4] FIXING FEE ARBITER")
    print("-" * 80)
    fix_fee_arbiter()
    
    ensure_signal_resolution_running()
    
    print("\n" + "=" * 80)
    print("FIXES APPLIED")
    print("=" * 80)
    print("✅ All fixes have been applied with backups created.")
    print("\n📋 NEXT STEPS:")
    print("   1. Restart the trading bot")
    print("   2. Monitor logs/predictive_signals.jsonl for signal generation")
    print("   3. Monitor logs/signal_outcomes.jsonl for outcome updates")
    print("   4. Check feature_store/pending_signals.json for logged signals")
    print("   5. Run diagnose_trading_block.py to verify fixes")
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()


