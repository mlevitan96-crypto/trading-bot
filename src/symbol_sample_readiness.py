"""
Symbol Sample Readiness - Ensures sufficient sample size before allocation decisions.

Requires minimum:
- N trades per symbol (default: 30)
- M days of data per symbol (default: 7)
Before allowing:
- Capital reallocation
- Symbol suppression/boosting
- Size multiplier adjustments

Tracks readiness state per symbol and provides metrics for dashboard.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from src.infrastructure.path_registry import PathRegistry


# Minimum sample requirements
MIN_TRADES_PER_SYMBOL = 30
MIN_DAYS_OF_DATA = 7

# State file
SAMPLE_READINESS_FILE = PathRegistry.FEATURE_STORE_DIR / "symbol_sample_readiness.json"


class SymbolSampleReadiness:
    """
    Tracks sample size readiness for each symbol.
    """
    
    def __init__(self):
        self.state_file = SAMPLE_READINESS_FILE
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
    def load_state(self) -> Dict[str, Any]:
        """Load sample readiness state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [SAMPLE-READINESS] Failed to load state: {e}")
                return {}
        return {
            "symbols": {},
            "last_updated": None,
            "config": {
                "min_trades": MIN_TRADES_PER_SYMBOL,
                "min_days": MIN_DAYS_OF_DATA
            }
        }
    
    def save_state(self, state: Dict[str, Any]):
        """Save sample readiness state."""
        state["last_updated"] = datetime.utcnow().isoformat() + "Z"
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️ [SAMPLE-READINESS] Failed to save state: {e}")
    
    def calculate_readiness(self, symbol: str, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate sample readiness for a symbol based on trades.
        
        Args:
            symbol: Trading symbol
            trades: List of trade records (from executed_trades.jsonl or positions_futures.json)
        
        Returns:
            Readiness dict with counts, dates, and readiness flags
        """
        if not trades:
            return {
                "symbol": symbol,
                "trade_count": 0,
                "days_of_data": 0,
                "first_trade_date": None,
                "last_trade_date": None,
                "meets_trade_threshold": False,
                "meets_days_threshold": False,
                "is_ready": False
            }
        
        # Filter to symbol's trades
        symbol_trades = [t for t in trades if t.get("symbol") == symbol]
        
        if not symbol_trades:
            return {
                "symbol": symbol,
                "trade_count": 0,
                "days_of_data": 0,
                "first_trade_date": None,
                "last_trade_date": None,
                "meets_trade_threshold": False,
                "meets_days_threshold": False,
                "is_ready": False
            }
        
        trade_count = len(symbol_trades)
        
        # Extract timestamps
        timestamps = []
        for trade in symbol_trades:
            ts = trade.get("ts") or trade.get("timestamp") or trade.get("entry_time")
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        dt = datetime.fromtimestamp(int(ts))
                    timestamps.append(dt)
                except:
                    pass
        
        if not timestamps:
            return {
                "symbol": symbol,
                "trade_count": trade_count,
                "days_of_data": 0,
                "first_trade_date": None,
                "last_trade_date": None,
                "meets_trade_threshold": trade_count >= MIN_TRADES_PER_SYMBOL,
                "meets_days_threshold": False,
                "is_ready": False
            }
        
        # Calculate days of data
        first_date = min(timestamps)
        last_date = max(timestamps)
        days_of_data = (last_date - first_date).days + 1  # +1 to include both start and end days
        
        meets_trade_threshold = trade_count >= MIN_TRADES_PER_SYMBOL
        meets_days_threshold = days_of_data >= MIN_DAYS_OF_DATA
        is_ready = meets_trade_threshold and meets_days_threshold
        
        return {
            "symbol": symbol,
            "trade_count": trade_count,
            "days_of_data": days_of_data,
            "first_trade_date": first_date.isoformat() + "Z",
            "last_trade_date": last_date.isoformat() + "Z",
            "meets_trade_threshold": meets_trade_threshold,
            "meets_days_threshold": meets_days_threshold,
            "is_ready": is_ready,
            "trades_needed": max(0, MIN_TRADES_PER_SYMBOL - trade_count),
            "days_needed": max(0, MIN_DAYS_OF_DATA - days_of_data)
        }
    
    def update_readiness(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Update readiness for all symbols based on trades.
        
        Args:
            trades: List of all trade records
        
        Returns:
            Updated state with per-symbol readiness
        """
        state = self.load_state()
        
        # Get unique symbols from trades
        symbols = set()
        for trade in trades:
            sym = trade.get("symbol")
            if sym:
                symbols.add(sym)
        
        # Calculate readiness for each symbol
        readiness_by_symbol = {}
        for symbol in symbols:
            readiness = self.calculate_readiness(symbol, trades)
            readiness_by_symbol[symbol] = readiness
        
        # Update state
        state["symbols"] = readiness_by_symbol
        state["config"] = {
            "min_trades": MIN_TRADES_PER_SYMBOL,
            "min_days": MIN_DAYS_OF_DATA
        }
        
        self.save_state(state)
        
        return state
    
    def is_symbol_ready(self, symbol: str) -> bool:
        """
        Check if a symbol meets minimum sample requirements.
        
        Args:
            symbol: Trading symbol
        
        Returns:
            True if symbol is ready for allocation decisions
        """
        state = self.load_state()
        symbol_data = state.get("symbols", {}).get(symbol, {})
        return symbol_data.get("is_ready", False)
    
    def get_readiness_stats(self) -> Dict[str, Any]:
        """
        Get overall readiness statistics.
        
        Returns:
            Stats dict with counts, percentages, and lists
        """
        state = self.load_state()
        symbols = state.get("symbols", {})
        
        total_symbols = len(symbols)
        ready_symbols = [s for s, d in symbols.items() if d.get("is_ready", False)]
        not_ready_symbols = [s for s, d in symbols.items() if not d.get("is_ready", False)]
        
        # Categorize by what's missing
        missing_trades = [s for s, d in symbols.items() if not d.get("meets_trade_threshold", False)]
        missing_days = [s for s, d in symbols.items() if not d.get("meets_days_threshold", False)]
        
        return {
            "total_symbols": total_symbols,
            "ready_count": len(ready_symbols),
            "not_ready_count": len(not_ready_symbols),
            "ready_symbols": ready_symbols,
            "not_ready_symbols": not_ready_symbols,
            "missing_trades": missing_trades,
            "missing_days": missing_days,
            "readiness_pct": (len(ready_symbols) / total_symbols * 100.0) if total_symbols > 0 else 0.0,
            "config": state.get("config", {})
        }
    
    def filter_allocation_proposals(self, proposals: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filter allocation proposals by sample readiness.
        
        Args:
            proposals: List of allocation proposals
        
        Returns:
            (approved_proposals, blocked_proposals)
        """
        approved = []
        blocked = []
        
        for proposal in proposals:
            symbol = proposal.get("symbol")
            if not symbol:
                approved.append(proposal)  # No symbol, can't check
                continue
            
            if self.is_symbol_ready(symbol):
                approved.append(proposal)
            else:
                state = self.load_state()
                symbol_data = state.get("symbols", {}).get(symbol, {})
                
                blocked_proposal = proposal.copy()
                blocked_proposal["block_reason"] = "insufficient_samples"
                blocked_proposal["sample_info"] = {
                    "trade_count": symbol_data.get("trade_count", 0),
                    "days_of_data": symbol_data.get("days_of_data", 0),
                    "trades_needed": symbol_data.get("trades_needed", MIN_TRADES_PER_SYMBOL),
                    "days_needed": symbol_data.get("days_needed", MIN_DAYS_OF_DATA)
                }
                blocked.append(blocked_proposal)
        
        return approved, blocked


def get_symbol_readiness() -> Dict[str, Any]:
    """
    Get current symbol readiness state.
    
    Main entry point for checking if symbols are ready for allocation decisions.
    """
    readiness = SymbolSampleReadiness()
    
    # Update from recent trades
    try:
        from src.position_manager import load_futures_positions
        positions_data = load_futures_positions()
        closed_positions = positions_data.get("closed_positions", [])
        
        # Convert to trade format expected by calculate_readiness
        trades = []
        for pos in closed_positions:
            trades.append({
                "symbol": pos.get("symbol"),
                "ts": pos.get("closed_at") or pos.get("entry_time"),
                "timestamp": pos.get("closed_at") or pos.get("entry_time"),
                "entry_time": pos.get("entry_time")
            })
        
        readiness.update_readiness(trades)
    except Exception as e:
        print(f"⚠️ [SAMPLE-READINESS] Failed to update from positions: {e}")
    
    return readiness.get_readiness_stats()


def is_symbol_ready_for_allocation(symbol: str) -> bool:
    """
    Check if symbol meets minimum sample requirements for allocation decisions.
    
    Args:
        symbol: Trading symbol
    
    Returns:
        True if symbol is ready
    """
    readiness = SymbolSampleReadiness()
    return readiness.is_symbol_ready(symbol)


if __name__ == "__main__":
    # Test sample readiness
    readiness = SymbolSampleReadiness()
    stats = get_symbol_readiness()
    
    print("\n📊 Symbol Sample Readiness")
    print("=" * 70)
    print(f"✅ Ready: {stats['ready_count']}/{stats['total_symbols']}")
    print(f"❌ Not Ready: {stats['not_ready_count']}")
    print(f"📈 Readiness: {stats['readiness_pct']:.1f}%")
    print("\n🔴 Not Ready Symbols:")
    for sym in stats['not_ready_symbols']:
        symbol_data = readiness.load_state().get("symbols", {}).get(sym, {})
        print(f"   • {sym}: {symbol_data.get('trade_count', 0)} trades, {symbol_data.get('days_of_data', 0)} days")
