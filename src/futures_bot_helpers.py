# File: src/futures_bot_helpers.py
# Purpose: Helper functions for futures margin monitoring, protective gating, and emergency actions

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

LOGS = Path("logs")
CONFIGS = Path("configs")

# Protective mode thresholds (aligned with futures_policies.json)
DEFAULT_POLICY = {
    "alert_buffer_pct": 12.0,
    "block_buffer_pct": 8.0,
    "auto_reduce_pct": 6.0,
    "min_buffer_pct": 10.0,
    "cooldown_seconds": 120
}

# Bot protective state
class FuturesProtectiveState:
    """Tracks futures protective mode and cooldown timers."""
    
    def __init__(self):
        self.mode = "OFF"  # OFF | ALERT | BLOCK | REDUCE
        self.last_auto_action: Dict[str, float] = {}  # symbol -> timestamp
        self.execution_log: List[Dict[str, Any]] = []
    
    def log_action(self, action_type: str, details: Dict[str, Any]):
        """Log protective action for audit trail."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": action_type,
            **details
        }
        self.execution_log.append(entry)
        self._persist_log()
    
    def _persist_log(self):
        """Save execution log to disk."""
        log_file = LOGS / "futures_protective_actions.json"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "w") as f:
                json.dump({"log": self.execution_log[-100:]}, f, indent=2)  # Keep last 100
        except Exception as e:
            print(f"⚠️ Failed to save futures protective log: {e}")
    
    def should_auto_act(self, symbol: str, cooldown_seconds: int = 120) -> bool:
        """Check if enough time has passed since last auto action."""
        now = datetime.utcnow().timestamp()
        last = self.last_auto_action.get(symbol, 0)
        return (now - last) >= cooldown_seconds
    
    def record_auto_action(self, symbol: str):
        """Record that auto action was taken."""
        self.last_auto_action[symbol] = datetime.utcnow().timestamp()


def load_futures_policy() -> Dict[str, Any]:
    """Load futures policy config or return defaults."""
    policy_file = CONFIGS / "futures_policies.json"
    try:
        if policy_file.exists():
            with open(policy_file, "r") as f:
                data = json.load(f)
                return {
                    "alert_buffer_pct": data.get("alert_buffer_pct", DEFAULT_POLICY["alert_buffer_pct"]),
                    "block_buffer_pct": 8.0,  # Fixed: BLOCK at <8%, not min_buffer_pct
                    "auto_reduce_pct": data.get("emergency_delever_buffer", DEFAULT_POLICY["auto_reduce_pct"]),
                    "min_buffer_pct": data.get("min_buffer_pct", DEFAULT_POLICY["min_buffer_pct"]),
                    "cooldown_seconds": DEFAULT_POLICY["cooldown_seconds"]
                }
    except Exception as e:
        print(f"⚠️ Failed to load futures_policies.json: {e}")
    
    return DEFAULT_POLICY


def evaluate_protective_mode(margin_report: Dict[str, Any], policy: Dict[str, Any]) -> str:
    """
    Determine protective mode based on worst liquidation buffer.
    
    Returns:
        - "OFF": All positions safe (>12% buffer)
        - "ALERT": Warning level (8-12% buffer)
        - "BLOCK": Block new entries (<8% buffer)
        - "REDUCE": Auto-reduce positions (<6% buffer)
    """
    positions = margin_report.get("positions", [])
    if not positions:
        return "OFF"
    
    # Find worst liquidation buffer
    buffers = [p.get("buffer_pct", 100.0) for p in positions]
    worst_buffer = min(buffers)
    
    if worst_buffer < policy["auto_reduce_pct"]:
        return "REDUCE"
    elif worst_buffer < policy["block_buffer_pct"]:
        return "BLOCK"
    elif worst_buffer < policy["alert_buffer_pct"]:
        return "ALERT"
    else:
        return "OFF"


def assess_margin_safety(state: FuturesProtectiveState, policy: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """
    Assess margin safety of all open futures positions.
    
    Returns:
        Tuple of (margin_report, protective_mode)
    """
    from src.futures_models import MarginSafetyMonitor
    from src.position_manager import load_futures_positions
    from src.blofin_futures_client import BlofinFuturesClient
    
    # Load open futures positions
    positions_file = load_futures_positions()
    positions_data = positions_file.get("open_positions", []) if isinstance(positions_file, dict) else []
    
    if not positions_data:
        return {"positions": [], "summary": "No open futures positions"}, "OFF"
    
    # Get current mark prices
    client = BlofinFuturesClient()
    mark_prices = {}
    for pos in positions_data:
        symbol = pos.get("symbol")
        if symbol:
            try:
                mark_price = client.get_mark_price(symbol)
                mark_prices[symbol] = mark_price
            except Exception as e:
                print(f"⚠️ Failed to get mark price for {symbol}: {e}")
                # Use entry price as fallback
                mark_prices[symbol] = pos.get("entry_price", 0)
    
    # Create FuturesPosition objects for monitoring
    from src.futures_models import FuturesPosition
    positions_objs = []
    for pos in positions_data:
        try:
            positions_objs.append(FuturesPosition(
                symbol=pos["symbol"],
                side=pos["direction"],
                qty=pos.get("size", 0),
                entry_price=pos["entry_price"],
                leverage=pos["leverage"],
                maintenance_margin_ratio=pos.get("maintenance_margin_ratio", 0.005),
                liquidation_price=pos.get("liquidation_price", 0)
            ))
        except Exception as e:
            print(f"⚠️ Failed to create FuturesPosition: {e}")
    
    # Run margin safety assessment
    monitor = MarginSafetyMonitor(
        min_liquidation_buffer_pct=policy["min_buffer_pct"],
        alert_buffer_pct=policy["alert_buffer_pct"]
    )
    report = monitor.assess(positions_objs, mark_prices)
    
    # Determine protective mode
    mode = evaluate_protective_mode(report, policy)
    state.mode = mode
    
    # Persist state
    state_file = LOGS / "futures_protective_state.json"
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w") as f:
            json.dump({
                "timestamp": datetime.utcnow().isoformat(),
                "mode": mode,
                "report": report
            }, f, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save protective state: {e}")
    
    return report, mode


def auto_reduce_positions(state: FuturesProtectiveState, margin_report: Dict[str, Any], policy: Dict[str, Any]):
    """
    Automatically reduce positions that are too close to liquidation.
    Only acts if cooldown has passed.
    """
    from src.position_manager import close_futures_position, load_futures_positions
    from src.blofin_futures_client import BlofinFuturesClient
    
    positions = margin_report.get("positions", [])
    client = BlofinFuturesClient()
    
    for p in positions:
        if p.get("status") == "REDUCE_EXPOSURE":
            symbol = p["symbol"]
            
            # Check cooldown
            if not state.should_auto_act(symbol, policy["cooldown_seconds"]):
                print(f"⏸️ {symbol}: Auto-reduce on cooldown")
                continue
            
            # Get position details
            positions_file = load_futures_positions()
            positions_data = positions_file.get("open_positions", []) if isinstance(positions_file, dict) else []
            pos_data = next((pos for pos in positions_data if pos.get("symbol") == symbol), None)
            if not pos_data:
                continue
            
            # Close 50% of position by default
            try:
                mark_price = client.get_mark_price(symbol)
                success = close_futures_position(
                    symbol=symbol,
                    strategy=pos_data["strategy"],
                    direction=pos_data["direction"],
                    exit_price=mark_price,
                    reason="auto_reduce_liquidation_buffer",
                    funding_fees=0  # Simplified for emergency action
                )
                
                if success:
                    state.record_auto_action(symbol)
                    state.log_action("auto_reduce", {
                        "symbol": symbol,
                        "buffer_pct": p.get("buffer_pct"),
                        "mark_price": mark_price,
                        "reason": "buffer_below_threshold"
                    })
                    print(f"🛡️ Auto-reduced {symbol} due to low liquidation buffer ({p.get('buffer_pct'):.2f}%)")
            
            except Exception as e:
                print(f"❌ Failed to auto-reduce {symbol}: {e}")
                state.log_action("auto_reduce_failed", {
                    "symbol": symbol,
                    "error": str(e)
                })


def should_allow_futures_entry(state: FuturesProtectiveState, symbol: str) -> Tuple[bool, Optional[str]]:
    """
    Check if futures entry is allowed based on protective mode.
    
    Returns:
        Tuple of (allowed, reason_if_blocked)
    """
    if state.mode == "REDUCE":
        return False, "protective_mode_REDUCE"
    elif state.mode == "BLOCK":
        return False, "protective_mode_BLOCK"
    elif state.mode == "ALERT":
        # Allow but log warning
        print(f"⚠️ {symbol}: Futures entry allowed but margins are in ALERT state")
        return True, None
    else:
        return True, None


def execute_kill_switch(state: FuturesProtectiveState) -> List[str]:
    """
    Emergency: Close ALL futures positions immediately.
    
    Returns:
        List of symbols that were closed
    """
    from src.position_manager import close_futures_position, load_futures_positions
    from src.blofin_futures_client import BlofinFuturesClient
    
    positions_file = load_futures_positions()
    positions = positions_file.get("open_positions", []) if isinstance(positions_file, dict) else []
    
    if not positions:
        print("ℹ️ Kill switch: No open futures positions")
        return []
    
    client = BlofinFuturesClient()
    closed = []
    
    for pos in positions:
        symbol = pos["symbol"]
        try:
            mark_price = client.get_mark_price(symbol)
            success = close_futures_position(
                symbol=symbol,
                strategy=pos["strategy"],
                direction=pos["direction"],
                exit_price=mark_price,
                reason="KILL_SWITCH_EMERGENCY",
                funding_fees=0
            )
            
            if success:
                closed.append(symbol)
                print(f"🛑 Kill switch: Closed {symbol}")
        
        except Exception as e:
            print(f"❌ Kill switch failed for {symbol}: {e}")
    
    state.log_action("kill_switch", {
        "positions_closed": closed,
        "total_positions": len(positions)
    })
    
    return closed
