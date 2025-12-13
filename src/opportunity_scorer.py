"""
REAL-TIME OPPORTUNITY SCORER
============================
Scores trading opportunities by EXPECTED PROFIT based on historical patterns.

This is the core of the profit-seeking approach:
- Instead of "should we block this?", answer "what's the expected profit?"
- Use multiple dimensions: symbol, direction, time, duration potential
- Provide actionable scoring for the alpha entry flow

TIME-OF-DAY WEIGHTING (Phase 15.0):
- Weight opportunities by hour performance (08:00 UTC = best = +$41.72 at 61.5% WR)
- Block trading during worst hours (configurable via avoid_hours_utc)
- Boost sizing during proven profitable hours (best_hours_utc)

Author: Trading Bot System  
Date: December 2025
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional, Tuple, Any, List

FEATURE_STORE = "feature_store"
CONFIG_DIR = "configs"
BACKTEST_RESULTS_PATH = os.path.join(FEATURE_STORE, "backtest_results.json")

DEFAULT_BEST_HOURS_UTC = [8, 9, 10, 14, 15]
DEFAULT_WORST_HOURS_UTC = [3, 4, 5, 22, 23]
DEFAULT_HOUR_BOOST = 1.25
DEFAULT_HOUR_PENALTY = 0.5


class TimeOfDayWeightingConfig:
    """Configuration for time-of-day weighting system."""
    
    def __init__(self):
        self.enabled = True
        self.best_hours_utc: List[int] = DEFAULT_BEST_HOURS_UTC.copy()
        self.worst_hours_utc: List[int] = DEFAULT_WORST_HOURS_UTC.copy()
        self.block_worst_hours = False  # Don't block - use coin preference instead
        self.best_hour_boost = DEFAULT_HOUR_BOOST
        self.worst_hour_penalty = DEFAULT_HOUR_PENALTY
        self._load_from_backtest()
    
    def _load_from_backtest(self):
        """Load optimal settings from backtest results if available."""
        try:
            if os.path.exists(BACKTEST_RESULTS_PATH):
                with open(BACKTEST_RESULTS_PATH, 'r') as f:
                    data = json.load(f)
                optimal = data.get("optimal_settings", {})
                if optimal.get("best_hours_utc"):
                    self.best_hours_utc = optimal["best_hours_utc"]
                if optimal.get("worst_hours_utc"):
                    self.worst_hours_utc = optimal["worst_hours_utc"]
        except:
            pass


class OpportunityScorer:
    """
    Real-time opportunity scoring based on profit-seeking analysis.
    
    Provides expected edge scores for trading decisions.
    Includes Time-of-Day Weighting for hour-based performance optimization.
    """
    
    def __init__(self):
        self.momentum_data = None
        self.alpha_config = None
        self.symbol_direction_scores = {}
        self.hour_scores = {}
        self.duration_scores = {}
        self.tod_config = TimeOfDayWeightingConfig()
        self._load_data()
    
    def _load_data(self):
        """Load analysis data and config."""
        momentum_path = os.path.join(FEATURE_STORE, "momentum_analysis.json")
        if os.path.exists(momentum_path):
            try:
                with open(momentum_path, 'r') as f:
                    self.momentum_data = json.load(f)
                self._build_score_tables()
            except:
                pass
        
        alpha_path = os.path.join(CONFIG_DIR, "alpha_config.json")
        if os.path.exists(alpha_path):
            try:
                with open(alpha_path, 'r') as f:
                    self.alpha_config = json.load(f)
            except:
                pass
    
    def _build_score_tables(self):
        """Build lookup tables for fast scoring."""
        if not self.momentum_data:
            return
        
        sd_data = self.momentum_data.get("by_symbol_direction", {})
        for key, stats in sd_data.items():
            if stats.get("trades", 0) >= 5:
                wr = stats.get("win_rate", 0) / 100
                avg_pnl = stats.get("avg_pnl", 0)
                self.symbol_direction_scores[key] = {
                    "win_rate": wr,
                    "avg_pnl": avg_pnl,
                    "edge": wr * avg_pnl if avg_pnl > 0 else avg_pnl * (1 - wr),
                    "trades": stats.get("trades", 0),
                    "profitable": stats.get("profitable", False),
                    "trend": stats.get("trend", "unknown")
                }
        
        hour_data = self.momentum_data.get("by_hour", {})
        for hour, stats in hour_data.items():
            if stats.get("trades", 0) >= 5:
                wr = stats.get("win_rate", 0) / 100
                avg_pnl = stats.get("avg_pnl", 0)
                self.hour_scores[hour] = {
                    "win_rate": wr,
                    "avg_pnl": avg_pnl,
                    "edge": wr * avg_pnl if avg_pnl > 0 else avg_pnl * (1 - wr),
                    "profitable": stats.get("profitable", False)
                }
        
        dur_data = self.momentum_data.get("by_duration", {})
        for dur, stats in dur_data.items():
            if stats.get("trades", 0) >= 10:
                wr = stats.get("win_rate", 0) / 100
                avg_pnl = stats.get("avg_pnl", 0)
                self.duration_scores[dur] = {
                    "win_rate": wr,
                    "avg_pnl": avg_pnl,
                    "edge": wr * avg_pnl if avg_pnl > 0 else avg_pnl * (1 - wr),
                    "profitable": stats.get("profitable", False)
                }
    
    def score_opportunity(self, symbol: str, side: str, 
                         ofi: float = 0.5, ensemble: float = 0.0,
                         current_hour: Optional[int] = None) -> Dict[str, Any]:
        """
        Score a trading opportunity by expected profit.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            side: Direction ("LONG" or "SHORT")
            ofi: OFI confidence value
            ensemble: Ensemble score
            current_hour: Current hour UTC (auto-detected if None)
        
        Returns:
            Dictionary with:
            - expected_edge: Predicted profit/loss per trade
            - win_probability: Estimated win rate
            - recommendation: "STRONG_BUY", "BUY", "NEUTRAL", "AVOID"
            - confidence: How confident in this prediction (0-1)
            - reasoning: List of factors considered
            - should_trade: Boolean - True if expected_edge > 0
        """
        if current_hour is None:
            current_hour = datetime.utcnow().hour
        
        scores = []
        reasoning = []
        
        sd_key = f"{symbol}|{side.upper()}"
        sd_data = self.symbol_direction_scores.get(sd_key)
        
        if sd_data:
            edge = sd_data["edge"]
            scores.append(("symbol_direction", edge, 0.4))
            
            wr_pct = sd_data["win_rate"] * 100
            trend_icon = "↑" if sd_data["trend"] == "improving" else "↓"
            profitable_marker = "***PROFITABLE***" if sd_data["profitable"] else ""
            
            reasoning.append(f"{sd_key}: {wr_pct:.0f}% WR, ${sd_data['avg_pnl']:.2f} avg, {sd_data['trades']} trades {trend_icon} {profitable_marker}")
        else:
            scores.append(("symbol_direction", 0, 0.4))
            reasoning.append(f"{sd_key}: No historical data")
        
        hour_key = f"{current_hour:02d}:00"
        hour_data = self.hour_scores.get(hour_key)
        
        if hour_data:
            edge = hour_data["edge"]
            scores.append(("time_of_day", edge, 0.2))
            
            wr_pct = hour_data["win_rate"] * 100
            profitable_marker = "***GOOD HOUR***" if hour_data["profitable"] else ""
            
            reasoning.append(f"Hour {hour_key}: {wr_pct:.0f}% WR, ${hour_data['avg_pnl']:.2f} avg {profitable_marker}")
        else:
            scores.append(("time_of_day", 0, 0.2))
        
        duration_sweet_spot = self.duration_scores.get("30-60min", {})
        if duration_sweet_spot and duration_sweet_spot.get("profitable"):
            edge = duration_sweet_spot["edge"]
            scores.append(("duration_potential", edge, 0.3))
            
            wr_pct = duration_sweet_spot["win_rate"] * 100
            reasoning.append(f"Target hold 30-60min: {wr_pct:.0f}% WR ***SWEET SPOT***")
        else:
            scores.append(("duration_potential", 0, 0.3))
        
        winning_patterns = []
        if self.alpha_config:
            ps_rules = self.alpha_config.get("profit_seeking_rules", {})
            patterns = ps_rules.get("winning_patterns", {}).get("top_performers", [])
            
            for p in patterns:
                if p.get("symbol") == symbol and p.get("side") == side.upper():
                    winning_patterns.append(p)
        
        if winning_patterns:
            best = winning_patterns[0]
            scores.append(("pattern_match", best["avg_pnl"] * 0.5, 0.1))
            reasoning.append(f"TOP WINNER PATTERN: ${best['avg_pnl']:.2f} avg, hold ~{best['avg_hold_min']}min")
        else:
            scores.append(("pattern_match", 0, 0.1))
        
        total_weight = sum(w for _, _, w in scores)
        expected_edge = sum(score * weight for _, score, weight in scores) / total_weight if total_weight > 0 else 0
        
        valid_scores = [s for _, s, _ in scores if s != 0]
        confidence = len(valid_scores) / len(scores) if scores else 0
        
        win_prob = 0.5
        if sd_data:
            win_prob = sd_data["win_rate"]
        
        if expected_edge > 1.0 and confidence >= 0.5:
            recommendation = "STRONG_BUY"
        elif expected_edge > 0.2:
            recommendation = "BUY"
        elif expected_edge > -0.2:
            recommendation = "NEUTRAL"
        else:
            recommendation = "AVOID"
        
        should_trade = expected_edge > 0 or recommendation in ["STRONG_BUY", "BUY"]
        
        if winning_patterns:
            should_trade = True
            if recommendation not in ["STRONG_BUY", "BUY"]:
                recommendation = "BUY"
        
        return {
            "expected_edge": round(expected_edge, 4),
            "win_probability": round(win_prob, 3),
            "recommendation": recommendation,
            "confidence": round(confidence, 2),
            "reasoning": reasoning,
            "should_trade": should_trade,
            "symbol": symbol,
            "side": side.upper(),
            "hour": current_hour,
            "is_winning_pattern": len(winning_patterns) > 0,
            "components": {name: round(score, 4) for name, score, _ in scores}
        }
    
    def get_best_opportunities(self) -> list:
        """
        Get all positive-edge opportunities based on current time.
        
        Returns list of symbol-direction combos ranked by expected edge.
        """
        current_hour = datetime.utcnow().hour
        
        opportunities = []
        
        for sd_key, data in self.symbol_direction_scores.items():
            parts = sd_key.split("|")
            if len(parts) != 2:
                continue
            
            symbol, side = parts
            score = self.score_opportunity(symbol, side, current_hour=current_hour)
            
            if score["expected_edge"] > 0 or score["is_winning_pattern"]:
                opportunities.append({
                    "symbol": symbol,
                    "side": side,
                    "expected_edge": score["expected_edge"],
                    "win_probability": score["win_probability"],
                    "recommendation": score["recommendation"],
                    "is_winning_pattern": score["is_winning_pattern"]
                })
        
        opportunities.sort(key=lambda x: x["expected_edge"], reverse=True)
        
        return opportunities
    
    def check_time_filter(self, current_hour: Optional[int] = None) -> Tuple[bool, str]:
        """
        Check if current time is good for trading.
        
        Returns:
            (is_good_time, reason)
        """
        if current_hour is None:
            current_hour = datetime.utcnow().hour
        
        if not self.alpha_config:
            return True, "No config loaded"
        
        ps_rules = self.alpha_config.get("profit_seeking_rules", {})
        tod_rules = ps_rules.get("time_of_day", {})
        
        if not tod_rules.get("enabled", False):
            return True, "Time filter disabled"
        
        avoid_hours = tod_rules.get("avoid_hours_utc", [])
        if current_hour in avoid_hours:
            return False, f"Hour {current_hour}:00 UTC is in avoid list (high loss hours)"
        
        best_hours = tod_rules.get("best_hours_utc", [])
        if current_hour in best_hours:
            return True, f"Hour {current_hour}:00 UTC is a BEST trading hour!"
        
        return True, f"Hour {current_hour}:00 UTC is acceptable"
    
    def get_minimum_hold_time(self) -> int:
        """Get recommended minimum hold time in minutes."""
        if not self.alpha_config:
            return 30
        
        ps_rules = self.alpha_config.get("profit_seeking_rules", {})
        dur_rules = ps_rules.get("duration_rules", {})
        
        return dur_rules.get("min_hold_minutes", 30)
    
    def get_time_of_day_weight(self, hour: Optional[int] = None) -> Tuple[float, str, bool]:
        """
        Get time-of-day weighting for the current or specified hour.
        
        Returns:
            (size_multiplier, reason, should_trade)
            - size_multiplier: Boost or penalty factor (1.0 = normal)
            - reason: Human-readable explanation
            - should_trade: False if trading should be blocked
        
        KEY DATA: 08:00 UTC = +$41.72 profit at 61.5% WR (BEST HOUR)
        """
        if hour is None:
            hour = datetime.utcnow().hour
        
        if not self.tod_config.enabled:
            return 1.0, "time_weighting_disabled", True
        
        if hour in self.tod_config.best_hours_utc:
            return self.tod_config.best_hour_boost, f"BEST_HOUR:{hour:02d}:00_UTC", True
        
        if hour in self.tod_config.worst_hours_utc:
            if self.tod_config.block_worst_hours:
                return 0.0, f"BLOCKED_WORST_HOUR:{hour:02d}:00_UTC", False
            else:
                return self.tod_config.worst_hour_penalty, f"WORST_HOUR:{hour:02d}:00_UTC", True
        
        return 1.0, f"NORMAL_HOUR:{hour:02d}:00_UTC", True
    
    def should_block_hour(self, hour: Optional[int] = None) -> Tuple[bool, str]:
        """
        Check if trading should be blocked for the current hour.
        
        Returns:
            (should_block, reason)
        """
        if hour is None:
            hour = datetime.utcnow().hour
        
        if not self.tod_config.enabled:
            return False, "time_weighting_disabled"
        
        if hour in self.tod_config.worst_hours_utc and self.tod_config.block_worst_hours:
            return True, f"Hour {hour:02d}:00 UTC is a historically unprofitable hour"
        
        return False, f"Hour {hour:02d}:00 UTC is acceptable"
    
    def get_sizing_boost(self, symbol: str, side: str, 
                         ofi: float = 0.5, 
                         current_hour: Optional[int] = None) -> Tuple[float, str]:
        """
        Get combined sizing boost from all factors.
        
        Returns:
            (total_multiplier, reason)
        
        Factors:
        1. Time-of-day weighting (best hours get boost)
        2. Pattern performance (winning patterns get boost)
        3. Symbol-direction historical performance
        """
        if current_hour is None:
            current_hour = datetime.utcnow().hour
        
        multipliers = []
        reasons = []
        
        tod_mult, tod_reason, can_trade = self.get_time_of_day_weight(current_hour)
        if not can_trade:
            return 0.0, f"BLOCKED: {tod_reason}"
        
        if tod_mult != 1.0:
            multipliers.append(tod_mult)
            reasons.append(f"time:{tod_mult:.2f}x")
        
        sd_key = f"{symbol}|{side.upper()}"
        sd_data = self.symbol_direction_scores.get(sd_key)
        if sd_data and sd_data.get("profitable"):
            wr = sd_data.get("win_rate", 0.5)
            if wr > 0.6:
                pattern_boost = min(1.5, 1 + (wr - 0.5))
                multipliers.append(pattern_boost)
                reasons.append(f"pattern:{pattern_boost:.2f}x")
        
        if not multipliers:
            return 1.0, "no_boosts"
        
        total = 1.0
        for m in multipliers:
            total *= m
        
        total = min(2.0, max(0.5, total))
        
        return round(total, 2), "+".join(reasons) if reasons else "normal"


_scorer_instance = None

def get_scorer() -> OpportunityScorer:
    """Get singleton scorer instance."""
    global _scorer_instance
    if _scorer_instance is None:
        _scorer_instance = OpportunityScorer()
    return _scorer_instance


def score_opportunity(symbol: str, side: str, ofi: float = 0.5, 
                     ensemble: float = 0.0, current_hour: Optional[int] = None) -> Dict[str, Any]:
    """
    Convenience function to score an opportunity.
    
    Usage:
        from src.opportunity_scorer import score_opportunity
        result = score_opportunity("BTCUSDT", "SHORT", ofi=0.7)
        if result["should_trade"]:
            # Execute trade
    """
    scorer = get_scorer()
    return scorer.score_opportunity(symbol, side, ofi, ensemble, current_hour)


def check_time_filter(current_hour: Optional[int] = None) -> Tuple[bool, str]:
    """Check if current time is good for trading."""
    scorer = get_scorer()
    return scorer.check_time_filter(current_hour)


def get_best_opportunities() -> list:
    """Get ranked list of positive-edge opportunities."""
    scorer = get_scorer()
    return scorer.get_best_opportunities()


def get_time_of_day_weight(hour: Optional[int] = None) -> Tuple[float, str, bool]:
    """
    Get time-of-day weighting for the current or specified hour.
    
    Returns:
        (size_multiplier, reason, should_trade)
    
    Usage:
        from src.opportunity_scorer import get_time_of_day_weight
        mult, reason, can_trade = get_time_of_day_weight()
        if not can_trade:
            print(f"Trading blocked: {reason}")
            return
        adjusted_size = base_size * mult
    """
    scorer = get_scorer()
    return scorer.get_time_of_day_weight(hour)


def should_block_hour(hour: Optional[int] = None) -> Tuple[bool, str]:
    """
    Check if trading should be blocked for the current hour.
    
    Returns:
        (should_block, reason)
    """
    scorer = get_scorer()
    return scorer.should_block_hour(hour)


def get_sizing_boost(symbol: str, side: str, ofi: float = 0.5, 
                     current_hour: Optional[int] = None) -> Tuple[float, str]:
    """
    Get combined sizing boost from all factors (time + pattern).
    
    Returns:
        (total_multiplier, reason)
    
    Usage:
        from src.opportunity_scorer import get_sizing_boost
        boost, reason = get_sizing_boost("DOTUSDT", "SHORT", ofi=0.8)
        final_size = base_size * boost
    """
    scorer = get_scorer()
    return scorer.get_sizing_boost(symbol, side, ofi, current_hour)


if __name__ == "__main__":
    print("=" * 70)
    print("OPPORTUNITY SCORER TEST")
    print("=" * 70)
    
    scorer = OpportunityScorer()
    
    print("\nLoaded data:")
    print(f"  Symbol-Direction scores: {len(scorer.symbol_direction_scores)}")
    print(f"  Hour scores: {len(scorer.hour_scores)}")
    print(f"  Duration scores: {len(scorer.duration_scores)}")
    
    print("\n" + "=" * 70)
    print("TESTING TOP WINNER PATTERNS:")
    print("=" * 70)
    
    test_cases = [
        ("DOTUSDT", "SHORT"),
        ("ADAUSDT", "SHORT"),
        ("BNBUSDT", "SHORT"),
        ("SOLUSDT", "SHORT"),
        ("XRPUSDT", "SHORT"),
        ("BTCUSDT", "LONG"),
        ("ETHUSDT", "SHORT"),
    ]
    
    for symbol, side in test_cases:
        result = scorer.score_opportunity(symbol, side)
        
        print(f"\n{symbol} {side}:")
        print(f"  Expected Edge: ${result['expected_edge']:.4f}")
        print(f"  Win Probability: {result['win_probability']*100:.1f}%")
        print(f"  Recommendation: {result['recommendation']}")
        print(f"  Should Trade: {result['should_trade']}")
        print(f"  Is Winning Pattern: {result['is_winning_pattern']}")
        print("  Reasoning:")
        for r in result['reasoning']:
            print(f"    - {r}")
    
    print("\n" + "=" * 70)
    print("CURRENT BEST OPPORTUNITIES:")
    print("=" * 70)
    
    opps = scorer.get_best_opportunities()
    for i, opp in enumerate(opps[:10], 1):
        pattern_marker = "***TOP PATTERN***" if opp["is_winning_pattern"] else ""
        print(f"  #{i}: {opp['symbol']} {opp['side']} | Edge: ${opp['expected_edge']:.4f} | WR: {opp['win_probability']*100:.0f}% | {opp['recommendation']} {pattern_marker}")
    
    print("\n" + "=" * 70)
    print("TIME FILTER CHECK:")
    print("=" * 70)
    
    is_good, reason = scorer.check_time_filter()
    print(f"  Current time good: {is_good}")
    print(f"  Reason: {reason}")
    print(f"  Minimum hold time: {scorer.get_minimum_hold_time()} minutes")
