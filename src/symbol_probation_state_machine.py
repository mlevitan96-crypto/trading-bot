"""
Symbol Probation State Machine - Component 6
=============================================
Tracks symbol performance and places symbols on probation when they underperform.
Prevents new signals for symbols on probation until they recover.

States:
- ACTIVE: Symbol is trading normally
- PROBATION: Symbol underperforming, signals blocked
- RECOVERING: Symbol showing improvement, monitoring
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from collections import defaultdict

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    DR = None

FEATURE_STORE = Path("feature_store")
LOGS = Path("logs")
PROBATION_STATE_FILE = FEATURE_STORE / "symbol_probation_state.json"
PROBATION_LOG = LOGS / "symbol_probation.jsonl"


class ProbationState(Enum):
    """Symbol probation states"""
    ACTIVE = "active"
    PROBATION = "probation"
    RECOVERING = "recovering"


class SymbolProbationStateMachine:
    """
    Manages symbol-level probation based on performance metrics.
    """
    
    def __init__(self):
        self.state_file = PROBATION_STATE_FILE
        self.log_file = PROBATION_LOG
        
        # Ensure directories exist
        FEATURE_STORE.mkdir(parents=True, exist_ok=True)
        LOGS.mkdir(parents=True, exist_ok=True)
        
        # Load state
        self.symbol_states: Dict[str, Dict] = {}
        self.load_state()
        
        # Configuration
        self.probation_thresholds = {
            "min_trades": 5,  # Minimum trades before probation consideration
            "max_loss_pct": -2.0,  # Max cumulative loss % to trigger probation
            "max_loss_count": 3,  # Max consecutive losses to trigger probation
            "min_win_rate": 0.30,  # Min win rate (30%) to avoid probation
            "recovery_period_hours": 24,  # Hours to wait before recovery check
            "recovery_min_trades": 3,  # Min trades in recovery period
            "recovery_min_win_rate": 0.50,  # Min win rate to exit probation
        }
    
    def load_state(self):
        """Load symbol probation state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.symbol_states = data.get("symbol_states", {})
            except Exception as e:
                print(f"⚠️ [PROBATION] Error loading state: {e}")
                self.symbol_states = {}
        else:
            self.symbol_states = {}
    
    def save_state(self):
        """Save symbol probation state to file"""
        try:
            data = {
                "updated_at": datetime.utcnow().isoformat() + 'Z',
                "symbol_states": self.symbol_states
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"⚠️ [PROBATION] Error saving state: {e}")
    
    def log_event(self, symbol: str, event_type: str, details: Dict):
        """Log probation event"""
        try:
            event = {
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "ts": time.time(),
                "symbol": symbol,
                "event_type": event_type,
                **details
            }
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            print(f"⚠️ [PROBATION] Error logging event: {e}")
    
    def get_symbol_state(self, symbol: str) -> ProbationState:
        """Get current probation state for a symbol"""
        state_data = self.symbol_states.get(symbol, {})
        state_str = state_data.get("state", ProbationState.ACTIVE.value)
        
        try:
            return ProbationState(state_str)
        except ValueError:
            return ProbationState.ACTIVE
    
    def should_block_symbol(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if symbol should be blocked (on probation).
        
        Returns:
            (should_block: bool, reason: str)
        """
        state = self.get_symbol_state(symbol)
        
        if state == ProbationState.PROBATION:
            state_data = self.symbol_states.get(symbol, {})
            entered_at = state_data.get("entered_at", "")
            reason = state_data.get("reason", "underperformance")
            return True, f"symbol_on_probation_{reason}"
        
        return False, "active"
    
    def analyze_symbol_performance(self, symbol: str, lookback_hours: int = 48) -> Dict:
        """
        Analyze symbol performance over lookback period.
        
        Returns:
            Dict with performance metrics
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=lookback_hours)
        cutoff_ts = cutoff_time.timestamp()
        
        # Load closed positions
        try:
            positions_path = Path("logs/positions_futures.json")
            if DR:
                positions_path = Path(DR.get_path("positions_futures"))
            
            if not positions_path.exists():
                return {"error": "no_data"}
            
            with open(positions_path, 'r') as f:
                positions = json.load(f)
            
            closed_positions = positions.get("closed_positions", [])
            
            # Filter to symbol and time window
            symbol_trades = []
            for pos in closed_positions:
                if pos.get("symbol", "").upper() != symbol.upper():
                    continue
                
                # Parse closed timestamp
                closed_at = pos.get("closed_at") or pos.get("opened_at")
                if not closed_at:
                    continue
                
                try:
                    if isinstance(closed_at, str):
                        trade_ts = datetime.fromisoformat(closed_at.replace("Z", "+00:00")).timestamp()
                    elif isinstance(closed_at, (int, float)):
                        trade_ts = float(closed_at)
                    else:
                        continue
                    
                    if trade_ts >= cutoff_ts:
                        symbol_trades.append(pos)
                except (ValueError, TypeError):
                    continue
            
            if len(symbol_trades) < self.probation_thresholds["min_trades"]:
                return {"error": "insufficient_trades", "count": len(symbol_trades)}
            
            # Calculate metrics
            total_pnl = 0.0
            total_trades = len(symbol_trades)
            winning_trades = 0
            losing_trades = 0
            consecutive_losses = 0
            max_consecutive_losses = 0
            
            for pos in symbol_trades:
                pnl = pos.get("pnl", 0.0) or pos.get("net_pnl", 0.0) or pos.get("profit_usd", 0.0) or 0.0
                total_pnl += pnl
                
                if pnl > 0:
                    winning_trades += 1
                    consecutive_losses = 0
                elif pnl < 0:
                    losing_trades += 1
                    consecutive_losses += 1
                    max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            
            win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
            
            # Calculate P&L percentage (approximate, using entry price)
            total_entry_value = 0.0
            for pos in symbol_trades:
                entry_price = pos.get("entry_price", 0)
                size = pos.get("size", 0)
                if entry_price > 0 and size > 0:
                    total_entry_value += size
            
            pnl_pct = (total_pnl / total_entry_value * 100) if total_entry_value > 0 else 0.0
            
            return {
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "pnl_pct": pnl_pct,
                "max_consecutive_losses": max_consecutive_losses,
                "lookback_hours": lookback_hours
            }
        
        except Exception as e:
            print(f"⚠️ [PROBATION] Error analyzing {symbol}: {e}")
            return {"error": str(e)}
    
    def evaluate_symbol(self, symbol: str) -> Dict:
        """
        Evaluate symbol and update probation state if needed.
        
        Returns:
            Dict with evaluation result
        """
        performance = self.analyze_symbol_performance(symbol)
        
        if "error" in performance:
            return {"state": "unchanged", "reason": performance.get("error")}
        
        current_state = self.get_symbol_state(symbol)
        thresholds = self.probation_thresholds
        
        # Check if should enter probation
        if current_state == ProbationState.ACTIVE:
            should_probate = False
            reason = None
            
            # Check cumulative loss
            if performance["pnl_pct"] < thresholds["max_loss_pct"]:
                should_probate = True
                reason = f"cumulative_loss_{performance['pnl_pct']:.2f}pct"
            
            # Check consecutive losses
            elif performance["max_consecutive_losses"] >= thresholds["max_loss_count"]:
                should_probate = True
                reason = f"consecutive_losses_{performance['max_consecutive_losses']}"
            
            # Check win rate
            elif performance["win_rate"] < thresholds["min_win_rate"] and performance["total_trades"] >= thresholds["min_trades"]:
                should_probate = True
                reason = f"low_win_rate_{performance['win_rate']:.2%}"
            
            if should_probate:
                self._enter_probation(symbol, reason, performance)
                return {"state": "entered_probation", "reason": reason}
        
        # Check if should exit probation (recovery)
        elif current_state == ProbationState.PROBATION:
            state_data = self.symbol_states.get(symbol, {})
            entered_at_str = state_data.get("entered_at", "")
            
            if entered_at_str:
                try:
                    entered_at = datetime.fromisoformat(entered_at_str.replace("Z", "+00:00"))
                    hours_since_probation = (datetime.utcnow() - entered_at).total_seconds() / 3600
                    
                    if hours_since_probation >= thresholds["recovery_period_hours"]:
                        # Analyze recovery period performance
                        recovery_performance = self.analyze_symbol_performance(symbol, lookback_hours=int(hours_since_probation))
                        
                        if "error" not in recovery_performance:
                            if (recovery_performance["total_trades"] >= thresholds["recovery_min_trades"] and
                                recovery_performance["win_rate"] >= thresholds["recovery_min_win_rate"]):
                                
                                self._exit_probation(symbol, "recovered", recovery_performance)
                                return {"state": "exited_probation", "reason": "recovered"}
                
                except (ValueError, TypeError):
                    pass
        
        return {"state": "unchanged"}
    
    def _enter_probation(self, symbol: str, reason: str, performance: Dict):
        """Place symbol on probation"""
        self.symbol_states[symbol] = {
            "state": ProbationState.PROBATION.value,
            "entered_at": datetime.utcnow().isoformat() + 'Z',
            "reason": reason,
            "performance_at_entry": performance
        }
        self.save_state()
        self.log_event(symbol, "entered_probation", {
            "reason": reason,
            "performance": performance
        })
        print(f"🚫 [PROBATION] {symbol} placed on probation: {reason}")
    
    def _exit_probation(self, symbol: str, reason: str, performance: Dict):
        """Remove symbol from probation"""
        self.symbol_states[symbol] = {
            "state": ProbationState.ACTIVE.value,
            "exited_at": datetime.utcnow().isoformat() + 'Z',
            "exit_reason": reason,
            "recovery_performance": performance
        }
        self.save_state()
        self.log_event(symbol, "exited_probation", {
            "reason": reason,
            "performance": performance
        })
        print(f"✅ [PROBATION] {symbol} removed from probation: {reason}")
    
    def evaluate_all_symbols(self):
        """Evaluate all symbols with recent trades"""
        # Get list of symbols from recent trades
        try:
            positions_path = Path("logs/positions_futures.json")
            if DR:
                positions_path = Path(DR.get_path("positions_futures"))
            
            if not positions_path.exists():
                return
            
            with open(positions_path, 'r') as f:
                positions = json.load(f)
            
            closed_positions = positions.get("closed_positions", [])
            
            # Get unique symbols from last 48 hours
            symbols = set()
            cutoff_time = datetime.utcnow() - timedelta(hours=48)
            cutoff_ts = cutoff_time.timestamp()
            
            for pos in closed_positions:
                closed_at = pos.get("closed_at") or pos.get("opened_at")
                if not closed_at:
                    continue
                
                try:
                    if isinstance(closed_at, str):
                        trade_ts = datetime.fromisoformat(closed_at.replace("Z", "+00:00")).timestamp()
                    elif isinstance(closed_at, (int, float)):
                        trade_ts = float(closed_at)
                    else:
                        continue
                    
                    if trade_ts >= cutoff_ts:
                        symbols.add(pos.get("symbol", "").upper())
                except (ValueError, TypeError):
                    continue
            
            # Evaluate each symbol
            for symbol in symbols:
                if symbol:
                    try:
                        self.evaluate_symbol(symbol)
                    except Exception as e:
                        print(f"⚠️ [PROBATION] Error evaluating {symbol}: {e}")
        
        except Exception as e:
            print(f"⚠️ [PROBATION] Error evaluating symbols: {e}")


# Singleton instance
_probation_machine_instance = None


def get_probation_machine() -> SymbolProbationStateMachine:
    """Get singleton instance"""
    global _probation_machine_instance
    if _probation_machine_instance is None:
        _probation_machine_instance = SymbolProbationStateMachine()
    return _probation_machine_instance


def check_symbol_probation(symbol: str) -> Tuple[bool, str]:
    """
    Check if symbol is on probation (should be blocked).
    
    Returns:
        (should_block: bool, reason: str)
    """
    machine = get_probation_machine()
    return machine.should_block_symbol(symbol)

