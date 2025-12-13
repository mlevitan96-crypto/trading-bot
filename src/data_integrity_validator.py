#!/usr/bin/env python3
"""
DATA INTEGRITY VALIDATOR
========================
Comprehensive validation system to catch data reference issues BEFORE they cause problems.

This module:
1. Validates all critical data files exist and have correct schemas
2. Checks for stale/corrupt data
3. Maps data sources to consumers for debugging
4. Runs at startup to catch issues early
5. Can audit the codebase for bad data references

IMPORTANT: Uses DataRegistry as single source of truth for paths.

Usage:
    from src.data_integrity_validator import DataIntegrityValidator as DIV
    
    # Run full validation at startup
    issues = DIV.run_startup_validation()
    
    # Validate specific file
    DIV.validate_file("logs/portfolio.json")
    
    # Get canonical source for a data type
    source = DIV.get_canonical_source("trades")
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    DR = None

class DataIntegrityValidator:
    """
    Validates data integrity across the trading bot.
    Catches schema violations, missing keys, stale data, and wrong sources.
    """
    
    @classmethod
    def _get_canonical_sources(cls) -> Dict[str, Dict]:
        """
        Get canonical sources - uses DataRegistry if available, otherwise fallback.
        This ensures a SINGLE SOURCE OF TRUTH.
        
        IMPORTANT: logs/positions_futures.json is the ONLY canonical source for trades/positions.
        See docs/DATA_ARCHITECTURE.md for complete reference.
        """
        canonical_trades_path = getattr(DR, 'TRADES_CANONICAL', "logs/positions_futures.json") if DR else "logs/positions_futures.json"
        
        return {
            "trades_and_positions": {
                "path": canonical_trades_path,
                "type": "json",
                "description": "CANONICAL source for ALL trades and positions (open + closed)",
                "consumers": ["email_report", "dashboard", "performance_metrics", "learning", "risk_checks"],
                "schema_keys": ["open_positions", "closed_positions"]
            },
            "feedback_loop": {
                "path": "feature_store/feedback_loop_summary.json",
                "type": "json",
                "description": "Learning system feedback summary",
                "consumers": ["email_report", "learning_monitor"]
            },
            "enriched_decisions": {
                "path": getattr(DR, 'ENRICHED_DECISIONS', "logs/enriched_decisions.jsonl") if DR else "logs/enriched_decisions.jsonl",
                "type": "jsonl",
                "description": "Trade decisions with full context for learning",
                "consumers": ["scenario_replay", "pattern_discovery", "learning"]
            },
            "signals": {
                "path": getattr(DR, 'SIGNALS_UNIVERSE', "logs/signals.jsonl") if DR else "logs/signals.jsonl",
                "type": "jsonl",
                "description": "All signals (executed, blocked, skipped)",
                "consumers": ["counterfactual", "signal_analytics"]
            },
            "learning_history": {
                "path": "feature_store/learning_history.jsonl",
                "type": "jsonl",
                "description": "Learning events and parameter changes",
                "consumers": ["email_report", "learning_monitor"]
            }
        }
    
    # =========================================================================
    # SCHEMA DEFINITIONS - Required keys for each file
    # =========================================================================
    # =========================================================================
    # FIELD ALIASES - Different names for the same data across files
    # This is the CANONICAL mapping to prevent field mismatches
    # =========================================================================
    FIELD_ALIASES = {
        "pnl": {
            "canonical": "net_pnl_usd",
            "aliases": ["net_pnl", "net_profit", "profit", "pnl_usd", "realized_pnl", "pnl"],
            "description": "Net P&L after fees in USD",
            "sources": {
                "logs/trades_futures.json": "net_pnl",
                "logs/portfolio.json (trades array)": "net_profit",
                "logs/trades_futures_backup.json": "net_pnl"
            }
        },
        "gross_pnl": {
            "canonical": "gross_pnl_usd", 
            "aliases": ["gross_pnl", "gross_profit", "pnl_before_fees"],
            "description": "Gross P&L before fees in USD",
            "sources": {
                "logs/trades_futures.json": "gross_pnl",
                "logs/portfolio.json (trades array)": "gross_profit"
            }
        },
        "size": {
            "canonical": "size_usd",
            "aliases": ["notional_size", "position_size", "partial_size", "size_usd", "size", "margin_collateral"],
            "description": "Position size in USD",
            "sources": {
                "logs/trades_futures.json": "notional_size",
                "logs/portfolio.json (trades array)": "position_size OR partial_size"
            }
        },
        "timestamp": {
            "canonical": "ts",
            "aliases": ["ts", "timestamp", "time", "close_ts", "closed_at", "open_ts"],
            "description": "Unix timestamp or ISO string",
            "sources": {
                "logs/trades_futures.json": "timestamp",
                "logs/portfolio.json (trades array)": "timestamp"
            }
        }
    }
    
    SCHEMAS = {
        "logs/trades_futures.json": {
            "required_keys": ["trades"],
            "trade_required": ["symbol", "side", "margin_collateral", "net_pnl"],
            "trade_timestamp_fields": ["ts", "close_ts", "open_ts", "timestamp"],
            "description": "Must have 'trades' array with symbol, side, margin_collateral, net_pnl, and a timestamp field"
        },
        "logs/portfolio.json": {
            "required_keys": ["current_value", "snapshots"],
            "trades_array_fields": ["gross_profit", "net_profit", "timestamp", "symbol"],
            "trades_array_optional": ["position_size", "partial_size", "fees", "roi_pct"],
            "description": "Must have current_value number and snapshots array. Trades array uses net_profit (not profit)"
        },
        "feature_store/feedback_loop_summary.json": {
            "required_keys": ["timestamp", "direction_accuracy", "early_exit_rate", "exit_analysis", "direction_analysis"],
            "description": "Must have learning metrics at top level"
        },
        "data/positions_futures.json": {
            "required_keys": ["positions"],
            "description": "Must have positions array"
        },
        "logs/pnl_snapshots.jsonl": {
            "record_required": ["ts", "pnl"],
            "description": "Each record must have timestamp and pnl"
        }
    }
    
    # =========================================================================
    # DEPRECATED SOURCES - Files that should NOT be used
    # See docs/DATA_ARCHITECTURE.md for complete reference
    # =========================================================================
    DEPRECATED_SOURCES = {
        "logs/portfolio.json": "DEPRECATED: Contains 10,359 synthetic placeholder trades. Use logs/positions_futures.json",
        "logs/intraday_engine.jsonl": "Use logs/positions_futures.json for trade data",
        "logs/executed_trades.jsonl": "Use logs/positions_futures.json for trade data",
        "logs/alpha_trades.jsonl": "Use logs/positions_futures.json (filtered by bot_type='alpha')",
        "logs/trade_log.jsonl": "Use logs/positions_futures.json for trade data",
        "logs/trades_futures.json": "Use logs/positions_futures.json for trade data",
    }
    
    # =========================================================================
    # PLACEHOLDER TRADE DETECTION
    # Synthetic/invalid trades that should NOT be in the canonical source
    # Note: Positions use "direction" field (LONG/SHORT), not "side"
    # =========================================================================
    PLACEHOLDER_INDICATORS = {
        "strategy_unknown": lambda t: t.get("strategy", "").lower() == "unknown",
        "zero_pnl_closed": lambda t: t.get("exit_price") and t.get("closed_at") and float(t.get("realized_pnl", t.get("net_pnl", t.get("pnl", 999)))) == 0,
        "zero_exit_price_closed": lambda t: t.get("closed_at") and t.get("exit_price", 0) == 0 and t.get("entry_price", 0) > 0,
        "missing_symbol": lambda t: not t.get("symbol"),
        "missing_direction": lambda t: not t.get("side") and not t.get("direction"),
    }
    
    @classmethod
    def validate_no_placeholder_trades(cls, trades: list, source: str = "unknown") -> Dict:
        """
        Validate that a trades list contains no placeholder/synthetic trades.
        Returns dict with count of issues and details.
        """
        result = {
            "total_trades": len(trades),
            "placeholder_count": 0,
            "placeholders_by_type": {},
            "is_clean": True,
            "placeholder_ratio": 0.0
        }
        
        for trade in trades:
            is_placeholder = False
            for indicator_name, check_fn in cls.PLACEHOLDER_INDICATORS.items():
                try:
                    if check_fn(trade):
                        is_placeholder = True
                        result["placeholders_by_type"][indicator_name] = result["placeholders_by_type"].get(indicator_name, 0) + 1
                except:
                    pass
            if is_placeholder:
                result["placeholder_count"] += 1
        
        if result["total_trades"] > 0:
            result["placeholder_ratio"] = result["placeholder_count"] / result["total_trades"]
        
        if result["placeholder_ratio"] > 0.01:
            result["is_clean"] = False
        
        return result
    
    @classmethod
    def _validate_canonical_trades(cls, path: str) -> Dict:
        """
        Validate the canonical trades file for placeholder trades.
        This is the main protection against synthetic data pollution.
        """
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            
            all_trades = []
            all_trades.extend(data.get("open_positions", []))
            all_trades.extend(data.get("closed_positions", []))
            
            return cls.validate_no_placeholder_trades(all_trades, source=path)
            
        except Exception as e:
            return {
                "total_trades": 0,
                "placeholder_count": 0,
                "placeholders_by_type": {},
                "is_clean": True,
                "placeholder_ratio": 0.0,
                "error": str(e)
            }
    
    # =========================================================================
    # VALIDATION METHODS
    # =========================================================================
    
    @classmethod
    def validate_file(cls, path: str) -> Dict[str, Any]:
        """
        Validate a single file for existence, schema compliance, and freshness.
        Returns dict with status, issues, and recommendations.
        """
        result = {
            "path": path,
            "exists": False,
            "valid_schema": False,
            "fresh": False,
            "issues": [],
            "warnings": [],
            "data_sample": None
        }
        
        if not os.path.exists(path):
            result["issues"].append(f"File does not exist: {path}")
            return result
        
        result["exists"] = True
        
        try:
            stat = os.stat(path)
            result["size_bytes"] = stat.st_size
            result["last_modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
            
            age_hours = (time.time() - stat.st_mtime) / 3600
            result["age_hours"] = round(age_hours, 1)
            
            if stat.st_size == 0:
                result["issues"].append(f"File is empty: {path}")
                return result
            
            if path.endswith(".json"):
                with open(path, 'r') as f:
                    data = json.load(f)
                result["data_sample"] = cls._get_sample(data)
                result = cls._validate_json_schema(path, data, result)
            elif path.endswith(".jsonl"):
                result = cls._validate_jsonl(path, result)
            
            if age_hours > 24:
                result["warnings"].append(f"File is {age_hours:.1f} hours old - may be stale")
            else:
                result["fresh"] = True
                
        except json.JSONDecodeError as e:
            result["issues"].append(f"Invalid JSON: {e}")
        except Exception as e:
            result["issues"].append(f"Error reading file: {e}")
        
        if not result["issues"]:
            result["valid_schema"] = True
            
        return result
    
    @classmethod
    def validate_field_aliases(cls, source_path: str, record: Dict) -> List[str]:
        """
        Check if a record contains known field aliases and report which are present.
        Use this to verify loaders handle all necessary field variations.
        
        Returns list of warnings about field variations found.
        """
        warnings = []
        for field_type, config in cls.FIELD_ALIASES.items():
            found_aliases = [a for a in config["aliases"] if a in record]
            if len(found_aliases) > 1:
                warnings.append(f"Multiple aliases for '{field_type}' found: {found_aliases}")
            elif found_aliases:
                canonical = config["canonical"]
                actual = found_aliases[0]
                if actual != canonical:
                    pass
        return warnings
    
    @classmethod
    def get_field_mapping_report(cls) -> str:
        """
        Generate a report of all field aliases for documentation.
        Call this to understand field naming across different sources.
        """
        lines = ["=" * 60, "FIELD ALIAS MAPPING REPORT", "=" * 60, ""]
        for field_type, config in cls.FIELD_ALIASES.items():
            lines.append(f"## {field_type.upper()}")
            lines.append(f"   Canonical name: {config['canonical']}")
            lines.append(f"   Description: {config['description']}")
            lines.append(f"   Known aliases: {', '.join(config['aliases'])}")
            lines.append("   Per-source mapping:")
            for source, field in config.get("sources", {}).items():
                lines.append(f"      - {source}: uses '{field}'")
            lines.append("")
        return "\n".join(lines)
    
    @classmethod
    def _validate_json_schema(cls, path: str, data: Dict, result: Dict) -> Dict:
        """Validate JSON file against its schema."""
        schema = cls.SCHEMAS.get(path)
        if not schema:
            return result
        
        for key in schema.get("required_keys", []):
            if key not in data:
                result["issues"].append(f"Missing required key: '{key}'")
            elif data[key] is None:
                result["issues"].append(f"Required key '{key}' is None")
        
        if "trade_required" in schema and "trades" in data:
            trades = data.get("trades", [])
            if not trades:
                result["warnings"].append("Trades array is empty")
            else:
                sample_trade = trades[0] if trades else {}
                for key in schema["trade_required"]:
                    if key not in sample_trade:
                        result["issues"].append(f"Trade missing required key: '{key}'")
                ts_fields = schema.get("trade_timestamp_fields", [])
                if ts_fields and not any(f in sample_trade for f in ts_fields):
                    result["issues"].append(f"Trade missing timestamp field (one of: {ts_fields})")
        
        return result
    
    @classmethod
    def _validate_jsonl(cls, path: str, result: Dict) -> Dict:
        """Validate JSONL file."""
        try:
            valid_records = 0
            invalid_records = 0
            sample = None
            
            with open(path, 'r') as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        valid_records += 1
                        if sample is None:
                            sample = cls._get_sample(record)
                    except json.JSONDecodeError:
                        invalid_records += 1
                        if invalid_records <= 3:
                            result["warnings"].append(f"Invalid JSON on line {i+1}")
            
            result["valid_records"] = valid_records
            result["invalid_records"] = invalid_records
            result["data_sample"] = sample
            
            if invalid_records > valid_records * 0.1:
                result["issues"].append(f"High corruption rate: {invalid_records}/{valid_records+invalid_records} invalid")
                
        except Exception as e:
            result["issues"].append(f"Error reading JSONL: {e}")
        
        return result
    
    @classmethod
    def _get_sample(cls, data: Any, max_len: int = 200) -> str:
        """Get a truncated sample of data for debugging."""
        try:
            if isinstance(data, dict):
                sample = {k: type(v).__name__ for k, v in list(data.items())[:5]}
                return str(sample)[:max_len]
            elif isinstance(data, list):
                return f"List with {len(data)} items"
            return str(data)[:max_len]
        except:
            return "Unable to sample"
    
    # =========================================================================
    # STARTUP VALIDATION
    # =========================================================================
    
    @classmethod
    def run_startup_validation(cls, fix_issues: bool = True) -> Dict[str, Any]:
        """
        Run comprehensive validation at startup.
        Returns summary of all issues found.
        
        Includes placeholder trade detection to prevent synthetic data pollution.
        """
        print("\n" + "=" * 60)
        print("DATA INTEGRITY VALIDATION")
        print("=" * 60)
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "files_checked": 0,
            "files_valid": 0,
            "issues_found": [],
            "warnings": [],
            "fixes_applied": [],
            "placeholder_check": None,
            "status": "PASS"
        }
        
        for name, config in cls._get_canonical_sources().items():
            path = config["path"]
            print(f"\nChecking {name}: {path}")
            
            validation = cls.validate_file(path)
            results["files_checked"] += 1
            
            if validation["valid_schema"] and validation["exists"]:
                results["files_valid"] += 1
                print(f"  OK - {validation.get('data_sample', 'Valid')}")
                
                if name == "trades_and_positions":
                    print(f"\n  Checking for placeholder trades...")
                    placeholder_result = cls._validate_canonical_trades(path)
                    results["placeholder_check"] = placeholder_result
                    
                    if not placeholder_result["is_clean"]:
                        pct = placeholder_result["placeholder_ratio"] * 100
                        issue = f"PLACEHOLDER ALERT: {placeholder_result['placeholder_count']}/{placeholder_result['total_trades']} ({pct:.1f}%) trades are synthetic"
                        results["issues_found"].append({"file": path, "issue": issue, "data_type": name})
                        print(f"  CRITICAL: {issue}")
                        for ptype, count in placeholder_result["placeholders_by_type"].items():
                            print(f"    - {ptype}: {count}")
                    else:
                        print(f"  OK - No placeholder trades detected ({placeholder_result['total_trades']} trades clean)")
            else:
                for issue in validation["issues"]:
                    issue_record = {"file": path, "issue": issue, "data_type": name}
                    results["issues_found"].append(issue_record)
                    print(f"  ERROR: {issue}")
                    
                    if fix_issues:
                        fix = cls._auto_fix(path, issue, name)
                        if fix:
                            results["fixes_applied"].append(fix)
                            print(f"  FIXED: {fix}")
            
            for warning in validation.get("warnings", []):
                results["warnings"].append({"file": path, "warning": warning})
                print(f"  WARN: {warning}")
        
        if results["issues_found"]:
            results["status"] = "FAIL" if len([i for i in results["issues_found"] if "fixes_applied" not in str(i)]) > 0 else "FIXED"
        
        print("\n" + "-" * 60)
        print(f"VALIDATION RESULT: {results['status']}")
        print(f"Files checked: {results['files_checked']}")
        print(f"Files valid: {results['files_valid']}")
        print(f"Issues found: {len(results['issues_found'])}")
        print(f"Fixes applied: {len(results['fixes_applied'])}")
        print("=" * 60 + "\n")
        
        cls._save_validation_report(results)
        
        return results
    
    @classmethod
    def _auto_fix(cls, path: str, issue: str, data_type: str) -> Optional[str]:
        """Attempt to automatically fix common issues."""
        try:
            if "does not exist" in issue:
                cls._create_empty_file(path, data_type)
                return f"Created empty {path}"
            
            if "Missing required key: 'snapshots'" in issue and "portfolio" in path:
                with open(path, 'r') as f:
                    data = json.load(f)
                data["snapshots"] = data.get("snapshots", [])
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2)
                return "Added missing 'snapshots' key to portfolio.json"
            
            if "Missing required key: 'trades'" in issue and "trades" in path:
                with open(path, 'r') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    data = {"trades": data}
                    with open(path, 'w') as f:
                        json.dump(data, f, indent=2)
                    return "Wrapped trades array in {'trades': [...]}"
            
            if "Missing required key: 'positions'" in issue:
                cls._create_empty_file(path, "positions")
                return f"Created positions file with empty array"
                
        except Exception as e:
            print(f"  Auto-fix failed: {e}")
        
        return None
    
    @classmethod
    def _create_empty_file(cls, path: str, data_type: str):
        """Create an empty file with correct structure."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        defaults = {
            "trades": {"trades": []},
            "portfolio": {"current_value": 10000, "snapshots": [], "realized_pnl": 0},
            "feedback_loop": {"timestamp": datetime.now().isoformat(), "direction_accuracy": None, "early_exit_rate": None, "exit_analysis": {}, "direction_analysis": {}},
            "positions": {"positions": []},
        }
        
        if path.endswith(".json"):
            with open(path, 'w') as f:
                json.dump(defaults.get(data_type, {}), f, indent=2)
        elif path.endswith(".jsonl"):
            Path(path).touch()
    
    @classmethod
    def _save_validation_report(cls, results: Dict):
        """Save validation results for audit trail."""
        os.makedirs("logs", exist_ok=True)
        report_path = "logs/data_validation_report.json"
        
        try:
            history = []
            if os.path.exists(report_path):
                with open(report_path, 'r') as f:
                    history = json.load(f)
                    if not isinstance(history, list):
                        history = [history]
            
            history.append(results)
            history = history[-100:]
            
            with open(report_path, 'w') as f:
                json.dump(history, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: Could not save validation report: {e}")
    
    # =========================================================================
    # SOURCE LOOKUP
    # =========================================================================
    
    @classmethod
    def get_canonical_source(cls, data_type: str) -> Optional[str]:
        """Get the canonical file path for a data type."""
        config = cls._get_canonical_sources().get(data_type)
        return config["path"] if config else None
    
    @classmethod
    def is_deprecated(cls, path: str) -> Tuple[bool, Optional[str]]:
        """Check if a path is deprecated and get the recommended replacement."""
        if path in cls.DEPRECATED_SOURCES:
            return True, cls.DEPRECATED_SOURCES[path]
        return False, None
    
    @classmethod
    def get_consumers(cls, data_type: str) -> List[str]:
        """Get list of consumers for a data type."""
        config = cls._get_canonical_sources().get(data_type)
        return config.get("consumers", []) if config else []
    
    # =========================================================================
    # CODEBASE AUDIT
    # =========================================================================
    
    @classmethod
    def audit_codebase(cls, src_dir: str = "src") -> Dict[str, Any]:
        """
        Audit the codebase for bad data references.
        Returns report of issues found.
        """
        import re
        
        results = {
            "deprecated_usage": [],
            "hardcoded_paths": [],
            "unsafe_dict_access": [],
            "missing_registry_import": []
        }
        
        for root, dirs, files in os.walk(src_dir):
            for file in files:
                if not file.endswith(".py"):
                    continue
                
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r') as f:
                        content = f.read()
                        lines = content.split('\n')
                    
                    for deprecated_path, recommendation in cls.DEPRECATED_SOURCES.items():
                        if deprecated_path in content:
                            for i, line in enumerate(lines):
                                if deprecated_path in line and not line.strip().startswith('#'):
                                    results["deprecated_usage"].append({
                                        "file": filepath,
                                        "line": i + 1,
                                        "deprecated_path": deprecated_path,
                                        "recommendation": recommendation
                                    })
                    
                    path_pattern = r'"logs/[a-z_]+\.(json|jsonl)"'
                    for i, line in enumerate(lines):
                        if re.search(path_pattern, line) and 'data_registry' not in filepath:
                            if not line.strip().startswith('#'):
                                results["hardcoded_paths"].append({
                                    "file": filepath,
                                    "line": i + 1,
                                    "content": line.strip()[:80]
                                })
                    
                    if 'data_registry' not in filepath:
                        has_import = 'from src.data_registry' in content or 'import data_registry' in content
                        has_hardcoded = bool(re.search(path_pattern, content))
                        if has_hardcoded and not has_import:
                            results["missing_registry_import"].append({
                                "file": filepath,
                                "recommendation": "Add: from src.data_registry import DataRegistry as DR"
                            })
                    
                except Exception as e:
                    print(f"Error auditing {filepath}: {e}")
        
        return results
    
    @classmethod
    def print_audit_report(cls, src_dir: str = "src"):
        """Print a formatted audit report."""
        results = cls.audit_codebase(src_dir)
        
        print("\n" + "=" * 70)
        print("CODEBASE DATA REFERENCE AUDIT")
        print("=" * 70)
        
        print(f"\n DEPRECATED SOURCE USAGE ({len(results['deprecated_usage'])} issues)")
        print("-" * 50)
        for issue in results["deprecated_usage"][:10]:
            print(f"  {issue['file']}:{issue['line']}")
            print(f"    Uses: {issue['deprecated_path']}")
            print(f"    Fix: {issue['recommendation']}")
        if len(results['deprecated_usage']) > 10:
            print(f"  ... and {len(results['deprecated_usage']) - 10} more")
        
        print(f"\n HARDCODED PATHS ({len(results['hardcoded_paths'])} issues)")
        print("-" * 50)
        for issue in results["hardcoded_paths"][:10]:
            print(f"  {issue['file']}:{issue['line']}")
            print(f"    {issue['content']}")
        if len(results['hardcoded_paths']) > 10:
            print(f"  ... and {len(results['hardcoded_paths']) - 10} more")
        
        print(f"\n FILES MISSING DataRegistry IMPORT ({len(results['missing_registry_import'])} files)")
        print("-" * 50)
        for issue in results["missing_registry_import"][:10]:
            print(f"  {issue['file']}")
        
        print("\n" + "=" * 70)
        total_issues = sum(len(v) for v in results.values())
        print(f"TOTAL ISSUES: {total_issues}")
        print("=" * 70 + "\n")
        
        return results


DIV = DataIntegrityValidator


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "audit":
        DIV.print_audit_report()
    else:
        DIV.run_startup_validation(fix_issues=True)
