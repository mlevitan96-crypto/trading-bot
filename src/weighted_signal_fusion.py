#!/usr/bin/env python3
"""
WEIGHTED SIGNAL FUSION SYSTEM
All intelligence sources contribute weighted probability scores to long/short decisions.
No binary on/off - every signal adjusts the probability.

Entry Decision: Weighted combination of all signals → long_prob, short_prob
Exit Decision: Weighted combination of timing signals → hold_prob, exit_prob

Weights are learned from historical performance and adjusted based on recent accuracy.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import math

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR


SIGNAL_WEIGHTS_PATH = "feature_store/signal_weights.json"
EXIT_WEIGHTS_PATH = "feature_store/exit_weights.json"
FUSION_HISTORY_PATH = "logs/fusion_history.jsonl"

DEFAULT_ENTRY_WEIGHTS = {
    "ofi": 0.25,
    "ensemble": 0.20,
    "mtf_alignment": 0.15,
    "regime": 0.10,
    "market_intel": 0.10,
    "volume": 0.08,
    "momentum": 0.07,
    "session": 0.05
}

DEFAULT_EXIT_WEIGHTS = {
    "unrealized_pnl": 0.25,
    "mtf_exit_signal": 0.20,
    "regime_shift": 0.15,
    "hold_duration": 0.15,
    "trailing_stop": 0.10,
    "momentum_reversal": 0.10,
    "volume_decline": 0.05
}

MIN_WEIGHT = 0.02
MAX_WEIGHT = 0.40
WEIGHT_ADJUSTMENT_RATE = 0.05


def load_json(path: str) -> Dict:
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return {}


def save_json(path: str, data: Dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def append_jsonl(path: str, record: Dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record) + "\n")


def sigmoid(x: float, k: float = 1.0) -> float:
    """Smooth sigmoid function to convert raw scores to probabilities."""
    try:
        return 1 / (1 + math.exp(-k * x))
    except:
        return 0.5


def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalize weights to sum to 1.0."""
    total = sum(weights.values())
    if total == 0:
        return weights
    return {k: v / total for k, v in weights.items()}


class SignalScorer:
    """
    Converts raw signal values to probability contributions.
    Each signal contributes a score from -1 (strongly short) to +1 (strongly long).
    """
    
    @staticmethod
    def score_ofi(ofi_value: float, direction: str) -> float:
        """
        OFI score: How strongly does OFI support the direction?
        OFI > 0 = buying pressure (supports LONG)
        OFI < 0 = selling pressure (supports SHORT)
        Returns: -1 to +1 score
        """
        if direction == "LONG":
            return min(max(ofi_value * 2, -1), 1)
        else:
            return min(max(-ofi_value * 2, -1), 1)
    
    @staticmethod
    def score_ensemble(ensemble_value: float, direction: str) -> float:
        """
        Ensemble score: How strongly does the ensemble agree with direction?
        Returns: -1 to +1 score
        """
        if direction == "LONG":
            return min(max(ensemble_value * 10, -1), 1)
        else:
            return min(max(-ensemble_value * 10, -1), 1)
    
    @staticmethod
    def score_mtf_alignment(trends: Dict[str, str], direction: str) -> float:
        """
        MTF alignment: How many timeframes agree with direction?
        trends: {"1m": "up/down/neutral", "5m": ..., "15m": ..., "1h": ...}
        Returns: -1 to +1 score
        """
        aligned = 0
        total = 0
        target = "up" if direction == "LONG" else "down"
        
        for tf, trend in trends.items():
            total += 1
            if trend == target:
                aligned += 1
            elif trend != "neutral":
                aligned -= 1
        
        if total == 0:
            return 0
        return aligned / total
    
    @staticmethod
    def score_regime(regime: str, direction: str) -> float:
        """
        Regime score: How favorable is the current regime for this direction?
        Returns: -1 to +1 score
        """
        regime_scores = {
            "LONG": {
                "bull_trend": 0.8,
                "recovery": 0.5,
                "stable": 0.2,
                "chop": -0.2,
                "bear_trend": -0.6,
                "crash": -0.9
            },
            "SHORT": {
                "bear_trend": 0.8,
                "crash": 0.5,
                "chop": 0.2,
                "stable": -0.1,
                "recovery": -0.5,
                "bull_trend": -0.8
            }
        }
        return regime_scores.get(direction, {}).get(regime, 0)
    
    @staticmethod
    def score_market_intel(intel: Dict, direction: str) -> float:
        """
        Market intelligence score based on liquidations, taker volume, fear/greed.
        Returns: -1 to +1 score
        """
        score = 0
        
        taker_ratio = intel.get("taker_buy_sell_ratio", 1.0)
        if direction == "LONG":
            score += (taker_ratio - 1.0) * 2
        else:
            score += (1.0 - taker_ratio) * 2
        
        fear_greed = intel.get("fear_greed", 50)
        if direction == "LONG":
            score += (fear_greed - 50) / 50 * 0.3
        else:
            score += (50 - fear_greed) / 50 * 0.3
        
        return min(max(score, -1), 1)
    
    @staticmethod
    def score_volume(volume_ratio: float) -> float:
        """
        Volume score: Is there enough volume to support the move?
        volume_ratio = current volume / average volume
        Returns: 0 to 1 score (low volume = lower confidence)
        """
        if volume_ratio >= 1.5:
            return 1.0
        elif volume_ratio >= 1.0:
            return 0.7
        elif volume_ratio >= 0.5:
            return 0.4
        else:
            return 0.2
    
    @staticmethod
    def score_momentum(roc: float, direction: str) -> float:
        """
        Momentum score based on rate of change.
        Returns: -1 to +1 score
        """
        if direction == "LONG":
            return min(max(roc * 20, -1), 1)
        else:
            return min(max(-roc * 20, -1), 1)
    
    @staticmethod
    def score_session(hour: int, symbol: str) -> float:
        """
        Session score: Historical performance during this session.
        Returns: -0.5 to +0.5 adjustment
        """
        if symbol in ["BTCUSDT", "ETHUSDT"]:
            if 12 <= hour < 20:
                return 0.3
            elif 8 <= hour < 12:
                return 0.1
            else:
                return -0.1
        return 0


class ExitScorer:
    """
    Converts exit-related signals to probability contributions.
    Each signal contributes a score from 0 (hold) to 1 (exit now).
    """
    
    @staticmethod
    def score_unrealized_pnl(pnl_pct: float, target_pct: float, stop_pct: float) -> float:
        """
        How close are we to target or stop?
        Returns: 0 (hold) to 1 (exit)
        """
        if pnl_pct >= target_pct:
            return 1.0
        elif pnl_pct <= stop_pct:
            return 1.0
        elif pnl_pct > 0:
            return pnl_pct / target_pct * 0.5
        else:
            return abs(pnl_pct / stop_pct) * 0.3
    
    @staticmethod
    def score_mtf_exit(trends: Dict[str, str], position_direction: str) -> float:
        """
        Are timeframes turning against the position?
        Returns: 0 (stay) to 1 (exit)
        """
        against = 0
        total = 0
        bad_trend = "down" if position_direction == "LONG" else "up"
        
        for tf, trend in trends.items():
            total += 1
            if trend == bad_trend:
                against += 1
        
        if total == 0:
            return 0
        return against / total
    
    @staticmethod
    def score_regime_shift(entry_regime: str, current_regime: str) -> float:
        """
        Has the regime changed unfavorably?
        Returns: 0 (same/better) to 1 (worse)
        """
        regime_rank = {
            "bull_trend": 5,
            "recovery": 4,
            "stable": 3,
            "chop": 2,
            "bear_trend": 1,
            "crash": 0
        }
        entry_rank = regime_rank.get(entry_regime, 3)
        current_rank = regime_rank.get(current_regime, 3)
        
        if current_rank < entry_rank - 1:
            return min((entry_rank - current_rank) / 3, 1.0)
        return 0
    
    @staticmethod
    def score_hold_duration(hold_minutes: float, optimal_minutes: float) -> float:
        """
        Have we held long enough based on learned patterns?
        Returns: 0 (keep holding) to 1 (exit)
        """
        if optimal_minutes <= 0:
            return 0
        
        ratio = hold_minutes / optimal_minutes
        if ratio < 0.5:
            return 0
        elif ratio < 1.0:
            return (ratio - 0.5) * 0.4
        elif ratio < 2.0:
            return 0.2 + (ratio - 1.0) * 0.4
        else:
            return 0.6 + min((ratio - 2.0) * 0.2, 0.4)
    
    @staticmethod
    def score_trailing_stop(high_pct: float, current_pct: float, trail_pct: float) -> float:
        """
        Have we given back too much from the high?
        Returns: 0 (within trail) to 1 (exit)
        """
        if current_pct >= high_pct:
            return 0
        
        giveback = high_pct - current_pct
        if giveback >= trail_pct:
            return 1.0
        return giveback / trail_pct * 0.5
    
    @staticmethod
    def score_momentum_reversal(entry_momentum: float, current_momentum: float) -> float:
        """
        Has momentum reversed significantly?
        Returns: 0 (same direction) to 1 (reversed)
        """
        if entry_momentum * current_momentum > 0:
            return 0
        
        return min(abs(current_momentum - entry_momentum) / abs(entry_momentum + 0.01), 1.0)
    
    @staticmethod
    def score_volume_decline(entry_volume_ratio: float, current_volume_ratio: float) -> float:
        """
        Has volume dried up?
        Returns: 0 (good volume) to 1 (no volume)
        """
        if current_volume_ratio >= entry_volume_ratio * 0.7:
            return 0
        
        decline = (entry_volume_ratio - current_volume_ratio) / entry_volume_ratio
        return min(decline, 1.0)


class WeightedSignalFusion:
    """
    Main fusion class that combines all signals using learned weights.
    """
    
    def __init__(self):
        self.entry_weights = self._load_weights(SIGNAL_WEIGHTS_PATH, DEFAULT_ENTRY_WEIGHTS)
        self.exit_weights = self._load_weights(EXIT_WEIGHTS_PATH, DEFAULT_EXIT_WEIGHTS)
        self.entry_weights = normalize_weights(self.entry_weights)
        self.exit_weights = normalize_weights(self.exit_weights)
    
    def _load_weights(self, path: str, defaults: Dict) -> Dict:
        """Load weights from file or use defaults."""
        saved = load_json(path)
        if saved and "weights" in saved:
            return saved["weights"]
        return defaults.copy()
    
    def _save_weights(self, path: str, weights: Dict, metadata: Dict = None):
        """Save weights to file."""
        data = {
            "weights": weights,
            "updated_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        save_json(path, data)
    
    def compute_entry_probability(self, 
                                   symbol: str,
                                   direction: str,
                                   ofi: float = 0,
                                   ensemble: float = 0,
                                   mtf_trends: Dict = None,
                                   regime: str = "stable",
                                   market_intel: Dict = None,
                                   volume_ratio: float = 1.0,
                                   momentum: float = 0,
                                   hour: int = 12) -> Dict[str, Any]:
        """
        Compute weighted entry probability for a direction.
        Returns probability 0-100% and component breakdown.
        """
        mtf_trends = mtf_trends or {}
        market_intel = market_intel or {}
        
        scores = {
            "ofi": SignalScorer.score_ofi(ofi, direction),
            "ensemble": SignalScorer.score_ensemble(ensemble, direction),
            "mtf_alignment": SignalScorer.score_mtf_alignment(mtf_trends, direction),
            "regime": SignalScorer.score_regime(regime, direction),
            "market_intel": SignalScorer.score_market_intel(market_intel, direction),
            "volume": SignalScorer.score_volume(volume_ratio),
            "momentum": SignalScorer.score_momentum(momentum, direction),
            "session": SignalScorer.score_session(hour, symbol)
        }
        
        weighted_sum = 0
        for signal, score in scores.items():
            weight = self.entry_weights.get(signal, 0.1)
            weighted_sum += score * weight
        
        raw_probability = sigmoid(weighted_sum, k=2.0)
        probability_pct = raw_probability * 100
        
        contributions = {
            signal: {
                "raw_score": round(scores[signal], 3),
                "weight": round(self.entry_weights.get(signal, 0.1), 3),
                "contribution": round(scores[signal] * self.entry_weights.get(signal, 0.1), 3)
            }
            for signal in scores
        }
        
        return {
            "symbol": symbol,
            "direction": direction,
            "probability_pct": round(probability_pct, 1),
            "raw_weighted_sum": round(weighted_sum, 3),
            "contributions": contributions,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def compute_exit_probability(self,
                                  symbol: str,
                                  position_direction: str,
                                  unrealized_pnl_pct: float = 0,
                                  target_pct: float = 2.0,
                                  stop_pct: float = -1.5,
                                  mtf_trends: Dict = None,
                                  entry_regime: str = "stable",
                                  current_regime: str = "stable",
                                  hold_minutes: float = 0,
                                  optimal_hold_minutes: float = 30,
                                  high_pnl_pct: float = 0,
                                  trail_pct: float = 0.5,
                                  entry_momentum: float = 0,
                                  current_momentum: float = 0,
                                  entry_volume_ratio: float = 1.0,
                                  current_volume_ratio: float = 1.0) -> Dict[str, Any]:
        """
        Compute weighted exit probability.
        Returns probability 0-100% that we should exit.
        """
        mtf_trends = mtf_trends or {}
        
        scores = {
            "unrealized_pnl": ExitScorer.score_unrealized_pnl(unrealized_pnl_pct, target_pct, stop_pct),
            "mtf_exit_signal": ExitScorer.score_mtf_exit(mtf_trends, position_direction),
            "regime_shift": ExitScorer.score_regime_shift(entry_regime, current_regime),
            "hold_duration": ExitScorer.score_hold_duration(hold_minutes, optimal_hold_minutes),
            "trailing_stop": ExitScorer.score_trailing_stop(high_pnl_pct, unrealized_pnl_pct, trail_pct),
            "momentum_reversal": ExitScorer.score_momentum_reversal(entry_momentum, current_momentum),
            "volume_decline": ExitScorer.score_volume_decline(entry_volume_ratio, current_volume_ratio)
        }
        
        weighted_sum = 0
        for signal, score in scores.items():
            weight = self.exit_weights.get(signal, 0.1)
            weighted_sum += score * weight
        
        probability_pct = weighted_sum * 100
        
        contributions = {
            signal: {
                "raw_score": round(scores[signal], 3),
                "weight": round(self.exit_weights.get(signal, 0.1), 3),
                "contribution": round(scores[signal] * self.exit_weights.get(signal, 0.1), 3)
            }
            for signal in scores
        }
        
        return {
            "symbol": symbol,
            "position_direction": position_direction,
            "exit_probability_pct": round(min(probability_pct, 100), 1),
            "raw_weighted_sum": round(weighted_sum, 3),
            "contributions": contributions,
            "recommendation": "EXIT" if probability_pct >= 60 else ("CONSIDER_EXIT" if probability_pct >= 40 else "HOLD"),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def update_weights_from_outcome(self, 
                                     signal_type: str,
                                     signal_contributions: Dict,
                                     outcome_pnl: float,
                                     was_profitable: bool):
        """
        Adjust weights based on trade outcome.
        Signals that contributed to profitable trades get boosted.
        Signals that contributed to losing trades get reduced.
        """
        weights = self.entry_weights if signal_type == "entry" else self.exit_weights
        path = SIGNAL_WEIGHTS_PATH if signal_type == "entry" else EXIT_WEIGHTS_PATH
        
        for signal, contrib_data in signal_contributions.items():
            if signal not in weights:
                continue
            
            contribution = contrib_data.get("contribution", 0)
            
            if was_profitable:
                if contribution > 0:
                    weights[signal] = min(weights[signal] * (1 + WEIGHT_ADJUSTMENT_RATE), MAX_WEIGHT)
                elif contribution < 0:
                    weights[signal] = max(weights[signal] * (1 - WEIGHT_ADJUSTMENT_RATE * 0.5), MIN_WEIGHT)
            else:
                if contribution > 0:
                    weights[signal] = max(weights[signal] * (1 - WEIGHT_ADJUSTMENT_RATE), MIN_WEIGHT)
                elif contribution < 0:
                    weights[signal] = min(weights[signal] * (1 + WEIGHT_ADJUSTMENT_RATE * 0.5), MAX_WEIGHT)
        
        weights = normalize_weights(weights)
        
        if signal_type == "entry":
            self.entry_weights = weights
        else:
            self.exit_weights = weights
        
        self._save_weights(path, weights, {
            "last_update_pnl": outcome_pnl,
            "last_update_profitable": was_profitable
        })
        
        append_jsonl(FUSION_HISTORY_PATH, {
            "timestamp": datetime.utcnow().isoformat(),
            "signal_type": signal_type,
            "weights": weights,
            "outcome_pnl": outcome_pnl,
            "was_profitable": was_profitable
        })
    
    def get_best_direction(self, symbol: str, **signal_data) -> Dict[str, Any]:
        """
        Compare LONG vs SHORT probabilities and return the better direction.
        """
        long_result = self.compute_entry_probability(symbol, "LONG", **signal_data)
        short_result = self.compute_entry_probability(symbol, "SHORT", **signal_data)
        
        long_prob = long_result["probability_pct"]
        short_prob = short_result["probability_pct"]
        
        if long_prob > short_prob:
            best = "LONG"
            confidence = long_prob
            margin = long_prob - short_prob
        else:
            best = "SHORT"
            confidence = short_prob
            margin = short_prob - long_prob
        
        return {
            "symbol": symbol,
            "best_direction": best,
            "confidence_pct": round(confidence, 1),
            "margin_pct": round(margin, 1),
            "long_probability_pct": round(long_prob, 1),
            "short_probability_pct": round(short_prob, 1),
            "should_trade": margin >= 10 and confidence >= 55,
            "long_breakdown": long_result["contributions"],
            "short_breakdown": short_result["contributions"],
            "timestamp": datetime.utcnow().isoformat()
        }


def learn_weights_from_history(min_trades: int = 50, min_hours: int = 48) -> Dict[str, Any]:
    """
    Learn optimal weights from historical trades.
    Only updates if we have enough data (50+ trades, 48+ hours).
    """
    from src.complete_feedback_loop import load_jsonl as load_jl
    
    timing_data = load_jl(str(DR.POSITION_TIMING_PATH))
    enriched = load_jl(str(DR.ENRICHED_DECISIONS_PATH))
    
    if len(timing_data) < min_trades:
        return {
            "status": "skipped",
            "reason": f"need {min_trades}+ trades, have {len(timing_data)}",
            "trades": len(timing_data)
        }
    
    if len(timing_data) >= 2:
        timestamps = []
        for t in timing_data:
            ts = t.get("entry_timestamp") or t.get("exit_timestamp")
            if ts:
                try:
                    timestamps.append(datetime.fromisoformat(ts.replace('Z', '+00:00')))
                except:
                    pass
        
        if len(timestamps) >= 2:
            span_hours = (max(timestamps) - min(timestamps)).total_seconds() / 3600
            if span_hours < min_hours:
                return {
                    "status": "skipped",
                    "reason": f"need {min_hours}h+ of data, have {span_hours:.1f}h",
                    "hours": span_hours
                }
    
    signal_performance = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0})
    
    for trade in enriched:
        pnl = trade.get("pnl_usd", 0)
        was_win = pnl > 0
        
        ofi = abs(trade.get("ofi_at_entry", 0))
        ensemble = trade.get("ensemble_at_entry", 0)
        
        if ofi > 0.3:
            if was_win:
                signal_performance["ofi"]["wins"] += 1
            else:
                signal_performance["ofi"]["losses"] += 1
            signal_performance["ofi"]["total_pnl"] += pnl
        
        if abs(ensemble) > 0.03:
            if was_win:
                signal_performance["ensemble"]["wins"] += 1
            else:
                signal_performance["ensemble"]["losses"] += 1
            signal_performance["ensemble"]["total_pnl"] += pnl
    
    fusion = WeightedSignalFusion()
    new_weights = fusion.entry_weights.copy()
    
    for signal, perf in signal_performance.items():
        total = perf["wins"] + perf["losses"]
        if total >= 20:
            win_rate = perf["wins"] / total
            if win_rate > 0.5:
                new_weights[signal] = min(new_weights.get(signal, 0.1) * 1.1, MAX_WEIGHT)
            elif win_rate < 0.4:
                new_weights[signal] = max(new_weights.get(signal, 0.1) * 0.9, MIN_WEIGHT)
    
    new_weights = normalize_weights(new_weights)
    
    save_json(SIGNAL_WEIGHTS_PATH, {
        "weights": new_weights,
        "updated_at": datetime.utcnow().isoformat(),
        "metadata": {
            "trades_analyzed": len(enriched),
            "signal_performance": dict(signal_performance)
        }
    })
    
    return {
        "status": "updated",
        "trades_analyzed": len(enriched),
        "new_weights": new_weights
    }


def get_fusion_instance() -> WeightedSignalFusion:
    """Get singleton instance of WeightedSignalFusion."""
    return WeightedSignalFusion()


if __name__ == "__main__":
    print("=" * 60)
    print("WEIGHTED SIGNAL FUSION SYSTEM")
    print("=" * 60)
    
    fusion = WeightedSignalFusion()
    
    print("\n📊 Current Entry Weights:")
    for signal, weight in sorted(fusion.entry_weights.items(), key=lambda x: -x[1]):
        print(f"   {signal:20s}: {weight:.3f}")
    
    print("\n📊 Current Exit Weights:")
    for signal, weight in sorted(fusion.exit_weights.items(), key=lambda x: -x[1]):
        print(f"   {signal:20s}: {weight:.3f}")
    
    print("\n🔬 Example Entry Calculation (BTCUSDT LONG):")
    result = fusion.compute_entry_probability(
        symbol="BTCUSDT",
        direction="LONG",
        ofi=0.4,
        ensemble=0.05,
        mtf_trends={"1m": "up", "5m": "up", "15m": "neutral", "1h": "up"},
        regime="stable",
        market_intel={"taker_buy_sell_ratio": 1.15, "fear_greed": 45},
        volume_ratio=1.3,
        momentum=0.02,
        hour=14
    )
    
    print(f"   Probability: {result['probability_pct']}%")
    print(f"   Contributions:")
    for signal, data in result["contributions"].items():
        print(f"      {signal:15s}: score={data['raw_score']:+.2f} × weight={data['weight']:.2f} = {data['contribution']:+.3f}")
    
    print("\n🔬 Example Exit Calculation:")
    exit_result = fusion.compute_exit_probability(
        symbol="BTCUSDT",
        position_direction="LONG",
        unrealized_pnl_pct=1.2,
        target_pct=2.5,
        stop_pct=-1.5,
        mtf_trends={"1m": "down", "5m": "up", "15m": "up", "1h": "up"},
        hold_minutes=25,
        optimal_hold_minutes=45,
        high_pnl_pct=1.8,
        trail_pct=0.5
    )
    
    print(f"   Exit Probability: {exit_result['exit_probability_pct']}%")
    print(f"   Recommendation: {exit_result['recommendation']}")
    
    print("\n🎯 Best Direction Analysis:")
    best = fusion.get_best_direction(
        symbol="BTCUSDT",
        ofi=0.4,
        ensemble=0.05,
        mtf_trends={"1m": "up", "5m": "up", "15m": "neutral", "1h": "up"},
        regime="stable",
        market_intel={"taker_buy_sell_ratio": 1.15},
        volume_ratio=1.3,
        momentum=0.02,
        hour=14
    )
    print(f"   Best: {best['best_direction']} ({best['confidence_pct']}%)")
    print(f"   LONG: {best['long_probability_pct']}%  |  SHORT: {best['short_probability_pct']}%")
    print(f"   Should Trade: {best['should_trade']}")
