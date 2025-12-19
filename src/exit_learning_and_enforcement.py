# src/exit_learning_and_enforcement.py
#
# Phase 14.0 – Dynamic Exit Learning & Runtime Enforcement
# Purpose:
#   - Enforce minimum-hold discipline, laddered take-profit, ATR-based trailing
#   - Log MAE/MFE, time-to-targets, and exit attribution
#   - Nightly auto-tune TP/SL/hold windows per symbol and regime based on realized outcomes
#   - Integrate with existing governance/learning system and strategy executor
#
# Usage (runtime):
#   manager = ExitManager(symbol="SOLUSDT", regime="volatile")
#   decision = manager.update(position_state_dict)
#   if decision["action"] in {"tp1","tp2","trail_exit","stop","time_stop"}:
#       execute_partial_or_close(decision)
#   manager.on_close(final_position_state)  # flush attribution when position fully closes
#
# Usage (nightly tuner):
#   ExitTuner.run_nightly_tuning()  # adjusts config/exit_policy.json based on logs/exit_runtime_events.jsonl

import os
import json
import time
from typing import Dict, Optional, List
from statistics import mean

# ---- Config & Log paths ----
EXIT_POLICY_PATH        = "config/exit_policy.json"
EXIT_RUNTIME_LOG        = "logs/exit_runtime_events.jsonl"   # per-exit action logs
EXIT_TUNING_EVENTS_LOG  = "logs/exit_tuning_events.jsonl"    # nightly tuning decisions

# ---- Defaults (overridden by policy) ----
DEFAULT_EXIT_POLICY = {
    "TP1_ROI": 0.005,            # 0.5%
    "TP2_ROI": 0.010,            # 1.0%
    "TP1_SIZE": 0.40,            # 40% of position
    "TP2_SIZE": 0.40,            # 40% of position
    "RUNNER_SIZE": 0.20,         # 20% of position
    "TRAIL_ATR_MULT": 1.5,       # trail distance = k * ATR
    "STOP_LOSS_ROI": -0.005,     # -0.5% stop as baseline
    "MIN_HOLD_MINUTES": 30,      # minimum hold before exits
    "TIME_STOP_MINUTES": 180,    # max time without TP1 → close
    "REGIME_OVERRIDES": {        # optional regime-specific overrides
        "volatile": {"TRAIL_ATR_MULT": 2.0, "MIN_HOLD_MINUTES": 45},
        "choppy":   {"TP1_ROI": 0.006, "TP2_ROI": 0.012, "TRAIL_ATR_MULT": 1.2, "MIN_HOLD_MINUTES": 20},
        "trending": {"TP1_ROI": 0.004, "TP2_ROI": 0.009, "TRAIL_ATR_MULT": 1.8, "MIN_HOLD_MINUTES": 60}
    }
}

# ---- IO helpers ----
def _read_json(path: str, default: dict) -> dict:
    if not os.path.exists(path): return default
    with open(path, "r") as f:
        try: return json.load(f)
        except: return default

def _write_json(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: json.dump(obj, f, indent=2)

def _append_jsonl(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    obj = dict(obj)
    obj["ts"] = obj.get("ts", int(time.time()))
    with open(path, "a") as f: f.write(json.dumps(obj) + "\n")

def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path): return []
    out = []
    with open(path, "r") as f:
        for line in f:
            s = line.strip()
            if s:
                try: out.append(json.loads(s))
                except: pass
    return out

# ---- Exit Manager (runtime enforcement) ----
class ExitManager:
    def __init__(self, symbol: str, regime: str = "default"):
        self.symbol = symbol
        self.regime = regime
        self.params = self._compose_params(symbol, regime)
        # Runtime attribution state
        self.open_ts: Optional[int] = None
        self.mae = 0.0            # maximum adverse excursion (min ROI)
        self.mfe = 0.0            # maximum favorable excursion (max ROI)
        self.tp1_hit_ts: Optional[int] = None
        self.tp2_hit_ts: Optional[int] = None
        self.tp1_taken = False
        self.tp2_taken = False
        self.runner_active = False
        self.break_even_roi = 0.0  # floor after TP1 so we don't trail below breakeven

    def _compose_params(self, symbol: str, regime: str) -> dict:
        policy_all = _read_json(EXIT_POLICY_PATH, {})
        base = dict(DEFAULT_EXIT_POLICY)
        tuned_symbol = policy_all.get(symbol, {})
        # merge symbol-level tuned values
        for k, v in tuned_symbol.items():
            if k == "REGIME_OVERRIDES": continue
            base[k] = v
        # regime overrides (policy or default)
        overrides = tuned_symbol.get("REGIME_OVERRIDES", base.get("REGIME_OVERRIDES", {})).get(regime, {})
        base.update(overrides)
        return base

    def update(self, pos: Dict) -> Dict:
        """
        pos expected keys:
          - roi: float (current ROI as decimal, e.g., 0.006 for 0.6%)
          - atr_roi: float (ATR expressed as ROI decimal for distance calc)
          - minutes_open: int
          - is_long: bool
          - size_remaining: float (0..1 of original size)
          - entry_price: float (optional)
          - closed: bool
        Return decision dict:
          {"action": "hold|tp1|tp2|trail_exit|stop|time_stop|none", "size_fraction": float, "reason": str}
        """
        if self.open_ts is None: self.open_ts = int(time.time())

        roi = float(pos.get("roi", 0.0))
        atr = float(pos.get("atr_roi", 0.0))
        minutes_open = int(pos.get("minutes_open", 0))
        size_remaining = float(pos.get("size_remaining", 1.0))

        # Track excursions
        self.mae = min(self.mae, roi)
        self.mfe = max(self.mfe, roi)

        # Minimum hold enforcement before any exit logic
        if minutes_open < self.params["MIN_HOLD_MINUTES"]:
            return {"action": "hold", "size_fraction": 0.0, "reason": "min_hold_enforced"}

        # Hard stop-loss
        if roi <= self.params["STOP_LOSS_ROI"]:
            self._log_exit(pos, "stop")
            return {"action": "stop", "size_fraction": 1.0, "reason": "stop_loss_hit"}

        # Time stop (only before TP1 to avoid cutting winners prematurely)
        if minutes_open >= self.params["TIME_STOP_MINUTES"] and not self.tp1_taken:
            self._log_exit(pos, "time_stop")
            return {"action": "time_stop", "size_fraction": 1.0, "reason": "time_stop_no_tp1"}

        # TP1
        if (not self.tp1_taken) and roi >= self.params["TP1_ROI"]:
            self.tp1_taken = True
            self.tp1_hit_ts = int(time.time())
            self.runner_active = True
            self.break_even_roi = 0.0  # enforce no trailing below breakeven post-TP1
            self._log_exit(pos, "tp1")
            return {"action": "tp1", "size_fraction": self.params["TP1_SIZE"], "reason": "tp1_threshold_hit"}

        # TP2
        if self.tp1_taken and (not self.tp2_taken) and roi >= self.params["TP2_ROI"]:
            self.tp2_taken = True
            self.tp2_hit_ts = int(time.time())
            self._log_exit(pos, "tp2")
            return {"action": "tp2", "size_fraction": self.params["TP2_SIZE"], "reason": "tp2_threshold_hit"}

        # Trailing runner
        if self.runner_active and size_remaining > 0.0:
            trail_dist = self.params["TRAIL_ATR_MULT"] * atr
            trail_floor = max(self.break_even_roi, self.mfe - trail_dist)
            if roi <= trail_floor:
                self._log_exit(pos, "trailing")
                # Exit whatever remains or runner size if provided differently
                size_fraction = size_remaining if size_remaining < self.params["RUNNER_SIZE"] else self.params["RUNNER_SIZE"]
                return {"action": "trail_exit", "size_fraction": size_fraction, "reason": "trailing_floor_hit"}

        # Hold if nothing else
        return {"action": "hold", "size_fraction": 0.0, "reason": "await_targets"}

    def on_close(self, final_pos: Dict):
        # Log final attribution payload on close (e.g., realized pnl, total minutes)
        event = {
            "symbol": self.symbol,
            "exit_type": "closed",
            "mae": round(self.mae, 6),
            "mfe": round(self.mfe, 6),
            "tp1_taken": self.tp1_taken,
            "tp2_taken": self.tp2_taken,
            "runner_active": self.runner_active,
            "minutes_open": final_pos.get("minutes_open", None),
            "realized_roi": final_pos.get("roi", None),
            "params": self.params
        }
        _append_jsonl(EXIT_RUNTIME_LOG, event)

    def _log_exit(self, pos: Dict, exit_type: str):
        event = {
            "symbol": self.symbol,
            "exit_type": exit_type,
            "mae": round(self.mae, 6),
            "mfe": round(self.mfe, 6),
            "tp1_taken": self.tp1_taken,
            "tp2_taken": self.tp2_taken,
            "runner_active": self.runner_active,
            "roi": pos.get("roi", 0.0),
            "atr_roi": pos.get("atr_roi", 0.0),
            "minutes_open": pos.get("minutes_open", 0),
            "params": self.params
        }
        if exit_type == "tp1" and self.open_ts is not None:
            event["time_to_tp1_sec"] = int(time.time()) - self.open_ts
        elif exit_type == "tp2":
            base_ts = self.tp1_hit_ts if self.tp1_hit_ts is not None else (self.open_ts or int(time.time()))
            event["time_to_tp2_sec"] = int(time.time()) - base_ts
        elif exit_type == "trailing":
            base_ts = self.tp2_hit_ts if self.tp2_hit_ts is not None else (self.tp1_hit_ts if self.tp1_hit_ts is not None else (self.open_ts or int(time.time())))
            event["time_to_trail_sec"] = int(time.time()) - base_ts
        _append_jsonl(EXIT_RUNTIME_LOG, event)

# ---- Nightly Exit Tuner (learn from runtime logs) ----
class ExitTuner:
    @staticmethod
    def run_nightly_tuning():
        # Load current policy and runtime logs
        policy = _read_json(EXIT_POLICY_PATH, {})
        logs = _read_jsonl(EXIT_RUNTIME_LOG)

        # Aggregate by symbol (optionally by regime if present)
        by_symbol = {}
        for e in logs:
            sym = e.get("symbol")
            if not sym: continue
            L = by_symbol.setdefault(sym, [])
            L.append(e)

        # For each symbol, compute hit-rates and P&L proxies from exit events
        tuning_decisions = []
        for sym, events in by_symbol.items():
            if not events: continue

            # Hit-rate proxies (include new profit_target exits from trailing_stop.py)
            tp1_hits = sum(1 for e in events if e.get("exit_type") == "tp1")
            tp2_hits = sum(1 for e in events if e.get("exit_type") == "tp2")
            trail_exits = sum(1 for e in events if e.get("exit_type") == "trailing" or (e.get("exit_type") == "closed" and "trailing" in str(e.get("reason", ""))))
            # Count profit target exits (from trailing_stop.py profit_target_* reasons)
            profit_target_exits = sum(1 for e in events if "profit_target" in str(e.get("exit_type", "")) or "profit_target" in str(e.get("reason", "")))
            stops = sum(1 for e in events if e.get("exit_type") == "stop")
            time_stops = sum(1 for e in events if e.get("exit_type") == "time_stop")
            
            # Analyze profitability of exits
            profitable_exits = sum(1 for e in events if e.get("was_profitable", False) or (e.get("roi", 0) or e.get("realized_roi", 0)) > 0)
            total_exits_count = len(events)

            # Volatility proxy from ATR
            atrs = [float(e.get("atr_roi", 0.0)) for e in events if e.get("atr_roi") is not None]
            avg_atr = mean(atrs) if atrs else 0.0

            # MFE/MAE averages
            mfes = [float(e.get("mfe", 0.0)) for e in events]
            maes = [float(e.get("mae", 0.0)) for e in events]
            avg_mfe = mean(mfes) if mfes else 0.0
            avg_mae = mean(maes) if maes else 0.0

            # Current params (fallback to defaults)
            current = dict(DEFAULT_EXIT_POLICY)
            current.update(policy.get(sym, {}))

            new_params = dict(current)

            # Tuning heuristics (data-driven adjustments):
            # 1) TP levels: if tp1_hits are frequent and tp2 rare, consider lowering TP2 slightly
            total_exits = max(1, tp1_hits + tp2_hits + trail_exits + profit_target_exits + stops + time_stops)
            tp1_rate = tp1_hits / total_exits
            tp2_rate = tp2_hits / total_exits
            trail_rate = trail_exits / total_exits
            profit_target_rate = profit_target_exits / total_exits
            stop_rate = stops / total_exits
            
            # Analyze if profit targets are working (profitable exits increasing)
            profitability_rate = profitable_exits / total_exits_count if total_exits_count > 0 else 0

            # Lower TP2 if very few reach TP2 but many reach TP1 (suggest targets too far in current regime)
            if tp1_rate > 0.35 and tp2_rate < 0.10:
                new_params["TP2_ROI"] = max(current["TP2_ROI"] - 0.002, current["TP1_ROI"] + 0.002)  # reduce by 0.2%
            # Raise TP1 if too many time_stops/stops occur before TP1 (avoid dead trades)
            if (time_stops + stops) / total_exits > 0.30:
                new_params["TP1_ROI"] = min(current["TP1_ROI"] + 0.001, 0.012)  # increase by 0.1%
            
            # CRITICAL: Learn from less profitable exits - adjust targets based on MFE analysis
            # If profit targets have high hit rate but we're missing bigger moves (low MFE capture)
            if profit_target_rate > 0.30 and profitability_rate < 0.40:
                # Many profit targets but low profitability - may be exiting too early
                # Check if we're capturing enough of the MFE
                if avg_mfe > current["TP1_ROI"] * 2.0:  # MFE is much higher than TP1
                    # We're exiting too early - positions are reaching higher profits
                    # BUT: If profitability is low, it means positions are reversing before targets
                    # So we should LOWER targets to capture profits before reversal
                    new_params["TP1_ROI"] = max(current["TP1_ROI"] - 0.001, 0.003)  # Lower TP1 to 0.3%
                    new_params["TP2_ROI"] = max(current["TP2_ROI"] - 0.002, current["TP1_ROI"] + 0.002)
                    tuning_decisions[-1]["stats"]["adjustment"] = "Lowered targets to capture profits before reversals"
            elif profit_target_rate > 0.50 and profitability_rate > 0.60:
                # High profit target rate AND high profitability - system is working well!
                # But check if we could capture more of the MFE
                if avg_mfe > current["TP2_ROI"] * 1.5:  # MFE is 50% higher than TP2
                    # Consider raising TP2 slightly to capture more profit
                    new_params["TP2_ROI"] = min(current["TP2_ROI"] + 0.002, 0.015)  # Raise TP2 by 0.2%
                    tuning_decisions[-1]["stats"]["adjustment"] = "Raised TP2 to capture more of high MFE moves"
            
            # NEW: Learn from early exits - if we're frequently missing >1% profit opportunities
            early_exit_events = [e for e in events if e.get("mfe", 0) > e.get("roi", 0) * 1.5 and e.get("roi", 0) > 0]
            if len(early_exit_events) > total_exits * 0.20:  # >20% of exits are early
                avg_early_miss = sum(e.get("mfe", 0) - e.get("roi", 0) for e in early_exit_events) / len(early_exit_events)
                if avg_early_miss > 0.005:  # Missing >0.5% on average
                    # Consider adding a "hold extended" rule or higher tier profit targets
                    tuning_decisions[-1]["stats"]["early_exit_warning"] = f"Missing avg {avg_early_miss*100:.2f}% profit on {len(early_exit_events)} early exits"

            # 2) Trailing distance: widen in high volatility, tighten in chop
            if avg_atr > 0.007:    # high vol regime proxy
                new_params["TRAIL_ATR_MULT"] = min(current["TRAIL_ATR_MULT"] + 0.2, 2.5)
            elif avg_atr < 0.003:  # choppy/low-vol proxy
                new_params["TRAIL_ATR_MULT"] = max(current["TRAIL_ATR_MULT"] - 0.2, 1.0)

            # 3) Stop-loss distance: reduce premature stops when avg_mae << stop
            # If MAE typically small but stop-outs frequent, stop might be too tight; otherwise, tighten if MAE large
            if stop_rate > 0.25 and avg_mae > current["STOP_LOSS_ROI"] * 0.5:
                # Loosen stop slightly (more negative allowed)
                new_params["STOP_LOSS_ROI"] = min(current["STOP_LOSS_ROI"] - 0.001, -0.02)
            elif stop_rate < 0.10 and avg_mae < current["STOP_LOSS_ROI"] * 0.3:
                # Tighten stop to protect downside
                new_params["STOP_LOSS_ROI"] = max(current["STOP_LOSS_ROI"] + 0.0005, -0.002)

            # 4) Minimum hold: increase if frequent time_stops (suggesting hold window too short)
            if time_stops / total_exits > 0.20:
                new_params["MIN_HOLD_MINUTES"] = min(current["MIN_HOLD_MINUTES"] + 10, 120)

            # Save tuning decision
            decision = {
                "symbol": sym,
                "old_params": current,
                "new_params": new_params,
                "stats": {
                    "tp1_rate": round(tp1_rate, 3),
                    "tp2_rate": round(tp2_rate, 3),
                    "trail_rate": round(trail_rate, 3),
                    "profit_target_rate": round(profit_target_rate, 3),
                    "profitability_rate": round(profitability_rate, 3),
                    "stop_rate": round(stop_rate, 3),
                    "avg_atr": round(avg_atr, 6),
                    "avg_mfe": round(avg_mfe, 6),
                    "avg_mae": round(avg_mae, 6),
                    "total_exits": total_exits,
                    "profitable_exits": profitable_exits,
                    "total_exits_count": total_exits_count
                }
            }
            tuning_decisions.append(decision)
            _append_jsonl(EXIT_TUNING_EVENTS_LOG, decision)

            # Update policy with new params
            policy[sym] = new_params

        # Write updated policy to disk
        _write_json(EXIT_POLICY_PATH, policy)
        print(f"✅ [EXIT_TUNER] Tuned {len(tuning_decisions)} symbols; policy saved to {EXIT_POLICY_PATH}")
        return tuning_decisions

# ---- Strategy executor adapter (runtime hook) ----
class ExitAdapter:
    """
    Thin adapter to integrate ExitManager into the strategy executor loop.
    Maintains manager instances per open position and applies actions.
    """
    def __init__(self):
        self._managers: Dict[str, ExitManager] = {}  # key: position_id

    def attach(self, position_id: str, symbol: str, regime: str = "default"):
        self._managers[position_id] = ExitManager(symbol=symbol, regime=regime)

    def update(self, position_id: str, state: Dict) -> Dict:
        mgr = self._managers.get(position_id)
        if not mgr:
            # Lazily attach with default regime if missing
            self.attach(position_id, symbol=state.get("symbol", "UNKNOWN"), regime=state.get("regime", "default"))
            mgr = self._managers[position_id]
        decision = mgr.update(state)
        # Emit runtime log for traceability (non-exit "hold" is not logged to reduce noise)
        if decision["action"] != "hold":
            _append_jsonl(EXIT_RUNTIME_LOG, {
                "symbol": state.get("symbol"),
                "position_id": position_id,
                "exit_type": decision["action"],
                "size_fraction": decision.get("size_fraction", 0.0),
                "reason": decision.get("reason", ""),
                "roi": state.get("roi", 0.0),
                "atr_roi": state.get("atr_roi", 0.0),
                "minutes_open": state.get("minutes_open", 0),
                "params": mgr.params
            })
        return decision

    def on_close(self, position_id: str, final_state: Dict):
        mgr = self._managers.get(position_id)
        if mgr:
            mgr.on_close(final_state)
            # Cleanup
            self._managers.pop(position_id, None)

# ---- Integration hooks for bot_cycle ----
def create_exit_manager(symbol: str, regime: str = "default") -> ExitManager:
    """Factory function to create an exit manager for a position."""
    return ExitManager(symbol=symbol, regime=regime)

def run_nightly_exit_tuning():
    """Hook for nightly maintenance scheduler to auto-tune exit policies."""
    return ExitTuner.run_nightly_tuning()

# ---- Example main hooks ----
if __name__ == "__main__":
    # Nightly tuning
    run_nightly_exit_tuning()
    print("Phase 14.0 exit learning nightly tuning complete.")
