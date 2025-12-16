#!/usr/bin/env python3
"""
Shadow Execution Engine
======================
Runs parallel to real execution engine, simulating ALL signals (even blocked ones).

Enables:
- What-if analysis: "What if I disabled the Volatility Guard?"
- Guard effectiveness: "How much money did guards save/lose?"
- Unfiltered performance: Compare real vs shadow performance
"""

import json
import time
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict

from src.infrastructure.path_registry import PathRegistry
from src.signal_bus import get_signal_bus, SignalState
from src.events.schemas import ShadowTradeOutcomeEvent, MarketSnapshot, create_decision_event
from src.exchange_gateway import ExchangeGateway


class ShadowExecutionEngine:
    """
    Simulates trades for all signals, even those blocked by guards.
    
    Subscribes to SignalBus and:
    1. Captures ALL signals (approved and blocked)
    2. Simulates entry at market snapshot price
    3. Tracks exit using actual market prices
    4. Calculates hypothetical P&L
    5. Logs ShadowTradeOutcomeEvent
    """
    
    def __init__(self):
        self.signal_bus = get_signal_bus()
        self.exchange_gateway = ExchangeGateway()
        self.active_shadow_trades = {}  # signal_id -> shadow_trade_info
        self.outcomes_log_path = Path(PathRegistry.get_path("logs", "shadow_trade_outcomes.jsonl"))
        self._lock = threading.RLock()
        self._running = False
        self._thread = None
        
        # Ensure log file exists
        self.outcomes_log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def start(self):
        """Start shadow execution engine"""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("🔮 [SHADOW] Shadow execution engine started")
    
    def stop(self):
        """Stop shadow execution engine"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("🔮 [SHADOW] Shadow execution engine stopped")
    
    def _run_loop(self):
        """Main loop: process signals and track shadow trades"""
        while self._running:
            try:
                # Process new signals
                self._process_new_signals()
                
                # Update active shadow trades
                self._update_active_trades()
                
                # Check for exits
                self._check_exits()
                
                time.sleep(5)  # Check every 5 seconds
            except Exception as e:
                print(f"⚠️ [SHADOW] Error in shadow execution loop: {e}")
                time.sleep(10)
    
    def _process_new_signals(self):
        """Process new signals from bus"""
        # Get all signals in GENERATED or BLOCKED state
        generated = self.signal_bus.get_signals_by_state(SignalState.GENERATED)
        blocked = self.signal_bus.get_signals_by_state(SignalState.BLOCKED)
        
        for signal_id in generated + blocked:
            if signal_id in self.active_shadow_trades:
                continue  # Already tracking
            
            signal_data = self.signal_bus.get_signal(signal_id)
            if not signal_data:
                continue
            
            signal = signal_data.get("signal", {})
            symbol = signal.get("symbol")
            direction = signal.get("direction")
            
            if not symbol or not direction or direction == "HOLD":
                continue
            
            # Get market snapshot
            try:
                price = self.exchange_gateway.get_price(symbol, venue="futures")
                if not price or price <= 0:
                    continue
                
                # Create shadow trade
                shadow_trade_id = f"shadow_{signal_id}_{uuid.uuid4().hex[:8]}"
                
                with self._lock:
                    self.active_shadow_trades[signal_id] = {
                        "shadow_trade_id": shadow_trade_id,
                        "signal_id": signal_id,
                        "symbol": symbol,
                        "direction": direction,
                        "entry_price": price,
                        "entry_ts": time.time(),
                        "original_decision": "BLOCKED" if signal_id in blocked else "APPROVED",
                        "blocker_component": signal_data.get("last_reason")  # If blocked, why
                    }
                
                print(f"🔮 [SHADOW] Started tracking shadow trade: {symbol} {direction} @ ${price:.2f}")
            except Exception as e:
                print(f"⚠️ [SHADOW] Failed to start shadow trade for {signal_id}: {e}")
    
    def _update_active_trades(self):
        """Update active shadow trades with current prices"""
        with self._lock:
            for signal_id, trade_info in list(self.active_shadow_trades.items()):
                symbol = trade_info["symbol"]
                try:
                    current_price = self.exchange_gateway.get_price(symbol, venue="futures")
                    if current_price and current_price > 0:
                        trade_info["current_price"] = current_price
                        trade_info["last_update_ts"] = time.time()
                except Exception as e:
                    # Skip if price fetch fails
                    pass
    
    def _check_exits(self):
        """Check if shadow trades should exit"""
        now = time.time()
        exit_candidates = []
        
        with self._lock:
            for signal_id, trade_info in list(self.active_shadow_trades.items()):
                entry_ts = trade_info.get("entry_ts", 0)
                hold_time = now - entry_ts
                
                # Exit conditions:
                # 1. Max hold time (e.g., 4 hours)
                # 2. Profit target (e.g., +2%)
                # 3. Stop loss (e.g., -1.5%)
                # 4. Signal expired/cancelled
                
                current_price = trade_info.get("current_price")
                if not current_price:
                    continue
                
                entry_price = trade_info["entry_price"]
                direction = trade_info["direction"]
                
                if direction == "LONG":
                    pnl_pct = (current_price - entry_price) / entry_price
                else:  # SHORT
                    pnl_pct = (entry_price - current_price) / entry_price
                
                should_exit = False
                exit_reason = None
                
                # Max hold time (4 hours)
                if hold_time > 14400:  # 4 hours
                    should_exit = True
                    exit_reason = "max_hold_time"
                
                # Profit target (+2%)
                elif pnl_pct >= 0.02:
                    should_exit = True
                    exit_reason = "profit_target"
                
                # Stop loss (-1.5%)
                elif pnl_pct <= -0.015:
                    should_exit = True
                    exit_reason = "stop_loss"
                
                # Signal expired
                signal_data = self.signal_bus.get_signal(signal_id)
                if signal_data:
                    state = signal_data.get("state")
                    if state in ["expired", "cancelled"]:
                        should_exit = True
                        exit_reason = f"signal_{state}"
                
                if should_exit:
                    exit_candidates.append((signal_id, trade_info, current_price, pnl_pct, exit_reason))
        
        # Execute exits
        for signal_id, trade_info, exit_price, pnl_pct, exit_reason in exit_candidates:
            self._exit_shadow_trade(signal_id, trade_info, exit_price, pnl_pct, exit_reason)
    
    def _exit_shadow_trade(self, signal_id: str, trade_info: Dict, exit_price: float, 
                          pnl_pct: float, exit_reason: str):
        """Exit a shadow trade and log outcome"""
        entry_price = trade_info["entry_price"]
        entry_ts = trade_info["entry_ts"]
        hold_time = time.time() - entry_ts
        
        # Calculate P&L (assuming $1000 notional for simplicity)
        notional = 1000.0  # Can be made configurable
        pnl = pnl_pct * notional
        
        outcome = ShadowTradeOutcomeEvent(
            signal_id=signal_id,
            shadow_trade_id=trade_info["shadow_trade_id"],
            symbol=trade_info["symbol"],
            direction=trade_info["direction"],
            entry_price=entry_price,
            exit_price=exit_price,
            exit_timestamp=datetime.utcnow().isoformat() + 'Z',
            pnl=pnl,
            pnl_pct=pnl_pct,
            hold_time_seconds=hold_time,
            was_profitable=pnl_pct > 0,
            original_decision=trade_info.get("original_decision"),
            blocker_component=trade_info.get("blocker_component")
        )
        
        # Log outcome
        try:
            with open(self.outcomes_log_path, 'a') as f:
                f.write(json.dumps(outcome.to_dict()) + '\n')
        except Exception as e:
            print(f"⚠️ [SHADOW] Failed to log shadow outcome: {e}")
        
        # Remove from active trades
        with self._lock:
            self.active_shadow_trades.pop(signal_id, None)
        
        status = "✅" if pnl_pct > 0 else "❌"
        print(f"🔮 [SHADOW] {status} Exited shadow trade: {trade_info['symbol']} {trade_info['direction']} | "
              f"P&L: {pnl_pct*100:.2f}% | Reason: {exit_reason}")
    
    def get_shadow_performance(self, hours: int = 24) -> Dict[str, Any]:
        """Get shadow performance summary"""
        cutoff_ts = time.time() - (hours * 3600)
        
        outcomes = []
        if self.outcomes_log_path.exists():
            try:
                with open(self.outcomes_log_path, 'r') as f:
                    for line in f:
                        try:
                            outcome = json.loads(line.strip())
                            if outcome.get("ts", 0) >= cutoff_ts:
                                outcomes.append(outcome)
                        except:
                            continue
            except Exception as e:
                print(f"⚠️ [SHADOW] Error reading outcomes: {e}")
        
        if not outcomes:
            return {
                "total_trades": 0,
                "profitable": 0,
                "losing": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "avg_pnl_pct": 0.0
            }
        
        profitable = [o for o in outcomes if o.get("was_profitable", False)]
        losing = [o for o in outcomes if not o.get("was_profitable", False)]
        total_pnl = sum(o.get("pnl", 0) for o in outcomes)
        
        return {
            "total_trades": len(outcomes),
            "profitable": len(profitable),
            "losing": len(losing),
            "win_rate": len(profitable) / len(outcomes) if outcomes else 0.0,
            "total_pnl": total_pnl,
            "avg_pnl_pct": sum(o.get("pnl_pct", 0) for o in outcomes) / len(outcomes) if outcomes else 0.0,
            "by_decision": {
                "blocked": len([o for o in outcomes if o.get("original_decision") == "BLOCKED"]),
                "approved": len([o for o in outcomes if o.get("original_decision") == "APPROVED"])
            }
        }


# Global singleton
_shadow_engine_instance = None
_shadow_engine_lock = threading.Lock()


def get_shadow_engine() -> ShadowExecutionEngine:
    """Get global ShadowExecutionEngine instance"""
    global _shadow_engine_instance
    
    with _shadow_engine_lock:
        if _shadow_engine_instance is None:
            _shadow_engine_instance = ShadowExecutionEngine()
        return _shadow_engine_instance

