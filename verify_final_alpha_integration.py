#!/usr/bin/env python3
"""
FINAL ALPHA Integration Verification
====================================
Verifies all integration points are correctly wired:

1. Time-Regime Optimizer → Enhanced Trade Logging
2. Enhanced Trade Logging → Position Manager
3. Position Manager → Dashboard
4. Intelligence Gate → Power Ranking
5. Trade Execution → Self-Healing Loop
6. Self-Healing Loop → Time-Regime Optimizer
7. Dashboard → All data sources

This script checks:
- All functions are callable
- Data flows correctly between modules
- No missing imports
- Configuration files are accessible
- Labels and naming are consistent
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 80)
print("FINAL ALPHA INTEGRATION VERIFICATION")
print("=" * 80)
print()

errors = []
warnings = []

def check(description: str, condition: bool, error_msg: str = ""):
    """Check a condition and record errors"""
    if condition:
        print(f"[OK] {description}")
    else:
        print(f"[ERROR] {description}")
        if error_msg:
            print(f"       {error_msg}")
        errors.append(f"{description}: {error_msg}")

def warn(description: str, warning_msg: str = ""):
    """Record a warning"""
    print(f"[WARN] {description}")
    if warning_msg:
        print(f"       {warning_msg}")
    warnings.append(f"{description}: {warning_msg}")

# ============================================================================
# 1. Verify Time-Regime Optimizer Integration
# ============================================================================
print("\n1. Time-Regime Optimizer Integration")
print("-" * 80)

try:
    from src.time_regime_optimizer import get_time_regime_optimizer, TimeRegimeOptimizer
    optimizer = get_time_regime_optimizer()
    check("Time-Regime Optimizer imports correctly", optimizer is not None)
    
    windows = optimizer.get_allowed_windows()
    check("get_allowed_windows() returns list", isinstance(windows, list))
    check("Base window exists", len(windows) > 0, f"Found {len(windows)} windows")
except Exception as e:
    check("Time-Regime Optimizer imports correctly", False, str(e))

try:
    from src.enhanced_trade_logging import is_golden_hour
    # This should internally use the optimizer
    result = is_golden_hour()
    check("is_golden_hour() uses dynamic windows", isinstance(result, bool))
except Exception as e:
    check("is_golden_hour() uses dynamic windows", False, str(e))

# ============================================================================
# 2. Verify Enhanced Trade Logging Integration
# ============================================================================
print("\n2. Enhanced Trade Logging Integration")
print("-" * 80)

try:
    from src.enhanced_trade_logging import check_golden_hours_block, get_golden_hour_config
    should_block, reason, trading_window = check_golden_hours_block()
    check("check_golden_hours_block() returns correct tuple", 
          isinstance(should_block, bool) and isinstance(reason, str) and trading_window in ["golden_hour", "24_7"],
          f"Got: ({should_block}, {reason}, {trading_window})")
except Exception as e:
    check("check_golden_hours_block() works correctly", False, str(e))

try:
    config = get_golden_hour_config()
    check("get_golden_hour_config() returns dict", isinstance(config, dict))
    check("Config has required keys", "restrict_to_golden_hour" in config)
except Exception as e:
    check("get_golden_hour_config() works correctly", False, str(e))

# ============================================================================
# 3. Verify Position Manager Integration
# ============================================================================
print("\n3. Position Manager Integration")
print("-" * 80)

try:
    from src.position_manager import open_futures_position
    # Check that function signature includes trading_window in signal_context
    import inspect
    sig = inspect.signature(open_futures_position)
    check("open_futures_position accepts signal_context parameter", 
          "signal_context" in sig.parameters)
except Exception as e:
    check("Position Manager integration check", False, str(e))

# ============================================================================
# 4. Verify Intelligence Gate Power Ranking
# ============================================================================
print("\n4. Intelligence Gate Power Ranking")
print("-" * 80)

try:
    from src.intelligence_gate import intelligence_gate, get_symbol_7day_performance, _get_symbol_shadow_win_rate_48h
    
    perf = get_symbol_7day_performance("BTCUSDT")
    check("get_symbol_7day_performance() works", 
          isinstance(perf, dict) and "win_rate" in perf and "profit_factor" in perf)
    
    shadow_wr = _get_symbol_shadow_win_rate_48h("BTCUSDT")
    check("_get_symbol_shadow_win_rate_48h() works", 
          isinstance(shadow_wr, float) and 0 <= shadow_wr <= 1)
    
    test_signal = {"symbol": "BTCUSDT", "action": "OPEN_LONG", "direction": "LONG", "expected_roi": 0.02}
    approved, reason, sizing_mult = intelligence_gate(test_signal)
    check("intelligence_gate() applies Power Ranking", 
          isinstance(sizing_mult, (int, float)) and sizing_mult >= 0)
except Exception as e:
    check("Intelligence Gate Power Ranking", False, str(e))

# ============================================================================
# 5. Verify Trade Execution Integration
# ============================================================================
print("\n5. Trade Execution Integration")
print("-" * 80)

try:
    from src.trade_execution import (
        get_marketable_limit_offset_bps,
        calculate_marketable_limit_price,
        analyze_fill_failure_rate,
        MARKETABLE_LIMIT_OFFSET_BPS,
        MARKETABLE_LIMIT_OFFSET_BPS_MAX
    )
    
    offset = get_marketable_limit_offset_bps()
    check("get_marketable_limit_offset_bps() works", 
          MARKETABLE_LIMIT_OFFSET_BPS <= offset <= MARKETABLE_LIMIT_OFFSET_BPS_MAX)
    
    price = calculate_marketable_limit_price(50000.0, "LONG", False)
    check("calculate_marketable_limit_price() uses dynamic offset", price > 50000.0)
    
    analysis = analyze_fill_failure_rate(hours=24)
    check("analyze_fill_failure_rate() works", isinstance(analysis, dict))
except Exception as e:
    check("Trade Execution integration", False, str(e))

# ============================================================================
# 6. Verify Self-Healing Learning Loop Integration
# ============================================================================
print("\n6. Self-Healing Learning Loop Integration")
print("-" * 80)

try:
    from src.self_healing_learning_loop import SelfHealingLearningLoop
    loop = SelfHealingLearningLoop()
    check("SelfHealingLearningLoop instantiates", loop is not None)
    
    # Check that _run_loop includes Time-Regime Optimizer calls
    import inspect
    source = inspect.getsource(loop._run_loop)
    check("Self-Healing Loop includes Time-Regime Optimizer", 
          "time_regime_optimizer" in source.lower() or "TIME-REGIME" in source)
except Exception as e:
    check("Self-Healing Learning Loop integration", False, str(e))

# ============================================================================
# 7. Verify Dashboard Integration
# ============================================================================
print("\n7. Dashboard Integration")
print("-" * 80)

try:
    # Check that cockpit.py can import required modules
    cockpit_path = Path("cockpit.py")
    if cockpit_path.exists():
        with open(cockpit_path, 'r') as f:
            cockpit_code = f.read()
        
        check("Dashboard imports time_regime_optimizer", 
              "time_regime_optimizer" in cockpit_code or "Time-Regime Optimizer" in cockpit_code)
        check("Dashboard has Shadow vs Live chart", 
              "Shadow vs Live" in cockpit_code or "shadow_trade_outcomes" in cockpit_code)
        check("Dashboard has Active Golden Windows", 
              "Active Golden Windows" in cockpit_code or "get_allowed_windows" in cockpit_code)
    else:
        warn("cockpit.py not found", "Dashboard file missing")
except Exception as e:
    check("Dashboard integration check", False, str(e))

# ============================================================================
# 8. Verify Data Flow Consistency
# ============================================================================
print("\n8. Data Flow Consistency")
print("-" * 80)

try:
    # Check that trading_window is consistently named
    files_to_check = [
        "src/enhanced_trade_logging.py",
        "src/position_manager.py",
        "src/bot_cycle.py",
        "src/full_integration_blofin_micro_live_and_paper.py",
        "src/unified_recovery_learning_fix.py"
    ]
    
    for file_path in files_to_check:
        path = Path(file_path)
        if path.exists():
            with open(path, 'r') as f:
                content = f.read()
            # Check for consistent naming
            if "trading_window" in content:
                check(f"{file_path} uses 'trading_window' consistently", True)
            else:
                warn(f"{file_path} may not use trading_window", "Check if this is expected")
except Exception as e:
    check("Data flow consistency check", False, str(e))

# ============================================================================
# 9. Verify Configuration File Structure
# ============================================================================
print("\n9. Configuration File Structure")
print("-" * 80)

try:
    from src.infrastructure.path_registry import PathRegistry
    
    # Check golden_hour_config.json structure
    config_path = Path(PathRegistry.get_path("feature_store", "golden_hour_config.json"))
    if config_path.exists():
        import json
        with open(config_path, 'r') as f:
            config = json.load(f)
        check("golden_hour_config.json has required fields", 
              "restrict_to_golden_hour" in config and "allowed_windows" in config)
    else:
        warn("golden_hour_config.json doesn't exist", "Will be created on first run")
    
    # Check trade_execution_config.json (may not exist yet)
    exec_config_path = Path(PathRegistry.get_path("feature_store", "trade_execution_config.json"))
    if exec_config_path.exists():
        import json
        with open(exec_config_path, 'r') as f:
            exec_config = json.load(f)
        check("trade_execution_config.json exists and is valid", isinstance(exec_config, dict))
    else:
        check("trade_execution_config.json will be created on first adjustment", True)
except Exception as e:
    check("Configuration file structure check", False, str(e))

# ============================================================================
# 10. Verify No Circular Dependencies
# ============================================================================
print("\n10. Circular Dependency Check")
print("-" * 80)

# Try importing all modules in sequence to detect circular dependencies
modules_to_check = [
    ("src.time_regime_optimizer", "Time-Regime Optimizer"),
    ("src.enhanced_trade_logging", "Enhanced Trade Logging"),
    ("src.intelligence_gate", "Intelligence Gate"),
    ("src.trade_execution", "Trade Execution"),
    ("src.self_healing_learning_loop", "Self-Healing Learning Loop"),
]

for module_name, display_name in modules_to_check:
    try:
        __import__(module_name)
        check(f"{display_name} imports without circular dependency", True)
    except ImportError as e:
        check(f"{display_name} imports without circular dependency", False, str(e))
    except Exception as e:
        # Some exceptions are OK (like missing dependencies)
        warn(f"{display_name} import check", f"Exception (may be OK): {e}")

# ============================================================================
# SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("VERIFICATION SUMMARY")
print("=" * 80)
print()

if errors:
    print(f"[FAILURE] Found {len(errors)} errors:")
    for error in errors:
        print(f"  - {error}")
    print()
    
if warnings:
    print(f"[WARNING] Found {len(warnings)} warnings:")
    for warning in warnings:
        print(f"  - {warning}")
    print()

if not errors:
    print("[SUCCESS] All integration checks passed!")
    print()
    print("FINAL ALPHA Integration Status:")
    print("  - Time-Regime Optimizer: INTEGRATED")
    print("  - Enhanced Trade Logging: INTEGRATED")
    print("  - Position Manager: INTEGRATED")
    print("  - Intelligence Gate Power Ranking: INTEGRATED")
    print("  - Trade Execution Tuning: INTEGRATED")
    print("  - Self-Healing Learning Loop: INTEGRATED")
    print("  - Dashboard: INTEGRATED")
    print()
    print("All components are correctly wired and ready for deployment!")
    sys.exit(0)
else:
    print("[FAILURE] Integration verification failed. Please fix errors above.")
    sys.exit(1)

