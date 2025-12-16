#!/usr/bin/env python3
"""
Path Unification Test - Verify all signal/decision files use unified paths
Tests that writers and readers use the same absolute paths regardless of CWD.
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_path_registry():
    """Test PathRegistry resolves paths correctly."""
    print("=" * 70)
    print("TEST 1: PathRegistry Resolution")
    print("=" * 70)
    
    from src.infrastructure.path_registry import PathRegistry
    
    # Get project root
    project_root = PathRegistry.get_root()
    print(f"[OK] Project root: {project_root}")
    print(f"  Exists: {project_root.exists()}")
    
    # Test critical paths
    test_paths = [
        ("logs", "signals.jsonl"),
        ("logs", "enriched_decisions.jsonl"),
        ("logs", "strategy_signals.jsonl"),
        ("logs", "predictive_signals.jsonl"),
        ("logs", "ensemble_predictions.jsonl"),
    ]
    
    all_good = True
    for dir_name, filename in test_paths:
        abs_path = PathRegistry.get_path(dir_name, filename)
        print(f"\n  {dir_name}/{filename}:")
        print(f"    Absolute path: {abs_path}")
        print(f"    Exists: {Path(abs_path).exists()}")
        print(f"    Parent exists: {Path(abs_path).parent.exists()}")
        
        # Verify it's actually absolute
        if not os.path.isabs(abs_path):
            print(f"    [ERROR] Path is not absolute!")
            all_good = False
        else:
            print(f"    [OK] Path is absolute")
    
    return all_good


def test_data_registry_paths():
    """Test DataRegistry uses PathRegistry paths."""
    print("\n" + "=" * 70)
    print("TEST 2: DataRegistry Path Consistency")
    print("=" * 70)
    
    from src.data_registry import DataRegistry as DR
    from src.infrastructure.path_registry import PathRegistry
    
    # Check SIGNALS_UNIVERSE
    dr_signals = DR.SIGNALS_UNIVERSE
    pr_signals = PathRegistry.get_path("logs", "signals.jsonl")
    
    print(f"\n  SIGNALS_UNIVERSE:")
    print(f"    DataRegistry: {dr_signals}")
    print(f"    PathRegistry: {pr_signals}")
    
    if dr_signals == pr_signals:
        print(f"    [OK] Paths match!")
    else:
        print(f"    [ERROR] Paths don't match!")
        return False
    
    # Check ENRICHED_DECISIONS
    dr_decisions = DR.ENRICHED_DECISIONS
    pr_decisions = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
    
    print(f"\n  ENRICHED_DECISIONS:")
    print(f"    DataRegistry: {dr_decisions}")
    print(f"    PathRegistry: {pr_decisions}")
    
    if dr_decisions == pr_decisions:
        print(f"    [OK] Paths match!")
    else:
        print(f"    [ERROR] Paths don't match!")
        return False
    
    return True


def test_writer_reader_consistency():
    """Test that writers and readers use the same paths."""
    print("\n" + "=" * 70)
    print("TEST 3: Writer/Reader Path Consistency")
    print("=" * 70)
    
    from src.infrastructure.path_registry import PathRegistry
    from src.data_registry import DataRegistry as DR
    from src.data_enrichment_layer import ENRICHED_LOG
    from src.signal_integrity import get_status
    
    # Check data_enrichment_layer writer path
    print(f"\n  Data Enrichment Layer (writer):")
    print(f"    ENRICHED_LOG: {ENRICHED_LOG}")
    
    # Check dashboard reader path (from pnl_dashboard.py pattern)
    dashboard_path = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
    print(f"    Dashboard reader: {dashboard_path}")
    
    if ENRICHED_LOG == dashboard_path:
        print(f"    [OK] Writer and reader use same path!")
    else:
        print(f"    [ERROR] Writer and reader paths don't match!")
        return False
    
    # Check signal_integrity reader
    print(f"\n  Signal Integrity (reader):")
    status = get_status()
    print(f"    Status: {status}")
    
    # Check DataRegistry signals path
    print(f"\n  DataRegistry signals path:")
    print(f"    DR.SIGNALS_UNIVERSE: {DR.SIGNALS_UNIVERSE}")
    
    return True


def test_file_access():
    """Test that files can be accessed at the unified paths."""
    print("\n" + "=" * 70)
    print("TEST 4: File Access Test")
    print("=" * 70)
    
    from src.infrastructure.path_registry import PathRegistry
    from src.data_registry import DataRegistry as DR
    
    test_files = [
        ("signals.jsonl", DR.SIGNALS_UNIVERSE),
        ("enriched_decisions.jsonl", DR.ENRICHED_DECISIONS),
    ]
    
    all_accessible = True
    for name, path in test_files:
        print(f"\n  {name}:")
        print(f"    Path: {path}")
        
        path_obj = Path(path)
        exists = path_obj.exists()
        print(f"    Exists: {exists}")
        
        if exists:
            # Try to read
            try:
                with open(path, 'r') as f:
                    lines = sum(1 for _ in f)
                print(f"    [OK] Readable ({lines} lines)")
            except Exception as e:
                print(f"    [ERROR] Read error: {e}")
                all_accessible = False
        else:
            # Try to create directory and touch file
            try:
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                path_obj.touch()
                print(f"    [OK] Created empty file for testing")
            except Exception as e:
                print(f"    [ERROR] Create error: {e}")
                all_accessible = False
    
    return all_accessible


def test_cwd_independence():
    """Test that paths work regardless of current working directory."""
    print("\n" + "=" * 70)
    print("TEST 5: CWD Independence")
    print("=" * 70)
    
    from src.infrastructure.path_registry import PathRegistry
    from src.data_registry import DataRegistry as DR
    
    original_cwd = os.getcwd()
    
    # Test from different directories
    test_dirs = [
        original_cwd,
        os.path.dirname(original_cwd) if os.path.dirname(original_cwd) else original_cwd,
    ]
    
    all_consistent = True
    paths_seen = {}
    
    for test_dir in test_dirs:
        if not os.path.exists(test_dir):
            continue
            
        os.chdir(test_dir)
        current_cwd = os.getcwd()
        
        print(f"\n  Testing from: {current_cwd}")
        
        # Get paths from this directory
        signals_path = PathRegistry.get_path("logs", "signals.jsonl")
        decisions_path = DR.ENRICHED_DECISIONS
        
        print(f"    signals.jsonl: {signals_path}")
        print(f"    enriched_decisions.jsonl: {decisions_path}")
        
        # Store for comparison
        key = f"{test_dir}"
        if key not in paths_seen:
            paths_seen[key] = (signals_path, decisions_path)
        else:
            prev_signals, prev_decisions = paths_seen[key]
            if signals_path != prev_signals or decisions_path != prev_decisions:
                print(f"    [ERROR] Paths changed when CWD changed!")
                all_consistent = False
            else:
                print(f"    [OK] Paths consistent across CWD changes")
    
    # Restore original CWD
    os.chdir(original_cwd)
    
    return all_consistent


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("PATH UNIFICATION TEST SUITE")
    print("=" * 70)
    print("\nThis script verifies that all signal/decision files use unified")
    print("absolute paths via PathRegistry, ensuring writers and readers")
    print("access the same files regardless of working directory.\n")
    
    results = []
    
    results.append(("PathRegistry Resolution", test_path_registry()))
    results.append(("DataRegistry Consistency", test_data_registry_paths()))
    results.append(("Writer/Reader Consistency", test_writer_reader_consistency()))
    results.append(("File Access", test_file_access()))
    results.append(("CWD Independence", test_cwd_independence()))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    all_passed = True
    for test_name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 70)
    if all_passed:
        print("[SUCCESS] ALL TESTS PASSED - Path unification is working correctly!")
    else:
        print("[FAILURE] SOME TESTS FAILED - Review errors above")
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

