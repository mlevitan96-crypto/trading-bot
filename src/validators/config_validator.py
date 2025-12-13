"""
Configuration Validation Orchestrator

Prevents silent configuration drift by validating:
1. Asset universe consistency across config/code/docs
2. Startup sanity checks (all symbols present)
3. Runtime monitoring (symbols actually being processed)

Runs on bot startup and emits warnings/errors to prevent issues like
missing symbols in the ASSETS list.
"""

import json
import os
import re
from typing import List, Dict, Any, Tuple
from pathlib import Path


class ValidationOrchestrator:
    """Central validation system for bot configuration consistency."""
    
    def __init__(self):
        self.canonical_config_path = "config/asset_universe.json"
        self.replit_md_path = "replit.md"
        self.issues = []
        self.warnings = []
        
    def load_canonical_assets(self) -> List[str]:
        """Load the canonical list of trading symbols."""
        try:
            with open(self.canonical_config_path, 'r') as f:
                config = json.load(f)
            
            assets = [
                asset["symbol"] 
                for asset in config.get("asset_universe", [])
                if asset.get("enabled", True)
            ]
            
            print(f"✅ [VALIDATOR] Loaded {len(assets)} canonical assets from {self.canonical_config_path}")
            return assets
        except FileNotFoundError:
            error = f"❌ [VALIDATOR] CRITICAL: Canonical config not found: {self.canonical_config_path}"
            self.issues.append(error)
            print(error)
            return []
        except Exception as e:
            error = f"❌ [VALIDATOR] Failed to load canonical config: {e}"
            self.issues.append(error)
            print(error)
            return []
    
    def check_regime_detector_assets(self, canonical_assets: List[str]) -> bool:
        """Verify regime_detector.py ASSETS matches canonical config."""
        try:
            with open("src/regime_detector.py", 'r') as f:
                content = f.read()
            
            # Check if using dynamic loading (preferred)
            if "load_canonical_assets()" in content and "ASSETS = load_canonical_assets()" in content:
                print(f"✅ [VALIDATOR] regime_detector.py uses dynamic canonical config loading")
                return True
            
            # Fall back to checking static list
            match = re.search(r'ASSETS\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if not match:
                error = "❌ [VALIDATOR] Could not find ASSETS list in regime_detector.py"
                self.issues.append(error)
                print(error)
                return False
            
            assets_str = match.group(1)
            configured_assets = [
                s.strip().strip('"').strip("'") 
                for s in assets_str.split(',') 
                if s.strip()
            ]
            
            canonical_set = set(canonical_assets)
            configured_set = set(configured_assets)
            
            missing = canonical_set - configured_set
            extra = configured_set - canonical_set
            
            if missing:
                error = f"❌ [VALIDATOR] CRITICAL: regime_detector.py missing symbols: {sorted(missing)}"
                self.issues.append(error)
                print(error)
                return False
            
            if extra:
                warning = f"⚠️ [VALIDATOR] regime_detector.py has extra symbols: {sorted(extra)}"
                self.warnings.append(warning)
                print(warning)
            
            if not missing and not extra:
                print(f"✅ [VALIDATOR] regime_detector.py ASSETS matches canonical config ({len(configured_assets)} symbols)")
                return True
            
            return len(missing) == 0
            
        except Exception as e:
            error = f"❌ [VALIDATOR] Failed to check regime_detector.py: {e}"
            self.issues.append(error)
            print(error)
            return False
    
    def check_documentation_consistency(self, canonical_assets: List[str]) -> bool:
        """Verify replit.md Asset Universe section matches canonical config."""
        try:
            with open(self.replit_md_path, 'r') as f:
                content = f.read()
            
            match = re.search(r'\*\*Live Trading\*\*:\s*All \d+ coins\s*-\s*([A-Z,\s]+)', content)
            if not match:
                warning = "⚠️ [VALIDATOR] Could not find Asset Universe in replit.md"
                self.warnings.append(warning)
                print(warning)
                return True
            
            doc_symbols_str = match.group(1)
            doc_symbols = [s.strip() for s in doc_symbols_str.split(',') if s.strip()]
            
            canonical_set = set(canonical_assets)
            doc_set = set(doc_symbols)
            
            missing = canonical_set - doc_set
            extra = doc_set - canonical_set
            
            if missing or extra:
                warning = f"⚠️ [VALIDATOR] replit.md docs mismatch - Missing: {sorted(missing) if missing else 'none'}, Extra: {sorted(extra) if extra else 'none'}"
                self.warnings.append(warning)
                print(warning)
                return False
            
            print(f"✅ [VALIDATOR] replit.md Asset Universe matches canonical config ({len(doc_symbols)} symbols)")
            return True
            
        except Exception as e:
            warning = f"⚠️ [VALIDATOR] Failed to check replit.md: {e}"
            self.warnings.append(warning)
            print(warning)
            return True
    
    def check_venue_mappings(self, canonical_assets: List[str]) -> bool:
        """Verify all symbols have venue mappings in phase93_enforcement.py."""
        try:
            # Check if file exists
            if not os.path.exists("src/phase93_enforcement.py"):
                warning = "⚠️ [VALIDATOR] phase93_enforcement.py not found - skipping venue mapping check"
                self.warnings.append(warning)
                print(warning)
                return True
                
            with open("src/phase93_enforcement.py", 'r') as f:
                content = f.read()
            
            match = re.search(r'VENUE_MAP\s*=\s*\{(.*?)\}', content, re.DOTALL)
            if not match:
                # Try to find if venues are handled differently
                if "def get_venue" in content or "venue_policy" in content:
                    print(f"✅ [VALIDATOR] Venue mappings handled dynamically in phase93_enforcement.py")
                    return True
                    
                warning = "⚠️ [VALIDATOR] Could not find VENUE_MAP in phase93_enforcement.py"
                self.warnings.append(warning)
                print(warning)
                return True
            
            venue_map_str = match.group(1)
            mapped_symbols = set(re.findall(r'"([A-Z]+USDT)"', venue_map_str))
            
            canonical_set = set(canonical_assets)
            missing = canonical_set - mapped_symbols
            
            if missing:
                error = f"❌ [VALIDATOR] CRITICAL: Symbols missing from VENUE_MAP: {sorted(missing)}"
                self.issues.append(error)
                print(error)
                return False
            
            print(f"✅ [VALIDATOR] All {len(canonical_assets)} symbols have venue mappings")
            return True
            
        except Exception as e:
            warning = f"⚠️ [VALIDATOR] Failed to check venue mappings: {e}"
            self.warnings.append(warning)
            print(warning)
            return True
    
    def run_startup_checks(self) -> Tuple[bool, List[str], List[str]]:
        """
        Run all validation checks on bot startup.
        
        Returns:
            (passed, critical_issues, warnings)
        """
        print("=" * 70)
        print("🔍 CONFIGURATION VALIDATOR - Startup Checks")
        print("=" * 70)
        
        self.issues = []
        self.warnings = []
        
        canonical_assets = self.load_canonical_assets()
        if not canonical_assets:
            self.issues.append("No canonical assets loaded - cannot proceed")
            return False, self.issues, self.warnings
        
        checks = [
            ("Regime Detector Assets", self.check_regime_detector_assets(canonical_assets)),
            ("Documentation Consistency", self.check_documentation_consistency(canonical_assets)),
            ("Venue Mappings", self.check_venue_mappings(canonical_assets))
        ]
        
        all_passed = all(result for _, result in checks)
        
        print("=" * 70)
        if all_passed and not self.issues:
            print("✅ VALIDATION PASSED - All configuration checks successful")
        elif self.issues:
            print("❌ VALIDATION FAILED - Critical issues detected:")
            for issue in self.issues:
                print(f"   {issue}")
        
        if self.warnings:
            print("⚠️ WARNINGS - Non-critical issues:")
            for warning in self.warnings:
                print(f"   {warning}")
        
        print("=" * 70)
        
        return len(self.issues) == 0, self.issues, self.warnings


class RuntimeMonitor:
    """Monitor symbol coverage during bot cycles."""
    
    def __init__(self):
        self.expected_symbols = set()
        self.seen_symbols = set()
        self.cycle_count = 0
        
    def set_expected_symbols(self, symbols: List[str]):
        """Set the symbols we expect to see each cycle."""
        self.expected_symbols = set(symbols)
    
    def record_symbol_activity(self, symbol: str):
        """Record that a symbol was processed."""
        self.seen_symbols.add(symbol)
    
    def check_cycle_completeness(self) -> Tuple[bool, List[str]]:
        """Check if all expected symbols were seen this cycle."""
        self.cycle_count += 1
        
        missing = self.expected_symbols - self.seen_symbols
        
        if missing and self.cycle_count > 1:
            print(f"⚠️ [RUNTIME MONITOR] Cycle {self.cycle_count}: Missing symbols: {sorted(missing)}")
            return False, list(missing)
        
        if not missing:
            print(f"✅ [RUNTIME MONITOR] Cycle {self.cycle_count}: All {len(self.expected_symbols)} symbols processed")
        
        self.seen_symbols.clear()
        return len(missing) == 0, list(missing)


_validator = None
_runtime_monitor = None

def get_validator() -> ValidationOrchestrator:
    """Get singleton validator instance."""
    global _validator
    if _validator is None:
        _validator = ValidationOrchestrator()
    return _validator

def get_runtime_monitor() -> RuntimeMonitor:
    """Get singleton runtime monitor instance."""
    global _runtime_monitor
    if _runtime_monitor is None:
        _runtime_monitor = RuntimeMonitor()
    return _runtime_monitor


if __name__ == "__main__":
    validator = ValidationOrchestrator()
    passed, issues, warnings = validator.run_startup_checks()
    
    if not passed:
        print("\n❌ Validation failed!")
        exit(1)
    else:
        print("\n✅ Validation passed!")
        exit(0)
