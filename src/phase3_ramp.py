"""
Phase 3 Capital Ramp Controller

Staged leverage increases with metric-based gating.
Only advances when Sharpe/Sortino hold and drawdown is controlled.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
import time
import json
from pathlib import Path
from datetime import datetime


@dataclass
class RampStage:
    """Single capital ramp stage."""
    duration_hours: int
    max_leverage: float
    note: str


@dataclass
class RampState:
    """Capital ramp progression state."""
    stage_index: int = 0
    stage_start_ts: Optional[float] = None
    total_ramp_hours: float = 0.0
    paused: bool = False
    pause_reason: Optional[str] = None


class CapitalRampController:
    """Manages staged capital ramp with metric-based gating."""
    
    def __init__(self, stages: List[Dict], hold_sharpe: float = 0.25,
                 hold_sortino: float = 0.3, max_drawdown_bps: float = 300.0):
        """
        Initialize capital ramp controller.
        
        Args:
            stages: List of ramp stage dicts with duration_hours, max_leverage, note
            hold_sharpe: Minimum Sharpe to advance
            hold_sortino: Minimum Sortino to advance
            max_drawdown_bps: Maximum allowed drawdown (positive bps)
        """
        self.stages = [RampStage(**s) for s in stages]
        self.hold_sharpe = hold_sharpe
        self.hold_sortino = hold_sortino
        self.max_drawdown_bps = max_drawdown_bps
        self.state = self._load_state()
    
    def get_current_leverage_cap(self, throttle_ok: bool, sharpe: float, 
                                 sortino: float, drawdown_bps: float) -> float:
        """
        Get current leverage cap based on ramp state and metrics.
        
        Args:
            throttle_ok: Phase 2 throttle status (True = ok to trade)
            sharpe: Current Sharpe ratio
            sortino: Current Sortino ratio
            drawdown_bps: Current drawdown in bps (negative)
            
        Returns:
            Maximum allowed leverage
        """
        current_stage = self.stages[self.state.stage_index]
        
        metrics_hold = (
            throttle_ok and
            sharpe >= self.hold_sharpe and
            sortino >= self.hold_sortino and
            drawdown_bps > -self.max_drawdown_bps
        )
        
        if not metrics_hold:
            if not self.state.paused:
                self.state.paused = True
                self.state.pause_reason = self._get_pause_reason(
                    throttle_ok, sharpe, sortino, drawdown_bps
                )
                self._save_state()
            
            return current_stage.max_leverage
        
        if self.state.paused:
            self.state.paused = False
            self.state.pause_reason = None
            self._save_state()
        
        now = time.time()
        if self.state.stage_start_ts is None:
            self.state.stage_start_ts = now
            self._save_state()
        
        elapsed_hours = (now - self.state.stage_start_ts) / 3600
        stage_complete = elapsed_hours >= current_stage.duration_hours
        
        if stage_complete and self.state.stage_index < len(self.stages) - 1:
            self.state.stage_index += 1
            self.state.stage_start_ts = now
            self.state.total_ramp_hours += elapsed_hours
            self._save_state()
            
            return self.stages[self.state.stage_index].max_leverage
        
        return current_stage.max_leverage
    
    def get_ramp_progress(self) -> Dict:
        """Get ramp progression status."""
        current_stage = self.stages[self.state.stage_index]
        
        progress = {
            "current_stage": self.state.stage_index + 1,
            "total_stages": len(self.stages),
            "stage_note": current_stage.note,
            "current_leverage_cap": current_stage.max_leverage,
            "paused": self.state.paused,
            "pause_reason": self.state.pause_reason,
            "total_ramp_hours": self.state.total_ramp_hours
        }
        
        if self.state.stage_start_ts:
            elapsed = (time.time() - self.state.stage_start_ts) / 3600
            progress["stage_elapsed_hours"] = round(elapsed, 2)
            progress["stage_duration_hours"] = current_stage.duration_hours
            progress["stage_progress_pct"] = min(100, (elapsed / current_stage.duration_hours) * 100)
        else:
            progress["stage_elapsed_hours"] = 0
            progress["stage_duration_hours"] = current_stage.duration_hours
            progress["stage_progress_pct"] = 0
        
        return progress
    
    def reset_ramp(self):
        """Reset ramp to initial stage."""
        self.state = RampState()
        self._save_state()
    
    def _get_pause_reason(self, throttle_ok: bool, sharpe: float,
                         sortino: float, drawdown_bps: float) -> str:
        """Determine reason for ramp pause."""
        reasons = []
        
        if not throttle_ok:
            reasons.append("throttle_inactive")
        if sharpe < self.hold_sharpe:
            reasons.append(f"sharpe_low({sharpe:.2f}<{self.hold_sharpe})")
        if sortino < self.hold_sortino:
            reasons.append(f"sortino_low({sortino:.2f}<{self.hold_sortino})")
        if drawdown_bps <= -self.max_drawdown_bps:
            reasons.append(f"drawdown_high({drawdown_bps:.1f}bps)")
        
        return ", ".join(reasons) if reasons else "metrics_degraded"
    
    def _save_state(self):
        """Save ramp state to disk."""
        state_file = Path("logs/phase3_ramp_state.json")
        state_file.parent.mkdir(exist_ok=True)
        
        data = {
            "stage_index": self.state.stage_index,
            "stage_start_ts": self.state.stage_start_ts,
            "total_ramp_hours": self.state.total_ramp_hours,
            "paused": self.state.paused,
            "pause_reason": self.state.pause_reason,
            "updated_at": datetime.now().isoformat()
        }
        
        with open(state_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_state(self) -> RampState:
        """Load ramp state from disk."""
        state_file = Path("logs/phase3_ramp_state.json")
        
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                    
                    return RampState(
                        stage_index=data.get("stage_index", 0),
                        stage_start_ts=data.get("stage_start_ts"),
                        total_ramp_hours=data.get("total_ramp_hours", 0.0),
                        paused=data.get("paused", False),
                        pause_reason=data.get("pause_reason")
                    )
            except Exception:
                pass
        
        return RampState()
