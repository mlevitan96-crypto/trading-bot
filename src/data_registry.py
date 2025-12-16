#!/usr/bin/env python3
"""
MASTER DATA REGISTRY - SINGLE SOURCE OF TRUTH
=============================================
ALL data paths in one place. Every module MUST import from here.
NEVER hardcode paths elsewhere in the codebase.

Usage:
    from src.data_registry import DataRegistry as DR
    
    # Get path:
    trades_path = DR.TRADES_CANONICAL
    
    # Validate path (warns if unregistered):
    DR.validate_path("logs/trades.jsonl")
    
    # Get reader/writer helpers:
    DR.append_trade(trade_dict)
    trades = DR.read_trades(last_n=100)

IMPORTANT: When adding new features, ADD THE PATH HERE FIRST.
Do NOT create new files without registering them in this module.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
from pathlib import Path
from src.infrastructure.path_registry import resolve_path, PathRegistry


class DataRegistry:
    """
    Canonical paths for ALL data in the trading bot.
    Organized by category.
    """
    
    # =========================================================================
    # TRADES & POSITIONS - SINGLE SOURCE OF TRUTH
    # logs/positions_futures.json is the AUTHORITATIVE MASTER for ALL:
    #   - "open_positions": [] array of current active trades
    #   - "closed_positions": [] array of completed trades with P&L
    #   - Each position has bot_type ("alpha" or "beta") for filtering
    #
    # IMPORTANT: This is the ONLY canonical source for trade/position data.
    # See docs/DATA_ARCHITECTURE.md for complete schema and ownership.
    #
    # NOTE: Paths are stored as relative strings, but resolved to absolute
    # via resolve_path() in all read/write operations for slot-based deployments.
    # =========================================================================
    TRADES_CANONICAL = "logs/positions_futures.json"
    POSITIONS_FUTURES = "logs/positions_futures.json"
    PORTFOLIO_MASTER = "logs/positions_futures.json"  # All aliases point to same file
    
    # DEPRECATED - DO NOT USE (contained synthetic placeholder trades)
    _DEPRECATED_PORTFOLIO = "logs/portfolio.json"
    
    # Legacy paths (DO NOT USE - for migration/backup only)
    _LEGACY_TRADES = [
        "logs/portfolio.json",  # DEPRECATED: Had 10,359 placeholder trades
        "logs/alpha_trades.jsonl",
        "logs/executed_trades.jsonl",
        "logs/trades_futures.jsonl",
        "logs/trade_log.jsonl",
        "logs/trades.jsonl",
        "logs/trades_futures_backup.json",
    ]
    
    # Legacy paths (DO NOT USE)
    _LEGACY_POSITIONS = [
        "data/positions_futures.json",  # Old location, migrate to logs/
    ]
    
    # =========================================================================
    # SIGNALS - ALL signals (executed + blocked + skipped)
    # =========================================================================
    # Use PathRegistry for absolute path resolution (critical for slot-based deployments)
    SIGNALS_UNIVERSE = PathRegistry.get_path("logs", "signals.jsonl")
    
    # Legacy paths (DO NOT USE)
    _LEGACY_SIGNALS = [
        "logs/signal_universe.jsonl",
        "logs/blocked_signals.jsonl",
        "logs/alpha_signals_274_275.jsonl",
    ]
    
    # =========================================================================
    # DECISIONS - Enriched decision records with outcomes
    # =========================================================================
    ENRICHED_DECISIONS = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
    COUNTERFACTUAL_OUTCOMES = "logs/counterfactual_outcomes.jsonl"
    
    # =========================================================================
    # LEARNING - Rules and models from learning system
    # =========================================================================
    LEARNED_RULES = "feature_store/learned_rules.json"
    PATTERN_DISCOVERIES = "feature_store/pattern_discoveries.json"
    ADAPTIVE_WEIGHTS = "feature_store/adaptive_weights.json"
    COUNTERFACTUAL_LEARNINGS = "feature_store/counterfactual_learnings.json"
    MISSED_OPPORTUNITIES = "logs/missed_opportunities.jsonl"
    CORRELATION_REPORT = "reports/full_correlation_analysis.json"
    GATE_FEEDBACK = "feature_store/gate_feedback.json"
    OFFENSIVE_RULES = "feature_store/offensive_rules.json"
    AGGRESSIVE_LEARNING = "feature_store/aggressive_learning_results.json"
    
    # =========================================================================
    # TIME FILTER SCENARIOS - Counterfactual analysis for time-based filters
    # Tracks what would have happened with different time filter configurations
    # =========================================================================
    TIME_FILTER_SCENARIOS = "logs/time_filter_scenarios.jsonl"
    
    # =========================================================================
    # PROFITABILITY ACCELERATION - Pattern & timing optimization
    # =========================================================================
    OPPORTUNITY_SCORES = "feature_store/opportunity_scores.json"
    HOLD_TIME_RULES = "feature_store/hold_time_rules.json"
    EXIT_TIMING_MFE = "feature_store/exit_timing_mfe.json"
    BACKTEST_RESULTS = "feature_store/backtest_results.json"
    DAILY_LEARNING_RULES = "feature_store/daily_learning_rules.json"
    MOMENTUM_ANALYSIS = "feature_store/momentum_analysis.json"
    
    # =========================================================================
    # STRATEGIC ADVISOR - Proactive profitability intelligence
    # =========================================================================
    STRATEGIC_ADVISOR_STATE = "feature_store/strategic_advisor_state.json"
    STRATEGIC_ADVISOR_LOG = "logs/strategic_advisor_insights.jsonl"
    
    # =========================================================================
    # FEE-AWARE ENTRY GATE - Blocks trades where expected_move < fees
    # =========================================================================
    FEE_GATE_STATE = "feature_store/fee_gate_state.json"
    FEE_GATE_LOG = "logs/fee_entry_blocks.jsonl"
    
    # =========================================================================
    # HOLD TIME ENFORCEMENT - Prevents premature exits
    # =========================================================================
    HOLD_TIME_POLICY = "feature_store/hold_time_policy.json"
    HOLD_TIME_LOG = "logs/hold_time_enforcement.jsonl"
    
    # =========================================================================
    # EDGE-WEIGHTED SIZING - Size based on signal quality grade
    # =========================================================================
    EDGE_SIZING_LOG = "logs/edge_sizing_decisions.jsonl"
    
    # =========================================================================
    # CORRELATION THROTTLE - Reduces exposure when assets are correlated
    # =========================================================================
    CORRELATION_THROTTLE_STATE = "feature_store/correlation_throttle_state.json"
    CORRELATION_THROTTLE_LOG = "logs/correlation_throttle.jsonl"
    
    # =========================================================================
    # MARKET INTELLIGENCE - CoinGlass and external data
    # =========================================================================
    MARKET_INTEL_CACHE = "feature_store/market_intelligence.json"
    COINGLASS_DIR = "feature_store/coinglass"
    INTELLIGENCE_DIR = "feature_store/intelligence"
    
    # =========================================================================
    # ENHANCED ML PIPELINE (Phase 16.0) - Deep Learning & Multi-Model Ensemble
    # =========================================================================
    # Sentiment Analysis
    SENTIMENT_DIR = "feature_store/sentiment"
    SENTIMENT_CACHE = "feature_store/sentiment/latest.json"
    SENTIMENT_HISTORY = "feature_store/sentiment/history.jsonl"
    
    # On-Chain Analytics
    ONCHAIN_DIR = "feature_store/onchain"
    ONCHAIN_WHALE_CACHE = "feature_store/onchain/whale_alerts.json"
    ONCHAIN_FLOWS_CACHE = "feature_store/onchain/exchange_flows.json"
    
    # ML Models
    ML_MODELS_DIR = "models"
    ML_GBM_MODELS = "models/gbm"
    ML_LSTM_MODELS = "models/lstm"
    ML_ENSEMBLE_CONFIG = "feature_store/ensemble_config.json"
    ML_TRAINING_DATASET = "feature_store/training_dataset.json"
    ML_VALIDATION_RESULTS = "feature_store/ml_validation_results.json"
    
    # Prediction Logs
    ML_PREDICTIONS_LOG = "logs/ml_predictions.jsonl"
    ENSEMBLE_PREDICTIONS_LOG = PathRegistry.get_path("logs", "ensemble_predictions.jsonl")
    
    # =========================================================================
    # CONFIGS - System configuration (mostly read-only)
    # =========================================================================
    LIVE_CONFIG = "live_config.json"
    # CANONICAL path - config/ is the primary, configs/ is legacy fallback
    ASSET_UNIVERSE = "config/asset_universe.json"
    ASSET_UNIVERSE_LEGACY = "configs/asset_universe.json"
    COMPOSITE_WEIGHTS = "configs/composite_weights.json"
    
    # =========================================================================
    # RUNTIME STATE - Dynamic state files
    # =========================================================================
    KILL_SWITCH_STATE = "state/kill_switch.json"
    HEALTH_STATE = "state/health_pulse.json"
    
    # =========================================================================
    # AUDIT - System audit trails
    # =========================================================================
    AUDIT_CHAIN = "logs/audit_chain.jsonl"
    PIPELINE_AUDIT = "logs/full_pipeline_audit.jsonl"
    
    # =========================================================================
    # P&L TRACKING - Performance metrics
    # =========================================================================
    PNL_SNAPSHOTS = "logs/pnl_snapshots.jsonl"
    PORTFOLIO_HISTORY = "logs/portfolio_history.jsonl"
    
    # =========================================================================
    # REPORTS - Generated reports
    # =========================================================================
    REPORTS_DIR = "reports"
    
    # =========================================================================
    # ALL REGISTERED PATHS (for validation)
    # =========================================================================
    _REGISTERED_PATHS = None
    
    @classmethod
    def _get_all_registered(cls) -> set:
        """Get all registered canonical paths."""
        if cls._REGISTERED_PATHS is None:
            paths = set()
            for attr in dir(cls):
                if attr.startswith('_') or attr.startswith('LEGACY'):
                    continue
                val = getattr(cls, attr)
                if isinstance(val, str) and ('/' in val or '.' in val):
                    paths.add(val)
            cls._REGISTERED_PATHS = paths
        return cls._REGISTERED_PATHS
    
    @classmethod
    def validate_path(cls, path: str, warn: bool = True) -> bool:
        """
        Check if a path is registered in the canonical list.
        Use this before reading/writing to catch unregistered paths.
        """
        registered = cls._get_all_registered()
        if path in registered:
            return True
        
        # Check if it's a legacy path
        all_legacy = (cls._LEGACY_TRADES + cls._LEGACY_POSITIONS + 
                      cls._LEGACY_SIGNALS)
        if path in all_legacy:
            if warn:
                print(f"⚠️ LEGACY PATH USED: {path}")
                print(f"   Migrate to canonical path from DataRegistry")
            return False
        
        if warn:
            print(f"⚠️ UNREGISTERED PATH: {path}")
            print(f"   Add to src/data_registry.py before using")
        return False
    
    @classmethod
    def ensure_dirs(cls):
        """Create all required directories."""
        dirs = [
            "logs", "data", "state", "reports", "feature_store",
            "feature_store/coinglass", "configs", "backups"
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
    
    # =========================================================================
    # HELPER METHODS - Common read/write operations
    # =========================================================================
    
    @classmethod
    def append_jsonl(cls, path: str, record: Dict[str, Any]) -> bool:
        """Safely append a record to a JSONL file. Resolves relative paths to absolute for slot-based deployments."""
        try:
            cls.ensure_dirs()
            # Resolve relative paths to absolute (handles trading-bot-A/B slot deployments)
            abs_path = resolve_path(path) if not os.path.isabs(path) else path
            # Add timestamp if not present
            if 'ts' not in record and 'timestamp' not in record:
                record['ts'] = time.time()
                record['ts_iso'] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            
            with open(abs_path, 'a') as f:
                f.write(json.dumps(record, default=str) + '\n')
            return True
        except Exception as e:
            print(f"Error writing to {abs_path if 'abs_path' in locals() else path}: {e}")
            return False
    
    @classmethod
    def read_jsonl(cls, path: str, last_n: Optional[int] = None) -> List[Dict]:
        """Read records from a JSONL file. Resolves relative paths to absolute for slot-based deployments."""
        # Resolve relative paths to absolute (handles trading-bot-A/B slot deployments)
        abs_path = resolve_path(path) if not os.path.isabs(path) else path
        if not os.path.exists(abs_path):
            return []
        
        try:
            records = []
            with open(abs_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            
            if last_n and len(records) > last_n:
                return records[-last_n:]
            return records
        except Exception as e:
            print(f"Error reading {abs_path}: {e}")
            return []
    
    @classmethod
    def read_json(cls, path: str) -> Optional[Dict]:
        """Read a JSON file. Resolves relative paths to absolute for slot-based deployments."""
        # Resolve relative paths to absolute (handles trading-bot-A/B slot deployments)
        abs_path = resolve_path(path) if not os.path.isabs(path) else path
        if not os.path.exists(abs_path):
            return None
        try:
            with open(abs_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading {abs_path}: {e}")
            return None
    
    @classmethod
    def write_json(cls, path: str, data: Dict, indent: int = 2) -> bool:
        """Safely write a JSON file. Resolves relative paths to absolute for slot-based deployments."""
        try:
            cls.ensure_dirs()
            # Resolve relative paths to absolute (handles trading-bot-A/B slot deployments)
            abs_path = resolve_path(path) if not os.path.isabs(path) else path
            # Write to temp file first, then rename (atomic)
            tmp_path = abs_path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=indent, default=str)
            os.rename(tmp_path, abs_path)
            return True
        except Exception as e:
            print(f"Error writing to {abs_path if 'abs_path' in locals() else path}: {e}")
            return False
    
    # =========================================================================
    # TRADE-SPECIFIC HELPERS (portfolio.json structure)
    # =========================================================================
    
    @classmethod
    def log_trade(cls, trade: Dict[str, Any], source: str = "unknown") -> bool:
        """
        Log a trade to the canonical portfolio.json master file.
        Appends to the "trades" array within the JSON structure.
        """
        try:
            trade['source'] = source
            if 'timestamp' not in trade and 'ts' not in trade:
                import time
                trade['timestamp'] = time.strftime("%Y-%m-%dT%H:%M:%S")
            
            # Read existing portfolio
            portfolio = cls.read_json(cls.PORTFOLIO_MASTER) or {"trades": [], "open_positions": []}
            if "trades" not in portfolio:
                portfolio["trades"] = []
            
            portfolio["trades"].append(trade)
            # Use safe write with backup for critical portfolio data
            return cls.safe_write_json_with_backup(cls.PORTFOLIO_MASTER, portfolio)
        except Exception as e:
            print(f"Error logging trade: {e}")
            return False
    
    @classmethod
    def get_trades(cls, last_n: Optional[int] = None, 
                   symbol: Optional[str] = None,
                   hours: Optional[float] = None) -> List[Dict]:
        """
        Get trades from canonical portfolio.json master file.
        
        Args:
            last_n: Return only last N trades
            symbol: Filter by symbol
            hours: Filter to trades within last N hours
        """
        portfolio = cls.read_json(cls.PORTFOLIO_MASTER)
        if not portfolio:
            return []
        
        trades = portfolio.get("trades", [])
        
        # Filter by hours if specified
        if hours:
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            cutoff_ts = cutoff.timestamp()
            
            filtered = []
            for t in trades:
                # Try multiple timestamp field names
                ts_str = t.get('timestamp') or t.get('close_time') or t.get('entry_time') or t.get('ts_iso')
                if ts_str:
                    try:
                        if isinstance(ts_str, (int, float)):
                            trade_ts = ts_str
                        else:
                            # Parse ISO format
                            ts_clean = ts_str.replace('Z', '+00:00')
                            if '.' in ts_clean and '+' in ts_clean:
                                ts_clean = ts_clean.split('.')[0] + '+' + ts_clean.split('+')[1]
                            elif '.' in ts_clean and '-' in ts_clean.split('T')[1]:
                                parts = ts_clean.split('-')
                                ts_clean = '-'.join(parts[:-1]).split('.')[0] + '-' + parts[-1]
                            dt = datetime.fromisoformat(ts_clean.replace('Z', '+00:00'))
                            trade_ts = dt.timestamp()
                        
                        if trade_ts >= cutoff_ts:
                            filtered.append(t)
                    except:
                        # Include trades with unparseable timestamps
                        filtered.append(t)
            trades = filtered
        
        # Filter by symbol
        if symbol:
            trades = [t for t in trades if t.get('symbol') == symbol]
        
        # Limit to last N
        if last_n and len(trades) > last_n:
            trades = trades[-last_n:]
        
        return trades
    
    @classmethod
    def get_open_positions(cls) -> List[Dict]:
        """Get current open positions from positions_futures.json (the authoritative source)."""
        # Open positions are actively tracked in positions_futures.json
        positions_data = cls.read_json(cls.POSITIONS_FUTURES)
        if not positions_data:
            return []
        return positions_data.get("open_positions", [])
    
    @classmethod
    def get_closed_positions(cls, hours: Optional[int] = 168) -> List[Dict]:
        """Get closed positions from positions_futures.json (the authoritative source)."""
        positions_data = cls.read_json(cls.POSITIONS_FUTURES)
        if not positions_data:
            return []
        closed = positions_data.get("closed_positions", [])
        
        # Filter by time if hours specified
        if hours and closed:
            from datetime import datetime, timedelta
            cutoff_ts = (datetime.utcnow() - timedelta(hours=hours)).timestamp()
            filtered = []
            for p in closed:
                ts_str = p.get('closed_at') or p.get('timestamp')
                if ts_str:
                    try:
                        if isinstance(ts_str, (int, float)):
                            pos_ts = ts_str
                        else:
                            ts_clean = ts_str.replace('Z', '+00:00')
                            if '.' in ts_clean and '+' in ts_clean:
                                ts_clean = ts_clean.split('.')[0] + '+' + ts_clean.split('+')[1]
                            dt = datetime.fromisoformat(ts_clean)
                            pos_ts = dt.timestamp()
                        if pos_ts >= cutoff_ts:
                            filtered.append(p)
                    except:
                        filtered.append(p)
                else:
                    filtered.append(p)
            return filtered
        return closed
    
    # =========================================================================
    # SQLITE DATABASE READ METHODS (Phase 4 Tri-Layer Architecture)
    # These methods read from SQLite for analytics/dashboard use cases.
    # OPEN positions still read from JSONL (actively managed by the bot).
    # CLOSED positions and SIGNALS for analytics come from SQLite.
    # =========================================================================
    
    @classmethod
    def get_closed_trades_from_db(cls, limit: int = None, symbol: str = None) -> List[Dict]:
        """
        Get closed trades from SQLite database.
        Use this for dashboard analytics and historical analysis.
        Falls back to JSONL if SQLite is unavailable.
        """
        try:
            from src.infrastructure.database import get_closed_trades_sync
            trades = get_closed_trades_sync(limit=limit, symbol=symbol)
            if trades:
                return trades
        except Exception as e:
            print(f"[DataRegistry] SQLite read failed, falling back to JSONL: {e}")
        
        return cls.get_closed_positions(hours=None)
    
    @classmethod
    def get_signals_from_db(cls, limit: int = None, signal_name: str = None) -> List[Dict]:
        """
        Get signals from SQLite database.
        Use this for learning/analytics use cases.
        Falls back to JSONL if SQLite is unavailable.
        """
        try:
            from src.infrastructure.database import get_signals_sync
            signals = get_signals_sync(limit=limit, signal_name=signal_name)
            if signals:
                return signals
        except Exception as e:
            print(f"[DataRegistry] SQLite signals read failed, falling back to JSONL: {e}")
        
        return cls.get_signals(last_n=limit)
    
    @classmethod
    def get_recent_signals_from_db(cls, hours: int = 24) -> List[Dict]:
        """
        Get recent signals from SQLite database.
        Use this for direction router and real-time learning.
        """
        try:
            from src.infrastructure.database import get_recent_signals_sync
            signals = get_recent_signals_sync(hours=hours)
            if signals:
                return signals
        except Exception as e:
            print(f"[DataRegistry] SQLite recent signals read failed: {e}")
        
        return []
    
    # =========================================================================
    # SIGNAL-SPECIFIC HELPERS
    # =========================================================================
    
    @classmethod
    def log_signal(cls, signal: Dict[str, Any]) -> bool:
        """Log a signal to the canonical signals file."""
        return cls.append_jsonl(cls.SIGNALS_UNIVERSE, signal)
    
    @classmethod
    def get_signals(cls, last_n: Optional[int] = None,
                    disposition: Optional[str] = None) -> List[Dict]:
        """Get signals, optionally filtered by disposition."""
        signals = cls.read_jsonl(cls.SIGNALS_UNIVERSE, last_n=last_n)
        if disposition:
            signals = [s for s in signals if s.get('disposition') == disposition]
        return signals
    
    # =========================================================================
    # POSITIONS HELPERS
    # =========================================================================
    
    @classmethod
    def get_positions(cls) -> Dict:
        """Get current positions from canonical file."""
        data = cls.read_json(cls.POSITIONS_FUTURES)
        return data or {"positions": []}
    
    @classmethod
    def save_positions(cls, data: Dict) -> bool:
        """Save positions to canonical file."""
        return cls.write_json(cls.POSITIONS_FUTURES, data)
    
    @classmethod
    def clean_ghost_positions(cls) -> int:
        """
        Remove ghost positions (no size, no timestamp).
        Returns count of positions removed.
        
        CRITICAL: This bot runs in PAPER TRADING mode. Positions exist only
        locally in JSON files, not on any exchange. We must NOT delete
        valid paper positions during cleanup.
        
        A position is valid if it has EITHER:
          - size > 0 OR size_usd > 0 (supports both field names)
          - opened_at is set OR entry_ts > 0 (supports both field names)
        """
        removed = 0
        
        for file_path in [cls.POSITIONS_FUTURES, cls.PORTFOLIO_MASTER]:
            try:
                data = cls.read_json(file_path)
                if not data:
                    continue
                
                open_key = 'open_positions'
                if open_key in data:
                    original_count = len(data[open_key])
                    valid_positions = []
                    for p in data[open_key]:
                        has_size = (p.get('size', 0) or 0) > 0 or (p.get('size_usd', 0) or 0) > 0
                        has_timestamp = bool(p.get('opened_at')) or (p.get('entry_ts', 0) or 0) > 0
                        if has_size and has_timestamp:
                            valid_positions.append(p)
                        else:
                            print(f"[DataRegistry] Removing truly ghost position: {p.get('symbol', 'unknown')} - no size or timestamp")
                    
                    removed_count = original_count - len(valid_positions)
                    if removed_count > 0:
                        data[open_key] = valid_positions
                        cls.write_json(file_path, data)
                        removed += removed_count
            except Exception as e:
                print(f"[DataRegistry] Ghost cleanup error for {file_path}: {e}")
        
        if removed > 0:
            print(f"[DataRegistry] Cleaned {removed} ghost positions")
        return removed
    
    # =========================================================================
    # MARKET INTELLIGENCE HELPERS
    # =========================================================================
    
    @classmethod
    def get_coinglass_features(cls, symbol: str) -> Optional[Dict]:
        """Get cached CoinGlass features for a symbol."""
        path = os.path.join(cls.COINGLASS_DIR, f"{symbol}_coinglass_features.json")
        return cls.read_json(path)
    
    @classmethod
    def save_coinglass_features(cls, symbol: str, data: Dict) -> bool:
        """Save CoinGlass features for a symbol."""
        os.makedirs(cls.COINGLASS_DIR, exist_ok=True)
        path = os.path.join(cls.COINGLASS_DIR, f"{symbol}_coinglass_features.json")
        return cls.write_json(path, data)
    
    # =========================================================================
    # MIGRATION HELPERS
    # =========================================================================
    
    @classmethod
    def migrate_legacy_trades(cls, dry_run: bool = True) -> Dict[str, int]:
        """
        Migrate all legacy trade files to canonical location.
        Returns count of records migrated from each file.
        """
        stats = {}
        for legacy_path in cls._LEGACY_TRADES:
            if os.path.exists(legacy_path):
                records = cls.read_jsonl(legacy_path)
                stats[legacy_path] = len(records)
                if not dry_run:
                    for record in records:
                        # Tag with source
                        if 'source' not in record:
                            record['source'] = f"migrated_from_{Path(legacy_path).stem}"
                        cls.append_jsonl(cls.TRADES_CANONICAL, record)
                    print(f"Migrated {len(records)} records from {legacy_path}")
        return stats
    
    @classmethod
    def migrate_legacy_signals(cls, dry_run: bool = True) -> Dict[str, int]:
        """
        Migrate all legacy signal files to canonical location.
        """
        stats = {}
        for legacy_path in cls._LEGACY_SIGNALS:
            if os.path.exists(legacy_path):
                records = cls.read_jsonl(legacy_path)
                stats[legacy_path] = len(records)
                if not dry_run:
                    for record in records:
                        cls.append_jsonl(cls.SIGNALS_UNIVERSE, record)
                    print(f"Migrated {len(records)} signals from {legacy_path}")
        return stats


    # =========================================================================
    # DATA SYNC HELPERS
    # =========================================================================
    
    @classmethod
    def sync_portfolio_from_futures(cls) -> Dict[str, Any]:
        """
        Sync portfolio.json open_positions from positions_futures.json.
        Ensures dashboard and other consumers see consistent data.
        Returns sync stats.
        """
        stats = {"synced": False, "open_positions": 0, "error": None}
        
        try:
            # Read current futures positions (authoritative)
            futures_data = cls.read_json(cls.POSITIONS_FUTURES)
            if not futures_data:
                stats["error"] = "positions_futures.json not found or empty"
                return stats
            
            open_positions = futures_data.get("open_positions", [])
            stats["open_positions"] = len(open_positions)
            
            # Read and update portfolio
            portfolio = cls.read_json(cls.PORTFOLIO_MASTER)
            if portfolio is None:
                portfolio = {"starting_capital": 10000, "current_value": 10000, "trades": [], "snapshots": []}
            
            # Sync open positions
            portfolio["open_positions"] = open_positions
            
            # Write back with safe write and backup for critical portfolio data
            cls.safe_write_json_with_backup(cls.PORTFOLIO_MASTER, portfolio)
            stats["synced"] = True
            
            print(f"📊 [SYNC] Synced {len(open_positions)} open positions to portfolio.json")
            return stats
            
        except Exception as e:
            stats["error"] = str(e)
            print(f"⚠️  [SYNC] Failed to sync portfolio: {e}")
            return stats
    
    @classmethod
    def validate_data_integrity(cls) -> Dict[str, Any]:
        """
        Run data integrity checks across all canonical files.
        Returns validation report.
        """
        report = {
            "valid": True,
            "issues": [],
            "stats": {}
        }
        
        # Check positions_futures.json
        futures_data = cls.read_json(cls.POSITIONS_FUTURES)
        if futures_data:
            open_count = len(futures_data.get("open_positions", []))
            closed_count = len(futures_data.get("closed_positions", []))
            report["stats"]["positions_futures"] = {
                "open": open_count,
                "closed": closed_count
            }
        else:
            report["issues"].append("positions_futures.json missing or empty")
            report["valid"] = False
        
        # Check portfolio.json
        portfolio = cls.read_json(cls.PORTFOLIO_MASTER)
        if portfolio:
            trade_count = len(portfolio.get("trades", []))
            report["stats"]["portfolio"] = {
                "trades": trade_count,
                "current_value": portfolio.get("current_value", 0)
            }
            
            # Check for sync mismatch
            portfolio_open = len(portfolio.get("open_positions", []))
            if futures_data and portfolio_open != open_count:
                report["issues"].append(
                    f"Open positions mismatch: portfolio has {portfolio_open}, futures has {open_count}"
                )
        else:
            report["issues"].append("portfolio.json missing or empty")
            report["valid"] = False
        
        if report["issues"]:
            report["valid"] = False
        
        return report
    
    # =========================================================================
    # ASSET UNIVERSE HELPERS - Dynamic symbol loading
    # =========================================================================
    
    @classmethod
    def get_enabled_symbols(cls, venue: str = "futures") -> List[str]:
        """
        Get list of enabled trading symbols from config/asset_universe.json.
        
        CRITICAL: ALL modules MUST use this instead of hardcoded lists.
        
        Args:
            venue: Filter by venue type (default: "futures")
            
        Returns:
            List of enabled symbol strings (e.g., ["BTCUSDT", "ETHUSDT", ...])
        """
        try:
            # Try canonical path first, then legacy fallback
            config = cls.read_json(cls.ASSET_UNIVERSE)
            if not config:
                config = cls.read_json(cls.ASSET_UNIVERSE_LEGACY)
                if config:
                    print("📋 [DataRegistry] Using legacy asset_universe path")
            
            if not config:
                print("⚠️ [DataRegistry] asset_universe.json not found, using fallback")
                return cls._FALLBACK_SYMBOLS
            
            assets = config.get("asset_universe", [])
            enabled = [
                a["symbol"] for a in assets 
                if a.get("enabled", True) and a.get("venue", "futures") == venue
            ]
            
            if not enabled:
                print("⚠️ [DataRegistry] No enabled symbols found, using fallback")
                return cls._FALLBACK_SYMBOLS
            
            # Log loaded symbols for visibility
            print(f"📋 [DataRegistry] Loaded {len(enabled)} enabled symbols from config")
            return enabled
        except Exception as e:
            print(f"⚠️ [DataRegistry] Error loading asset universe: {e}")
            return cls._FALLBACK_SYMBOLS
    
    # Fallback symbols in case config is missing (should never happen in production)
    _FALLBACK_SYMBOLS = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "DOTUSDT",
        "TRXUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "BNBUSDT", 
        "LINKUSDT", "ARBUSDT", "OPUSDT", "PEPEUSDT"
    ]
    
    @classmethod
    def get_symbol_tiers(cls) -> Dict[str, List[str]]:
        """Get symbols organized by tier (major, l1, l2, meme, defi)."""
        try:
            config = cls.read_json(cls.ASSET_UNIVERSE)
            if not config:
                return {"all": cls._FALLBACK_SYMBOLS}
            
            tiers = {}
            for asset in config.get("asset_universe", []):
                if not asset.get("enabled", True):
                    continue
                tier = asset.get("tier", "other")
                if tier not in tiers:
                    tiers[tier] = []
                tiers[tier].append(asset["symbol"])
            return tiers
        except Exception as e:
            print(f"⚠️ [DataRegistry] Error loading symbol tiers: {e}")
            return {"all": cls._FALLBACK_SYMBOLS}
    
    # =========================================================================
    # SAFE WRITE WITH BACKUP - Critical data protection
    # =========================================================================
    
    @classmethod
    def safe_write_json_with_backup(cls, path: str, data: Dict, 
                                     max_backups: int = 5) -> bool:
        """
        Safely write JSON with automatic backup and integrity verification.
        
        1. Creates backup of existing file before overwrite
        2. Writes to temp file first
        3. Verifies the write by reading back
        4. Only then replaces original
        5. Maintains rolling backup history
        
        Use for CRITICAL files like portfolio.json, positions_futures.json
        """
        try:
            cls.ensure_dirs()
            os.makedirs("logs/backups", exist_ok=True)
            
            # Step 1: Create backup of existing file (rotate happens after validation)
            if os.path.exists(path):
                import shutil
                from datetime import datetime
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{Path(path).stem}_{timestamp}.json"
                backup_path = f"logs/backups/{backup_name}"
                shutil.copy2(path, backup_path)
            
            # Step 2: Write to temp file with fsync for durability
            tmp_path = path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)
                f.flush()
                os.fsync(f.fileno())
            
            # Step 3: Verify temp file is valid JSON before rename
            with open(tmp_path, 'r') as f:
                verify_data = json.load(f)
            
            # Step 4: Atomic rename
            os.rename(tmp_path, path)
            
            # Step 5: CRITICAL - Verify the FINAL file after rename to catch disk flush failures
            with open(path, 'r') as f:
                final_verify = json.load(f)
            
            # Step 6: Only rotate backups after final validation passes
            if os.path.exists(path):
                cls._rotate_backups(Path(path).stem, max_backups)
            
            return True
        except Exception as e:
            print(f"❌ [DataRegistry] Safe write failed for {path}: {e}")
            # Try to clean up temp file
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except:
                pass
            return False
    
    @classmethod
    def _rotate_backups(cls, file_stem: str, max_backups: int, min_keep: int = 1):
        """
        Keep only the most recent N backups, but ALWAYS preserve at least min_keep.
        This ensures recovery is possible even after rotation.
        """
        try:
            backup_dir = Path("logs/backups")
            if not backup_dir.exists():
                return
            
            backups = sorted(
                backup_dir.glob(f"{file_stem}_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            # CRITICAL: Always keep at least min_keep backups for recovery
            keep_count = max(max_backups, min_keep)
            
            for old_backup in backups[keep_count:]:
                old_backup.unlink()
        except Exception as e:
            print(f"⚠️ [DataRegistry] Backup rotation failed: {e}")
    
    @classmethod
    def restore_from_backup(cls, path: str) -> bool:
        """
        Restore a file from its most recent backup.
        Use when file corruption is detected.
        """
        try:
            file_stem = Path(path).stem
            backup_dir = Path("logs/backups")
            
            backups = sorted(
                backup_dir.glob(f"{file_stem}_*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            if not backups:
                print(f"❌ [DataRegistry] No backups found for {path}")
                return False
            
            latest_backup = backups[0]
            
            # Verify backup is valid JSON
            with open(latest_backup, 'r') as f:
                data = json.load(f)
            
            # Restore
            import shutil
            shutil.copy2(latest_backup, path)
            print(f"✅ [DataRegistry] Restored {path} from {latest_backup}")
            return True
            
        except Exception as e:
            print(f"❌ [DataRegistry] Restore failed: {e}")
            return False
    
    @classmethod
    def check_json_integrity(cls, path: str) -> Dict[str, Any]:
        """
        Check if a JSON file is valid and not corrupted.
        Returns integrity report.
        """
        report = {
            "path": path,
            "exists": False,
            "valid_json": False,
            "size_bytes": 0,
            "record_count": None,
            "error": None
        }
        
        if not os.path.exists(path):
            report["error"] = "File does not exist"
            return report
        
        report["exists"] = True
        report["size_bytes"] = os.path.getsize(path)
        
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            report["valid_json"] = True
            
            # Count records if it's a known structure
            if isinstance(data, dict):
                if "trades" in data:
                    report["record_count"] = len(data.get("trades", []))
                elif "open_positions" in data:
                    report["record_count"] = len(data.get("open_positions", []))
            elif isinstance(data, list):
                report["record_count"] = len(data)
                
        except json.JSONDecodeError as e:
            report["error"] = f"JSON parse error: {e}"
        except Exception as e:
            report["error"] = f"Read error: {e}"
        
        return report


# Shorthand alias for common usage
DR = DataRegistry


# Self-test when run directly
if __name__ == "__main__":
    print("=" * 60)
    print("DATA REGISTRY - PATH INVENTORY")
    print("=" * 60)
    
    DR.ensure_dirs()
    
    print("\n📁 CANONICAL PATHS:")
    for attr in sorted(dir(DR)):
        if not attr.startswith('_') and attr.isupper():
            val = getattr(DR, attr)
            if isinstance(val, str):
                exists = "✓" if os.path.exists(val) else "✗"
                print(f"  {exists} {attr}: {val}")
    
    print("\n📦 LEGACY PATHS (to migrate):")
    all_legacy = DR._LEGACY_TRADES + DR._LEGACY_POSITIONS + DR._LEGACY_SIGNALS
    for lp in all_legacy:
        exists = "✓" if os.path.exists(lp) else "✗"
        print(f"  {exists} {lp}")
    
    print("\n📊 MIGRATION DRY RUN:")
    trade_stats = DR.migrate_legacy_trades(dry_run=True)
    for path, count in trade_stats.items():
        print(f"  {path}: {count} records")
    
    signal_stats = DR.migrate_legacy_signals(dry_run=True)
    for path, count in signal_stats.items():
        print(f"  {path}: {count} records")
