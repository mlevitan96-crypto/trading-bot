"""
Phase 3 Missed Opportunity Replay (MOR)

Replays missed signals to update bandits and attribution without risking capital.
Helps learning system improve from blocked signals that would have been profitable.
"""

from typing import List, Dict, Optional
import json
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class MissedSignal:
    """A signal that was blocked."""
    timestamp: str
    symbol: str
    strategy: str
    side: str
    block_reason: str
    predicted_roi: float
    predicted_pnl: float = 0.0


def get_missed_signals(lookback_hours: int = 48) -> List[MissedSignal]:
    """
    Load missed signals from the last N hours.
    
    Args:
        lookback_hours: How many hours to look back
        
    Returns:
        List of missed signals
    """
    missed_file = Path("logs/missed_opportunities.json")
    
    if not missed_file.exists():
        return []
    
    try:
        with open(missed_file) as f:
            data = json.load(f)
            
            if isinstance(data, dict) and "missed_trades" in data:
                missed_trades = data["missed_trades"]
            else:
                missed_trades = []
        
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
        
        signals = []
        for trade in missed_trades:
            try:
                ts = datetime.fromisoformat(trade.get("timestamp", ""))
                if ts >= cutoff_time:
                    signals.append(MissedSignal(
                        timestamp=trade.get("timestamp", ""),
                        symbol=trade.get("symbol", ""),
                        strategy=trade.get("strategy", ""),
                        side=trade.get("side", ""),
                        block_reason=trade.get("filter_reason", ""),
                        predicted_roi=trade.get("predicted_roi", 0.0),
                        predicted_pnl=trade.get("predicted_pnl", 0.0)
                    ))
            except (ValueError, KeyError):
                continue
        
        return signals
        
    except Exception:
        return []


def should_replay(signal: MissedSignal, relax_policy: Optional[str],
                 attribution_positive: bool) -> bool:
    """
    Check if missed signal should be replayed.
    
    Args:
        signal: Missed signal to potentially replay
        relax_policy: Current relaxation policy (if any)
        attribution_positive: Whether attribution is positive for this symbol
        
    Returns:
        True if should replay
    """
    if relax_policy is None:
        return False
    
    if "mtf" in signal.block_reason.lower() and relax_policy == "require_1m_strong+15m_neutral":
        return True
    
    if "regime" in signal.block_reason.lower() and relax_policy == "require_regime_in_favor+1m_ok":
        return True
    
    if attribution_positive and relax_policy == "allow_divergence_if_attribution_positive":
        return True
    
    return False


def simulate_signal_outcome(signal: MissedSignal) -> float:
    """
    Simulate what the P&L would have been.
    
    For now, use predicted_pnl if available, otherwise estimate from ROI.
    In production, could replay actual market data.
    
    Args:
        signal: Missed signal to simulate
        
    Returns:
        Simulated P&L in USD
    """
    if signal.predicted_pnl != 0.0:
        return signal.predicted_pnl
    
    estimated_position_size = 500.0
    return estimated_position_size * signal.predicted_roi


def replay_missed_opportunities(lookback_hours: int = 48,
                               replay_limit: int = 20,
                               relax_policy: Optional[str] = None,
                               attribution_data: Optional[Dict] = None) -> Dict:
    """
    Replay missed signals and update learning systems.
    
    Args:
        lookback_hours: How far back to look for missed signals
        replay_limit: Maximum signals to replay per run
        relax_policy: Current relaxation policy
        attribution_data: Dict mapping symbol -> attribution strength
        
    Returns:
        Replay statistics
    """
    missed_signals = get_missed_signals(lookback_hours)
    
    replayed = 0
    total_simulated_pnl = 0.0
    replay_log = []
    
    for signal in missed_signals:
        if replayed >= replay_limit:
            break
        
        attribution_strength = 0.0
        if attribution_data and signal.symbol in attribution_data:
            attribution_strength = attribution_data[signal.symbol]
        
        attribution_positive = attribution_strength > 0
        
        if should_replay(signal, relax_policy, attribution_positive):
            simulated_pnl = simulate_signal_outcome(signal)
            
            replay_log.append({
                "timestamp": datetime.now().isoformat(),
                "original_timestamp": signal.timestamp,
                "symbol": signal.symbol,
                "strategy": signal.strategy,
                "block_reason": signal.block_reason,
                "simulated_pnl": simulated_pnl,
                "relax_policy": relax_policy
            })
            
            total_simulated_pnl += simulated_pnl
            replayed += 1
    
    log_file = Path("logs/phase3_mor_replay.json")
    log_file.parent.mkdir(exist_ok=True)
    
    if log_file.exists():
        try:
            with open(log_file) as f:
                existing_log = json.load(f)
        except Exception:
            existing_log = []
    else:
        existing_log = []
    
    existing_log.extend(replay_log)
    existing_log = existing_log[-10000:]
    
    with open(log_file, 'w') as f:
        json.dump(existing_log, f, indent=2)
    
    return {
        "replayed_count": replayed,
        "total_simulated_pnl": total_simulated_pnl,
        "avg_simulated_pnl": total_simulated_pnl / replayed if replayed > 0 else 0.0,
        "missed_count": len(missed_signals)
    }
