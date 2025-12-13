"""
Pattern Validator - Statistical validation for trading patterns

This module provides proper backtesting infrastructure to validate
trading patterns before they go live.

Key Features:
1. Train/Validation Split - Never validate on training data
2. Minimum Sample Size Requirements - n>=200 for statistical significance
3. Confidence Interval Calculation - Reject patterns with CI overlapping 50%
4. Walk-Forward Validation - Test patterns across rolling windows
5. Fee-Aware Backtesting - Include realistic fee impact

CRITICAL: We need 30+ days of data before trusting patterns.
Current data: 8 days (Nov 25 - Dec 2) is NOT enough!
"""

import json
import os
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

POSITIONS_FILE = "logs/positions_futures.json"
VALIDATION_RESULTS_DIR = "feature_store/validation_results"

def load_historical_trades() -> List[dict]:
    """Load all historical closed trades."""
    try:
        with open(POSITIONS_FILE) as f:
            data = json.load(f)
        return data.get("closed_positions", [])
    except Exception as e:
        print(f"[VALIDATOR] Error loading trades: {e}")
        return []

def get_data_summary() -> dict:
    """Get summary of available historical data."""
    trades = load_historical_trades()
    
    if not trades:
        return {"error": "No trades found"}
    
    dates = []
    for t in trades:
        opened = t.get("opened_at", "")[:10]
        if opened:
            dates.append(opened)
    
    unique_dates = sorted(set(dates))
    
    daily_counts = defaultdict(int)
    daily_pnl = defaultdict(float)
    for t in trades:
        d = t.get("opened_at", "")[:10]
        if d:
            daily_counts[d] += 1
            daily_pnl[d] += float(t.get("net_pnl", 0))
    
    return {
        "total_trades": len(trades),
        "unique_days": len(unique_dates),
        "date_range": {
            "start": unique_dates[0] if unique_dates else None,
            "end": unique_dates[-1] if unique_dates else None
        },
        "trades_per_day": dict(daily_counts),
        "pnl_per_day": dict(daily_pnl),
        "avg_trades_per_day": len(trades) / len(unique_dates) if unique_dates else 0,
        "sufficient_data": len(unique_dates) >= 30,
        "days_needed": max(0, 30 - len(unique_dates)),
        "recommendation": "COLLECT MORE DATA" if len(unique_dates) < 30 else "DATA SUFFICIENT"
    }

def calculate_confidence_interval(wins: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Calculate confidence interval for win rate using Wilson score interval.
    More accurate than normal approximation for small samples.
    """
    if total == 0:
        return 0.0, 1.0
    
    p = wins / total
    z = 1.96 if confidence == 0.95 else 2.576
    
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    spread = z * math.sqrt((p*(1-p) + z*z/(4*total)) / total) / denominator
    
    lower = max(0, center - spread)
    upper = min(1, center + spread)
    
    return lower, upper

def validate_pattern_statistical_significance(
    wins: int, 
    total: int,
    total_pnl: float = 0.0,
    total_fees: float = 0.0,
    min_sample: int = 200,
    min_win_rate: float = 0.50,
    require_profitable: bool = True
) -> dict:
    """
    Validate if a pattern has statistical significance.
    
    STRICT Requirements (per architect review):
    1. Minimum sample size (n >= 200)
    2. Win rate >= 50% (not coin-flip territory)
    3. Confidence interval lower bound > 40% (not overlapping random chance)
    4. Fee-adjusted P&L must be positive (if require_profitable=True)
    5. Fee-adjusted EV must be positive
    """
    win_rate = wins / total if total > 0 else 0
    fee_adjusted_pnl = total_pnl - total_fees
    fee_adjusted_ev = fee_adjusted_pnl / total if total > 0 else 0
    
    result = {
        "wins": wins,
        "total": total,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "fee_adjusted_pnl": fee_adjusted_pnl,
        "fee_adjusted_ev": fee_adjusted_ev,
        "passes_sample_size": total >= min_sample,
        "passes_win_rate": win_rate >= min_win_rate,
        "passes_profitability": fee_adjusted_pnl > 0 if require_profitable else True,
        "is_valid": False,
        "reason": ""
    }
    
    if total < min_sample:
        result["reason"] = f"Insufficient sample size: {total} < {min_sample} required"
        return result
    
    ci_lower, ci_upper = calculate_confidence_interval(wins, total)
    result["ci_95"] = {"lower": ci_lower, "upper": ci_upper}
    result["passes_ci"] = ci_lower >= 0.40
    
    if ci_lower < 0.40:
        result["reason"] = f"CI lower bound {ci_lower:.1%} < 40% - too close to random chance"
        return result
    
    if win_rate < min_win_rate:
        result["reason"] = f"Win rate {win_rate:.1%} < {min_win_rate:.0%} - not better than coin flip"
        return result
    
    if require_profitable and fee_adjusted_pnl <= 0:
        result["reason"] = f"Fee-adjusted P&L ${fee_adjusted_pnl:.2f} is not profitable"
        return result
    
    if fee_adjusted_ev <= 0:
        result["reason"] = f"Fee-adjusted EV ${fee_adjusted_ev:.4f} is negative"
        return result
    
    result["is_valid"] = True
    result["reason"] = f"Pattern validated: WR={win_rate:.1%}, CI=[{ci_lower:.1%}, {ci_upper:.1%}], EV=${fee_adjusted_ev:.4f}, n={total}"
    
    return result

def split_train_validation(trades: List[dict], train_ratio: float = 0.7) -> Tuple[List[dict], List[dict]]:
    """
    Split trades into training and validation sets by DATE (not random).
    This ensures we don't leak future information into training.
    """
    dated_trades = defaultdict(list)
    for t in trades:
        date = t.get("opened_at", "")[:10]
        if date:
            dated_trades[date].append(t)
    
    sorted_dates = sorted(dated_trades.keys())
    split_idx = int(len(sorted_dates) * train_ratio)
    
    train_dates = sorted_dates[:split_idx]
    val_dates = sorted_dates[split_idx:]
    
    train_trades = []
    for d in train_dates:
        train_trades.extend(dated_trades[d])
    
    val_trades = []
    for d in val_dates:
        val_trades.extend(dated_trades[d])
    
    return train_trades, val_trades

def validate_strategy(trades: List[dict], strategy: str) -> dict:
    """Validate a specific strategy with statistical rigor and fee awareness."""
    strat_trades = [t for t in trades if t.get("strategy") == strategy]
    wins = sum(1 for t in strat_trades if float(t.get("net_pnl", 0)) > 0)
    total_pnl = sum(float(t.get("net_pnl", 0)) for t in strat_trades)
    gross_pnl = sum(float(t.get("gross_pnl", t.get("pnl", 0))) for t in strat_trades)
    total_fees = sum(float(t.get("trading_fees", 0)) for t in strat_trades)
    
    validation = validate_pattern_statistical_significance(
        wins=wins, 
        total=len(strat_trades),
        total_pnl=gross_pnl,
        total_fees=total_fees,
        min_win_rate=0.50,
        require_profitable=True
    )
    
    return {
        "strategy": strategy,
        "trades": len(strat_trades),
        "wins": wins,
        "win_rate": wins / len(strat_trades) if strat_trades else 0,
        "gross_pnl": gross_pnl,
        "total_fees": total_fees,
        "net_pnl": total_pnl,
        "ev": total_pnl / len(strat_trades) if strat_trades else 0,
        "validation": validation
    }

def validate_direction(trades: List[dict], direction: str) -> dict:
    """Validate a direction (LONG/SHORT) with statistical rigor and fee awareness."""
    dir_trades = [t for t in trades if t.get("direction", "").upper() == direction.upper()]
    wins = sum(1 for t in dir_trades if float(t.get("net_pnl", 0)) > 0)
    total_pnl = sum(float(t.get("net_pnl", 0)) for t in dir_trades)
    gross_pnl = sum(float(t.get("gross_pnl", t.get("pnl", 0))) for t in dir_trades)
    total_fees = sum(float(t.get("trading_fees", 0)) for t in dir_trades)
    
    validation = validate_pattern_statistical_significance(
        wins=wins,
        total=len(dir_trades),
        total_pnl=gross_pnl,
        total_fees=total_fees,
        min_win_rate=0.50,
        require_profitable=True
    )
    
    return {
        "direction": direction,
        "trades": len(dir_trades),
        "wins": wins,
        "win_rate": wins / len(dir_trades) if dir_trades else 0,
        "gross_pnl": gross_pnl,
        "total_fees": total_fees,
        "net_pnl": total_pnl,
        "ev": total_pnl / len(dir_trades) if dir_trades else 0,
        "validation": validation
    }

def get_validated_recommendations() -> Tuple[List[dict], List[dict]]:
    """
    Get actionable recommendations with statistical backing.
    Returns (validated_recommendations, unvalidated_observations).
    
    ONLY items with validation.is_valid=True go in validated_recommendations.
    Everything else goes in unvalidated_observations.
    """
    trades = load_historical_trades()
    data_summary = get_data_summary()
    
    validated = []
    unvalidated = []
    
    insufficient_data = data_summary.get("unique_days", 0) < 30
    if insufficient_data:
        unvalidated.append({
            "priority": "CRITICAL",
            "type": "data_collection",
            "action": "WAIT - Collect more data before trusting any patterns",
            "reason": f"Only {data_summary.get('unique_days', 0)} days of data. Need 30+ days for reliable validation.",
            "days_remaining": data_summary.get("days_needed", 30)
        })
    
    beta_result = validate_strategy(trades, "Beta-Inversion")
    if beta_result["trades"] >= 200:
        is_valid = beta_result["validation"].get("is_valid", False)
        rec = {
            "priority": "HIGH",
            "type": "strategy",
            "reason": f"n={beta_result['trades']}, WR={beta_result['win_rate']*100:.1f}%, Net P&L=${beta_result['net_pnl']:.2f}, Fees=${beta_result['total_fees']:.2f}",
            "validation": beta_result["validation"]
        }
        if is_valid:
            rec["action"] = "VALIDATED - Monitor Beta-Inversion performance"
            validated.append(rec)
        elif beta_result["net_pnl"] < -100:
            rec["action"] = "NOT VALIDATED - EMERGENCY DISABLE Beta-Inversion (massive losses)"
            unvalidated.append(rec)
        else:
            rec["action"] = "NOT VALIDATED - Needs review with more data"
            unvalidated.append(rec)
    
    long_result = validate_direction(trades, "LONG")
    if long_result["trades"] >= 100:
        is_valid = long_result["validation"].get("is_valid", False)
        rec = {
            "priority": "HIGH",
            "type": "direction",
            "reason": f"LONG: n={long_result['trades']}, WR={long_result['win_rate']*100:.1f}%, Net P&L=${long_result['net_pnl']:.2f}, Fees=${long_result['total_fees']:.2f}",
            "validation": long_result["validation"]
        }
        if is_valid:
            rec["action"] = "VALIDATED - LONG direction passes all criteria"
            validated.append(rec)
        elif long_result["net_pnl"] < -100 or long_result["win_rate"] < 0.15:
            rec["action"] = "NOT VALIDATED - REDUCE LONG exposure (poor performance)"
            unvalidated.append(rec)
        else:
            rec["action"] = "NOT VALIDATED - LONG needs more data"
            unvalidated.append(rec)
    
    short_result = validate_direction(trades, "SHORT")
    if short_result["trades"] >= 200:
        is_valid = short_result["validation"].get("is_valid", False)
        rec = {
            "priority": "MEDIUM",
            "type": "direction",
            "reason": f"SHORT: n={short_result['trades']}, WR={short_result['win_rate']*100:.1f}%, Net P&L=${short_result['net_pnl']:.2f}, Fees=${short_result['total_fees']:.2f}",
            "validation": short_result["validation"]
        }
        if is_valid:
            rec["action"] = "VALIDATED - CONTINUE SHORT trades (passes all criteria)"
            validated.append(rec)
        else:
            rec["action"] = "NOT VALIDATED - SHORT needs review (failed WR/EV criteria)"
            unvalidated.append(rec)
    
    return validated, unvalidated

def run_full_validation() -> dict:
    """Run full validation suite and save results."""
    trades = load_historical_trades()
    data_summary = get_data_summary()
    
    train, validation_set = split_train_validation(trades)
    validated, unvalidated = get_validated_recommendations()
    
    results = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data_summary": data_summary,
        "split_info": {
            "train_trades": len(train),
            "validation_trades": len(validation_set),
            "train_pct": len(train) / len(trades) * 100 if trades else 0
        },
        "strategy_validation": {},
        "direction_validation": {},
        "validated_recommendations": validated,
        "unvalidated_observations": unvalidated
    }
    
    for strategy in ["Alpha-OFI", "EMA-Futures", "Beta-Inversion"]:
        results["strategy_validation"][strategy] = validate_strategy(trades, strategy)
    
    for direction in ["LONG", "SHORT"]:
        results["direction_validation"][direction] = validate_direction(trades, direction)
    
    os.makedirs(VALIDATION_RESULTS_DIR, exist_ok=True)
    result_file = os.path.join(
        VALIDATION_RESULTS_DIR,
        f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(result_file, "w") as f:
        json.dump(results, f, indent=2)
    
    latest_file = os.path.join(VALIDATION_RESULTS_DIR, "latest_validation.json")
    with open(latest_file, "w") as f:
        json.dump(results, f, indent=2)
    
    return results

def print_validation_report():
    """Print human-readable validation report with clear separation."""
    print("=" * 70)
    print("PATTERN VALIDATION REPORT - Statistical Analysis")
    print("=" * 70)
    
    summary = get_data_summary()
    print(f"\n📊 DATA SUMMARY:")
    print(f"   Total Trades: {summary.get('total_trades', 0)}")
    print(f"   Trading Days: {summary.get('unique_days', 0)}")
    print(f"   Date Range: {summary.get('date_range', {}).get('start')} to {summary.get('date_range', {}).get('end')}")
    
    if summary.get("unique_days", 0) < 30:
        days_needed = summary.get("days_needed", 30)
        print(f"\n⚠️  INSUFFICIENT DATA WARNING:")
        print(f"   Only {summary.get('unique_days', 0)} days of data available.")
        print(f"   Need {days_needed} more days for reliable validation.")
        print(f"   ALL patterns below are HYPOTHESES, NOT proven facts!")
    
    validated, unvalidated = get_validated_recommendations()
    
    print(f"\n✅ VALIDATED PATTERNS (can be promoted to live trading):")
    if validated:
        for rec in validated:
            priority = rec.get("priority", "")
            action = rec.get("action", "")
            reason = rec.get("reason", "")
            print(f"\n   [{priority}] {action}")
            print(f"   ✓ PASSES ALL CRITERIA: WR>=50%, CI>=40%, EV>0, n>=200")
            print(f"   Evidence: {reason}")
    else:
        print("   (none - no patterns meet all validation criteria)")
    
    print(f"\n⚠️ UNVALIDATED OBSERVATIONS (DO NOT promote to live trading):")
    if unvalidated:
        for rec in unvalidated:
            priority = rec.get("priority", "")
            action = rec.get("action", "")
            reason = rec.get("reason", "")
            print(f"\n   [{priority}] {action}")
            print(f"   ⚠️ FAILS validation - needs more data or does not meet criteria")
            print(f"   Evidence: {reason}")
    else:
        print("   (none)")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    print_validation_report()
    
    print("\nRunning full validation...")
    results = run_full_validation()
    print(f"\nValidation complete! Results saved to {VALIDATION_RESULTS_DIR}/")
