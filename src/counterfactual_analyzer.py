"""
Counterfactual Analysis Module
Analyzes trades that were NOT taken to learn from missed opportunities.

Features:
- Track potential trades that failed pre-trade risk checks
- Analyze what would have happened if we took them
- Learn from false negatives (good trades we skipped)
- Identify overly conservative risk filters
- Feed insights back to learning engine
"""

import json
import time
import os
from typing import Dict, List, Optional

COUNTERFACTUAL_LOG = "logs/counterfactual_analysis.jsonl"

def _now():
    return int(time.time())

def _append_jsonl(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj) + "\n")

class CounterfactualAnalyzer:
    """Analyzes trades we didn't take and learns from them."""
    
    def __init__(self):
        self.rejected_signals = []
        self.missed_opportunities = []
        
    def log_rejected_signal(self, symbol: str, reason: str, signal_data: Dict):
        """Log a trading signal that was rejected by risk filters."""
        entry = {
            "ts": _now(),
            "symbol": symbol,
            "reason": reason,
            "signal_strength": signal_data.get("strength", 0),
            "entry_price": signal_data.get("price", 0),
            "direction": signal_data.get("direction", "LONG"),
            "risk_metrics": signal_data.get("risk_metrics", {}),
            "event": "signal_rejected"
        }
        
        self.rejected_signals.append(entry)
        _append_jsonl(COUNTERFACTUAL_LOG, entry)
        
        # Keep only last 1000 rejected signals in memory
        if len(self.rejected_signals) > 1000:
            self.rejected_signals = self.rejected_signals[-1000:]
    
    def analyze_outcome(self, symbol: str, entry_price: float, direction: str, 
                       exit_price: float, hours_held: float = 24):
        """
        Analyze what would have happened if we took a rejected trade.
        
        Args:
            symbol: Trading pair
            entry_price: Price at signal time
            direction: LONG or SHORT
            exit_price: Current price (or price after time window)
            hours_held: Time window for analysis
        """
        if direction == "LONG":
            roi = (exit_price - entry_price) / entry_price
        else:  # SHORT
            roi = (entry_price - exit_price) / entry_price
        
        outcome = {
            "ts": _now(),
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "direction": direction,
            "roi": round(roi, 6),
            "hours_held": hours_held,
            "would_have_won": roi > 0,
            "would_have_profit_pct": round(roi * 100, 2),
            "event": "counterfactual_outcome"
        }
        
        self.missed_opportunities.append(outcome)
        _append_jsonl(COUNTERFACTUAL_LOG, outcome)
        
        return outcome
    
    def get_recent_missed_opportunities(self, lookback_hours: int = 168) -> List[Dict]:
        """Get missed opportunities from the last N hours."""
        cutoff = _now() - (lookback_hours * 3600)
        
        recent = []
        try:
            if os.path.exists(COUNTERFACTUAL_LOG):
                with open(COUNTERFACTUAL_LOG, 'r') as f:
                    for line in f:
                        entry = json.loads(line)
                        if entry.get("event") == "counterfactual_outcome" and entry.get("ts", 0) >= cutoff:
                            recent.append(entry)
        except Exception as e:
            print(f"⚠️  [Counterfactual] Failed to load log: {e}")
        
        return recent
    
    def analyze_false_negatives(self, lookback_hours: int = 168) -> Dict:
        """
        Analyze false negatives: good trades we rejected.
        
        Returns summary of:
        - Total rejected signals
        - How many would have been winners
        - Average ROI of missed opportunities
        - Most common rejection reasons
        """
        recent = self.get_recent_missed_opportunities(lookback_hours)
        
        if not recent:
            return {
                "total_counterfactuals": 0,
                "would_have_won": 0,
                "would_have_lost": 0,
                "missed_win_rate": 0.0,
                "avg_missed_roi": 0.0,
                "total_missed_profit_pct": 0.0
            }
        
        winners = [r for r in recent if r.get("would_have_won", False)]
        losers = [r for r in recent if not r.get("would_have_won", False)]
        
        total_roi = sum(r.get("roi", 0) for r in recent)
        avg_roi = total_roi / len(recent) if recent else 0.0
        
        return {
            "total_counterfactuals": len(recent),
            "would_have_won": len(winners),
            "would_have_lost": len(losers),
            "missed_win_rate": round(len(winners) / len(recent), 4) if recent else 0.0,
            "avg_missed_roi": round(avg_roi, 6),
            "total_missed_profit_pct": round(total_roi * 100, 2),
            "top_missed_winners": sorted(
                [{"symbol": r["symbol"], "roi_pct": r["would_have_profit_pct"]} 
                 for r in winners],
                key=lambda x: x["roi_pct"],
                reverse=True
            )[:5]
        }
    
    def get_rejection_reason_stats(self, lookback_hours: int = 168) -> Dict[str, int]:
        """Get counts of rejection reasons."""
        cutoff = _now() - (lookback_hours * 3600)
        
        reason_counts = {}
        try:
            if os.path.exists(COUNTERFACTUAL_LOG):
                with open(COUNTERFACTUAL_LOG, 'r') as f:
                    for line in f:
                        entry = json.loads(line)
                        if entry.get("event") == "signal_rejected" and entry.get("ts", 0) >= cutoff:
                            reason = entry.get("reason", "unknown")
                            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        except Exception as e:
            print(f"⚠️  [Counterfactual] Failed to load log: {e}")
        
        return dict(sorted(reason_counts.items(), key=lambda x: x[1], reverse=True))


# Global singleton
_counterfactual_analyzer = None

def get_counterfactual_analyzer() -> CounterfactualAnalyzer:
    """Get or create the global counterfactual analyzer."""
    global _counterfactual_analyzer
    if _counterfactual_analyzer is None:
        _counterfactual_analyzer = CounterfactualAnalyzer()
    return _counterfactual_analyzer


def log_rejected_trade(symbol: str, reason: str, signal_data: Dict):
    """Convenience function to log a rejected trade signal."""
    analyzer = get_counterfactual_analyzer()
    analyzer.log_rejected_signal(symbol, reason, signal_data)


def analyze_missed_opportunity(symbol: str, entry_price: float, direction: str, 
                               exit_price: float, hours_held: float = 24):
    """Convenience function to analyze a missed trade opportunity."""
    analyzer = get_counterfactual_analyzer()
    return analyzer.analyze_outcome(symbol, entry_price, direction, exit_price, hours_held)


def get_counterfactual_summary(lookback_hours: int = 168) -> Dict:
    """Get summary of false negatives and missed opportunities."""
    analyzer = get_counterfactual_analyzer()
    
    false_negatives = analyzer.analyze_false_negatives(lookback_hours)
    rejection_reasons = analyzer.get_rejection_reason_stats(lookback_hours)
    
    return {
        "false_negatives": false_negatives,
        "rejection_reasons": rejection_reasons,
        "analysis_window_hours": lookback_hours
    }
