#!/usr/bin/env python3
"""
BOT-SCOPED DATA REGISTRY
========================
Extends DataRegistry to support multiple parallel trading bots (Alpha/Beta).
Each bot has isolated data directories while sharing read-only market data.

Usage:
    from src.bot_registry import BotRegistry
    
    # Get bot-specific registry
    alpha = BotRegistry("alpha")
    beta = BotRegistry("beta")
    
    # Access bot-scoped paths
    alpha.PORTFOLIO_MASTER  # -> logs/alpha/portfolio.json
    beta.PORTFOLIO_MASTER   # -> logs/beta/portfolio.json
    
    # Shared paths (read-only, same for both)
    alpha.ENRICHED_DECISIONS  # -> logs/enriched_decisions.jsonl (shared)
"""

import json
import os
import time
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime


class BotRegistry:
    """
    Bot-scoped data registry for parallel trading bots.
    
    Isolates:
    - Portfolio tracking (portfolio.json)
    - Position management (positions_futures.json)
    - Learning rules and feature stores
    - P&L snapshots and reports
    
    Shares (read-only):
    - Market data and signals
    - Enriched decisions (historical training data)
    - CoinGlass intelligence
    - Asset universe configuration
    """
    
    # Valid bot IDs
    VALID_BOTS = ["alpha", "beta"]
    
    def __init__(self, bot_id: str):
        if bot_id not in self.VALID_BOTS:
            raise ValueError(f"Invalid bot_id: {bot_id}. Must be one of {self.VALID_BOTS}")
        
        self.bot_id = bot_id
        self._init_paths()
        self.ensure_dirs()
    
    def _init_paths(self):
        """Initialize all bot-scoped paths."""
        bid = self.bot_id
        
        # =====================================================================
        # BOT-SCOPED PATHS (isolated per bot)
        # =====================================================================
        
        # Trading data
        self.PORTFOLIO_MASTER = f"logs/{bid}/portfolio.json"
        self.POSITIONS_FUTURES = f"logs/{bid}/positions_futures.json"
        self.PNL_SNAPSHOTS = f"logs/{bid}/pnl_snapshots.jsonl"
        self.WALLET_SNAPSHOTS = f"logs/{bid}/wallet_snapshots.jsonl"
        
        # Bot-specific signals and trades
        self.BOT_TRADES = f"logs/{bid}/trades.jsonl"
        self.BOT_SIGNALS = f"logs/{bid}/signals.jsonl"
        self.BOT_DECISIONS = f"logs/{bid}/decisions.jsonl"
        
        # Learning and feature stores
        self.LEARNED_RULES = f"feature_store/{bid}/learned_rules.json"
        self.DAILY_LEARNING_RULES = f"feature_store/{bid}/daily_learning_rules.json"
        self.PATTERN_DISCOVERIES = f"feature_store/{bid}/pattern_discoveries.json"
        self.COIN_PROFILES = f"feature_store/{bid}/coin_profiles.json"
        self.COIN_SELECTION = f"feature_store/{bid}/coin_selection_state.json"
        self.ADAPTIVE_WEIGHTS = f"feature_store/{bid}/adaptive_weights.json"
        self.OFFENSIVE_RULES = f"feature_store/{bid}/offensive_rules.json"
        
        # Bot configuration
        self.BOT_CONFIG = f"configs/{bid}_config.json"
        self.BOT_STATE = f"state/{bid}_state.json"
        
        # Reports
        self.REPORTS_DIR = f"reports/{bid}"
        self.NIGHTLY_DIGEST = f"logs/{bid}/nightly_digest.json"
        
        # =====================================================================
        # SHARED PATHS (read-only, same source for all bots)
        # =====================================================================
        
        # Historical training data (shared, read-only)
        self.ENRICHED_DECISIONS = "logs/enriched_decisions.jsonl"
        self.COUNTERFACTUAL_OUTCOMES = "logs/counterfactual_outcomes.jsonl"
        self.SIGNALS_UNIVERSE = "logs/signals.jsonl"
        
        # Market intelligence (shared, read-only)
        self.MARKET_INTEL_CACHE = "feature_store/market_intelligence.json"
        self.COINGLASS_DIR = "feature_store/coinglass"
        self.COINGLASS_CORRELATIONS = "feature_store/coinglass_correlations.json"
        
        # Configuration (shared, read-only)
        self.ASSET_UNIVERSE = "config/asset_universe.json"
        self.COMPOSITE_WEIGHTS = "configs/composite_weights.json"
        self.LIVE_CONFIG = "live_config.json"
        
        # Deep intelligence analysis (shared)
        self.DEEP_INTELLIGENCE = "feature_store/deep_intelligence_analysis.json"
        self.CONFIDENCE_TIERS = "logs/confidence_tier_backtest.json"
    
    def ensure_dirs(self):
        """Create all required bot-scoped directories."""
        bid = self.bot_id
        dirs = [
            f"logs/{bid}",
            f"logs/{bid}/backups",
            f"feature_store/{bid}",
            f"feature_store/{bid}/coinglass",
            f"configs",
            f"state",
            f"reports/{bid}",
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
    
    # =========================================================================
    # FILE I/O HELPERS
    # =========================================================================
    
    def read_json(self, path: str) -> Optional[Dict]:
        """Read a JSON file."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[{self.bot_id}] Error reading {path}: {e}")
            return None
    
    def write_json(self, path: str, data: Dict, indent: int = 2) -> bool:
        """Safely write a JSON file with atomic rename."""
        try:
            self.ensure_dirs()
            tmp_path = path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=indent, default=str)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp_path, path)
            return True
        except Exception as e:
            print(f"[{self.bot_id}] Error writing to {path}: {e}")
            return False
    
    def append_jsonl(self, path: str, record: Dict) -> bool:
        """Append a record to a JSONL file."""
        try:
            self.ensure_dirs()
            if 'ts' not in record and 'timestamp' not in record:
                record['ts'] = time.time()
                record['ts_iso'] = datetime.utcnow().isoformat() + "Z"
            record['bot_id'] = self.bot_id
            
            with open(path, 'a') as f:
                f.write(json.dumps(record, default=str) + '\n')
            return True
        except Exception as e:
            print(f"[{self.bot_id}] Error appending to {path}: {e}")
            return False
    
    def read_jsonl(self, path: str, last_n: Optional[int] = None) -> List[Dict]:
        """Read records from a JSONL file."""
        if not os.path.exists(path):
            return []
        try:
            records = []
            with open(path, 'r') as f:
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
            print(f"[{self.bot_id}] Error reading {path}: {e}")
            return []
    
    # =========================================================================
    # PORTFOLIO HELPERS
    # =========================================================================
    
    # Shared data paths (single source of truth for all bots)
    SHARED_PORTFOLIO = "logs/portfolio.json"
    SHARED_POSITIONS = "logs/positions_futures.json"
    
    def get_portfolio(self) -> Dict:
        """Get bot's portfolio data, filtering from shared source by bot_type."""
        # First try bot-specific file
        data = self.read_json(self.PORTFOLIO_MASTER)
        if data and data.get('trades'):
            return data
        
        # Fallback: Read from shared portfolio and filter by bot_type
        shared_data = self.read_json(self.SHARED_PORTFOLIO)
        if shared_data:
            all_trades = shared_data.get('trades', [])
            # Filter trades by bot_type (legacy trades without bot_type default to alpha)
            bot_trades = [t for t in all_trades if t.get('bot_type', 'alpha') == self.bot_id]
            
            # Calculate bot-specific metrics
            realized_pnl = sum(t.get('pnl', t.get('profit', t.get('realized_pnl', 0))) for t in bot_trades)
            
            return {
                "bot_id": self.bot_id,
                "starting_capital": 10000,
                "current_value": 10000 + realized_pnl,
                "realized_pnl": realized_pnl,
                "trades": bot_trades,
                "open_positions": [],
                "created_at": shared_data.get('created_at', datetime.utcnow().isoformat() + "Z")
            }
        
        return {
            "bot_id": self.bot_id,
            "starting_capital": 10000,
            "current_value": 10000,
            "realized_pnl": 0,
            "trades": [],
            "open_positions": [],
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
    
    def save_portfolio(self, data: Dict) -> bool:
        """Save bot's portfolio data."""
        data['bot_id'] = self.bot_id
        data['updated_at'] = datetime.utcnow().isoformat() + "Z"
        return self.write_json(self.PORTFOLIO_MASTER, data)
    
    def log_trade(self, trade: Dict) -> bool:
        """Log a trade to bot's portfolio."""
        trade['bot_id'] = self.bot_id
        trade['logged_at'] = datetime.utcnow().isoformat() + "Z"
        
        portfolio = self.get_portfolio()
        if 'trades' not in portfolio:
            portfolio['trades'] = []
        portfolio['trades'].append(trade)
        
        # Update realized P&L
        pnl = trade.get('pnl', 0)
        portfolio['realized_pnl'] = portfolio.get('realized_pnl', 0) + pnl
        portfolio['current_value'] = portfolio.get('current_value', 10000) + pnl
        
        return self.save_portfolio(portfolio)
    
    def record_trade(self, trade: Dict) -> bool:
        """Record a trade (alias for log_trade). Used by dual bot supervisor."""
        return self.log_trade(trade)
    
    def get_trades(self, last_n: Optional[int] = None, hours: Optional[float] = None) -> List[Dict]:
        """Get bot's trades from master registry (closed_positions), filtered by bot_type."""
        # PRIMARY: Read from shared positions file closed_positions (master source of truth)
        data = self.read_json(self.SHARED_POSITIONS)
        if data:
            all_closed = data.get('closed_positions', [])
            # Filter by bot_type (legacy without bot_type defaults to alpha)
            trades = [p for p in all_closed if p.get('bot_type', 'alpha') == self.bot_id]
        else:
            # Fallback to portfolio
            portfolio = self.get_portfolio()
            trades = portfolio.get('trades', [])
        
        if hours:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            cutoff_ts = cutoff.timestamp()
            filtered = []
            for t in trades:
                ts_str = t.get('timestamp') or t.get('close_time') or t.get('logged_at')
                if ts_str:
                    try:
                        if isinstance(ts_str, (int, float)):
                            trade_ts = ts_str
                        else:
                            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                            trade_ts = dt.timestamp()
                        if trade_ts >= cutoff_ts:
                            filtered.append(t)
                    except:
                        filtered.append(t)
            trades = filtered
        
        if last_n and len(trades) > last_n:
            trades = trades[-last_n:]
        
        return trades
    
    # =========================================================================
    # POSITION HELPERS
    # =========================================================================
    
    def get_open_positions(self) -> List[Dict]:
        """Get bot's open positions from shared file, filtered by bot_type."""
        # Read from shared positions file
        data = self.read_json(self.SHARED_POSITIONS)
        if data is None:
            return []
        all_positions = data.get('open_positions', [])
        # Filter by bot_type (legacy positions without bot_type default to alpha)
        return [p for p in all_positions if p.get('bot_type', 'alpha') == self.bot_id]
    
    def get_closed_positions(self, hours: int = 168) -> List[Dict]:
        """Get bot's closed positions from shared file, filtered by bot_type."""
        # Read from shared positions file
        data = self.read_json(self.SHARED_POSITIONS)
        if data is None:
            return []
        all_closed = data.get('closed_positions', [])
        # Filter by bot_type (legacy positions without bot_type default to alpha)
        closed = [p for p in all_closed if p.get('bot_type', 'alpha') == self.bot_id]
        
        if hours and closed:
            from datetime import timedelta
            cutoff_ts = (datetime.utcnow() - timedelta(hours=hours)).timestamp()
            filtered = []
            for p in closed:
                ts_str = p.get('closed_at') or p.get('timestamp')
                if ts_str:
                    try:
                        if isinstance(ts_str, (int, float)):
                            pos_ts = ts_str
                        else:
                            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                            pos_ts = dt.timestamp()
                        if pos_ts >= cutoff_ts:
                            filtered.append(p)
                    except:
                        filtered.append(p)
            return filtered
        return closed
    
    def save_positions(self, data: Dict) -> bool:
        """Save bot's positions."""
        data['bot_id'] = self.bot_id
        data['updated_at'] = datetime.utcnow().isoformat() + "Z"
        return self.write_json(self.POSITIONS_FUTURES, data)
    
    # =========================================================================
    # LEARNING HELPERS
    # =========================================================================
    
    def get_learned_rules(self) -> Dict:
        """Get bot's learned rules."""
        data = self.read_json(self.LEARNED_RULES)
        return data or {"rules": [], "updated_at": None}
    
    def save_learned_rules(self, data: Dict) -> bool:
        """Save bot's learned rules."""
        data['bot_id'] = self.bot_id
        data['updated_at'] = datetime.utcnow().isoformat() + "Z"
        return self.write_json(self.LEARNED_RULES, data)
    
    def get_daily_rules(self) -> Dict:
        """Get bot's daily learning rules."""
        data = self.read_json(self.DAILY_LEARNING_RULES)
        return data or {"rules": [], "updated_at": None}
    
    def save_daily_rules(self, data: Dict) -> bool:
        """Save bot's daily learning rules."""
        data['bot_id'] = self.bot_id
        data['updated_at'] = datetime.utcnow().isoformat() + "Z"
        return self.write_json(self.DAILY_LEARNING_RULES, data)
    
    # =========================================================================
    # PERFORMANCE METRICS
    # =========================================================================
    
    def get_performance_summary(self, since_ts: Optional[float] = None) -> Dict:
        """
        Get bot's performance summary from master registry.
        
        Args:
            since_ts: Optional timestamp to filter trades (only include trades after this time)
        """
        data = self.read_json(self.SHARED_POSITIONS)
        
        def get_trade_pnl(t):
            """Get P&L from trade, checking multiple possible field names."""
            return t.get('net_pnl', t.get('pnl', t.get('profit', t.get('realized_pnl', 0))))
        
        def get_trade_ts(t):
            """Get timestamp from trade, checking multiple possible field names."""
            ts = t.get('close_ts', t.get('exit_ts', t.get('closed_at', t.get('timestamp', 0))))
            if isinstance(ts, str):
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    return dt.timestamp()
                except:
                    return 0
            return ts or 0
        
        if data:
            all_closed = data.get('closed_positions', [])
            all_open = data.get('open_positions', [])
            closed_trades = [p for p in all_closed if p.get('bot_type', 'alpha') == self.bot_id]
            open_positions = [p for p in all_open if p.get('bot_type', 'alpha') == self.bot_id]
            
            if since_ts:
                closed_trades = [t for t in closed_trades if get_trade_ts(t) >= since_ts]
                open_positions = [t for t in open_positions if get_trade_ts(t) >= since_ts]
        else:
            portfolio = self.get_portfolio()
            trades = portfolio.get('trades', [])
            closed_trades = [t for t in trades if get_trade_pnl(t) != 0 or t.get('exit_price', 0) > 0]
            open_positions = [t for t in trades if t.get('status') == 'open']
            
            if since_ts:
                closed_trades = [t for t in closed_trades if get_trade_ts(t) >= since_ts]
                open_positions = [t for t in open_positions if get_trade_ts(t) >= since_ts]
        
        starting = 10000
        if not closed_trades and not open_positions:
            return {
                "bot_id": self.bot_id,
                "total_trades": 0,
                "win_rate": 0,
                "realized_pnl": 0,
                "current_value": starting,
                "drawdown": 0,
                "since_ts": since_ts
            }
        
        wins = sum(1 for t in closed_trades if get_trade_pnl(t) > 0)
        total_closed = len(closed_trades)
        realized_pnl = sum(get_trade_pnl(t) for t in closed_trades)
        
        current = starting + realized_pnl
        drawdown = min(0, current - starting) / starting * 100 if starting > 0 else 0
        
        return {
            "bot_id": self.bot_id,
            "total_trades": total_closed + len(open_positions),
            "closed_trades": total_closed,
            "open_trades": len(open_positions),
            "win_rate": (wins / total_closed * 100) if total_closed > 0 else 0,
            "wins": wins,
            "losses": total_closed - wins,
            "realized_pnl": realized_pnl,
            "starting_capital": starting,
            "current_value": current,
            "drawdown_pct": drawdown,
            "avg_pnl_per_trade": realized_pnl / total_closed if total_closed > 0 else 0,
            "since_ts": since_ts
        }
    
    def log_pnl_snapshot(self) -> bool:
        """Log current P&L snapshot."""
        summary = self.get_performance_summary()
        summary['snapshot_time'] = datetime.utcnow().isoformat() + "Z"
        return self.append_jsonl(self.PNL_SNAPSHOTS, summary)
    
    # =========================================================================
    # BOT STATE
    # =========================================================================
    
    def get_state(self) -> Dict:
        """Get bot's runtime state."""
        data = self.read_json(self.BOT_STATE)
        return data or {
            "bot_id": self.bot_id,
            "status": "initialized",
            "last_cycle": None,
            "cycles_run": 0
        }
    
    def save_state(self, data: Dict) -> bool:
        """Save bot's runtime state."""
        data['bot_id'] = self.bot_id
        data['updated_at'] = datetime.utcnow().isoformat() + "Z"
        return self.write_json(self.BOT_STATE, data)


# =============================================================================
# BOT COMPARISON UTILITIES
# =============================================================================

def get_tracking_config() -> Dict:
    """Load tracking reset configuration."""
    tracking_file = "configs/tracking_reset.json"
    if os.path.exists(tracking_file):
        try:
            with open(tracking_file) as f:
                return json.load(f)
        except:
            pass
    return {"tracking_start_ts": None, "starting_capital": 10000}


def compare_bots(fresh_only: bool = False) -> Dict:
    """
    Compare performance of Alpha vs Beta bots.
    
    Args:
        fresh_only: If True, only include trades after tracking_start_ts from config
    """
    alpha = BotRegistry("alpha")
    beta = BotRegistry("beta")
    
    tracking_config = get_tracking_config()
    since_ts = tracking_config.get('tracking_start_ts') if fresh_only else None
    tracking_start_iso = tracking_config.get('tracking_start_iso', 'N/A') if fresh_only else 'All Time'
    
    alpha_perf = alpha.get_performance_summary(since_ts=since_ts)
    beta_perf = beta.get_performance_summary(since_ts=since_ts)
    
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "tracking_mode": "fresh" if fresh_only else "all_time",
        "tracking_start": tracking_start_iso,
        "alpha": alpha_perf,
        "beta": beta_perf,
        "comparison": {
            "pnl_delta": beta_perf.get('realized_pnl', 0) - alpha_perf.get('realized_pnl', 0),
            "win_rate_delta": beta_perf.get('win_rate', 0) - alpha_perf.get('win_rate', 0),
            "trade_count_delta": beta_perf.get('total_trades', 0) - alpha_perf.get('total_trades', 0),
            "leader": "beta" if beta_perf.get('realized_pnl', 0) > alpha_perf.get('realized_pnl', 0) else "alpha"
        }
    }


def get_all_bot_registries() -> Dict[str, BotRegistry]:
    """Get registry instances for all bots."""
    return {
        "alpha": BotRegistry("alpha"),
        "beta": BotRegistry("beta")
    }


if __name__ == "__main__":
    print("=" * 60)
    print("BOT REGISTRY - Dual Bot Setup")
    print("=" * 60)
    
    # Initialize both bots
    alpha = BotRegistry("alpha")
    beta = BotRegistry("beta")
    
    print(f"\n[Alpha] Portfolio: {alpha.PORTFOLIO_MASTER}")
    print(f"[Alpha] Positions: {alpha.POSITIONS_FUTURES}")
    print(f"[Alpha] Learning:  {alpha.LEARNED_RULES}")
    
    print(f"\n[Beta] Portfolio:  {beta.PORTFOLIO_MASTER}")
    print(f"[Beta] Positions:  {beta.POSITIONS_FUTURES}")
    print(f"[Beta] Learning:   {beta.LEARNED_RULES}")
    
    print(f"\n[Shared] Enriched Decisions: {alpha.ENRICHED_DECISIONS}")
    print(f"[Shared] Asset Universe:     {alpha.ASSET_UNIVERSE}")
    
    # Compare performance
    comparison = compare_bots()
    print(f"\n{comparison}")
