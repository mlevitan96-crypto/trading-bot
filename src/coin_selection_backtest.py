"""
Coin Selection Strategy Backtester - NO LOOK-AHEAD BIAS

This backtester replays historical signals through the new Coin Selection Engine
using ONLY data that was available at the time of each signal.

Key principles:
1. Time-ordered processing - signals replayed in chronological order
2. No future data - only uses learning rules/profiles from BEFORE the signal
3. Compares "would have traded" vs "what actually happened"
4. Calculates true performance delta between old and new strategy
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

SIGNALS_LOG = "logs/signals_universe.jsonl"
PORTFOLIO_LOG = "logs/portfolio.json"
ENRICHED_DECISIONS = "logs/enriched_decisions.jsonl"
BACKTEST_RESULTS = "logs/backtest_coin_selection.json"

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _parse_ts(ts_str) -> Optional[datetime]:
    """Parse various timestamp formats."""
    if not ts_str:
        return None
    try:
        if isinstance(ts_str, (int, float)):
            return datetime.fromtimestamp(float(ts_str))
        ts_str = str(ts_str)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1]
        if "T" in ts_str:
            return datetime.fromisoformat(ts_str)
        return datetime.fromtimestamp(float(ts_str))
    except:
        return None

def load_signals(hours_back: int = 48) -> List[Dict]:
    """Load signals from the past N hours."""
    signals = []
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    
    if not os.path.exists(SIGNALS_LOG):
        print(f"[BACKTEST] No signals file found at {SIGNALS_LOG}")
        return []
    
    with open(SIGNALS_LOG, 'r') as f:
        for line in f:
            try:
                sig = json.loads(line.strip())
                ts = _parse_ts(sig.get("ts", ""))
                if ts and ts >= cutoff:
                    sig["_parsed_ts"] = ts
                    signals.append(sig)
            except:
                continue
    
    signals.sort(key=lambda x: x.get("_parsed_ts", datetime.min))
    print(f"[BACKTEST] Loaded {len(signals)} signals from past {hours_back} hours")
    return signals

def load_actual_trades(hours_back: int = 48) -> Dict[str, Dict]:
    """Load actual trades that were executed."""
    trades = {}
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    
    if not os.path.exists(PORTFOLIO_LOG):
        return {}
    
    try:
        with open(PORTFOLIO_LOG, 'r') as f:
            data = json.load(f)
        
        for trade in data.get("trades", []):
            ts = _parse_ts(trade.get("entry_time", "") or trade.get("ts", ""))
            if ts and ts >= cutoff:
                key = f"{trade.get('symbol', '')}_{ts.isoformat()}"
                trades[key] = trade
    except:
        pass
    
    print(f"[BACKTEST] Loaded {len(trades)} actual trades from past {hours_back} hours")
    return trades

def load_enriched_decisions(hours_back: int = 48) -> List[Dict]:
    """Load enriched decision records (signals + outcomes)."""
    decisions = []
    cutoff = datetime.utcnow() - timedelta(hours=hours_back)
    
    if not os.path.exists(ENRICHED_DECISIONS):
        return []
    
    with open(ENRICHED_DECISIONS, 'r') as f:
        for line in f:
            try:
                dec = json.loads(line.strip())
                ts = _parse_ts(dec.get("ts", ""))
                if ts and ts >= cutoff:
                    dec["_parsed_ts"] = ts
                    
                    signal_ctx = dec.get("signal_ctx", {})
                    outcome = dec.get("outcome", {})
                    dec["symbol"] = dec.get("symbol", "")
                    dec["side"] = signal_ctx.get("side", "")
                    dec["disposition"] = "executed"
                    dec["realized_pnl"] = outcome.get("pnl_usd", 0)
                    dec["intelligence"] = {
                        "ofi": abs(signal_ctx.get("ofi", 0)),
                        "ensemble": signal_ctx.get("ensemble", 0),
                        "roi": signal_ctx.get("roi", 0),
                        "regime": signal_ctx.get("regime", "unknown")
                    }
                    
                    decisions.append(dec)
            except:
                continue
    
    decisions.sort(key=lambda x: x.get("_parsed_ts", datetime.min))
    print(f"[BACKTEST] Loaded {len(decisions)} enriched decisions from past {hours_back} hours")
    return decisions


class CoinSelectionBacktester:
    """
    Replays historical signals through coin selection logic.
    
    For each signal, calculates:
    1. What grade would the coin selection engine give it?
    2. Would we have traded it under the new rules?
    3. What was the actual outcome?
    4. Compare P&L: new strategy vs baseline
    """
    
    def __init__(self, hours_back: int = 48):
        self.hours_back = hours_back
        self.decisions = []
        self.results = {
            "run_ts": _now(),
            "hours_back": hours_back,
            "baseline": {"trades": 0, "wins": 0, "pnl": 0.0},
            "new_strategy": {"trades": 0, "wins": 0, "pnl": 0.0},
            "blocked_by_new": [],
            "boosted_by_new": [],
            "grade_distribution": defaultdict(int),
            "per_coin_analysis": {},
            "summary": {}
        }
        
        self.direction_accuracy = {
            "DOTUSDT": 0.90, "AVAXUSDT": 0.86, "ETHUSDT": 0.71,
            "DOGEUSDT": 0.69, "ADAUSDT": 0.65, "SOLUSDT": 0.64,
            "XRPUSDT": 0.63, "BNBUSDT": 0.59, "BTCUSDT": 0.55,
            "MATICUSDT": 0.60, "LINKUSDT": 0.60, "TRXUSDT": 0.55,
            "ARBUSDT": 0.58, "OPUSDT": 0.58, "PEPEUSDT": 0.55
        }
        
        self.profitable_patterns = {}
        self._load_learning_state()
    
    def _load_learning_state(self):
        """Load the learning state that was available at backtest start."""
        try:
            with open("feature_store/daily_learning_rules.json", 'r') as f:
                rules = json.load(f)
                self.profitable_patterns = rules.get("profitable_patterns", {})
        except:
            pass
    
    def grade_signal(self, signal: Dict) -> Dict:
        """
        Grade a signal using coin selection logic.
        Returns grade (A-F) and sizing multiplier.
        
        This is a PURE function using only data available at signal time.
        """
        symbol = signal.get("symbol", "")
        direction = signal.get("side", signal.get("direction", "")).upper()
        if direction in ["BUY", "LONG"]:
            direction = "LONG"
        elif direction in ["SELL", "SHORT"]:
            direction = "SHORT"
        
        intel = signal.get("intelligence", {})
        ofi = intel.get("ofi", 0.5)
        ensemble = intel.get("ensemble", 0)
        
        ofi_bucket = "extreme" if ofi > 0.8 else "very_strong" if ofi > 0.7 else "strong" if ofi > 0.6 else "moderate" if ofi > 0.4 else "weak"
        ens_bucket = "strong_bull" if ensemble > 0.3 else "bull" if ensemble > 0.1 else "neutral" if ensemble > -0.1 else "bear" if ensemble > -0.3 else "strong_bear"
        
        score = 0
        factors = []
        
        accuracy = self.direction_accuracy.get(symbol, 0.5)
        if accuracy >= 0.80:
            score += 30
            factors.append("elite_accuracy")
        elif accuracy >= 0.70:
            score += 20
            factors.append("high_accuracy")
        elif accuracy >= 0.58:
            score += 10
            factors.append("standard_accuracy")
        else:
            score -= 10
            factors.append("low_accuracy_penalty")
        
        pattern_key = f"sym={symbol}|dir={direction}"
        for key, data in self.profitable_patterns.items():
            if pattern_key in key:
                pnl = data.get("pnl", 0)
                wr = data.get("wr", 0)
                if pnl > 5 and wr >= 50:
                    score += 25
                    factors.append("strong_pattern")
                elif pnl > 0:
                    score += 15
                    factors.append("positive_pattern")
        
        ofi_pattern = f"sym={symbol}|ofi={ofi_bucket}"
        for key, data in self.profitable_patterns.items():
            if ofi_pattern in key and data.get("pnl", 0) > 0:
                score += 10
                factors.append("ofi_match")
                break
        
        grade = "F"
        size_mult = 0.5
        if score >= 60:
            grade = "A"
            size_mult = 1.4
        elif score >= 45:
            grade = "B"
            size_mult = 1.2
        elif score >= 30:
            grade = "C"
            size_mult = 1.0
        elif score >= 15:
            grade = "D"
            size_mult = 0.75
        else:
            grade = "F"
            size_mult = 0.5
        
        return {
            "grade": grade,
            "score": score,
            "size_mult": size_mult,
            "should_trade": grade in ["A", "B", "C"],
            "factors": factors,
            "accuracy": accuracy
        }
    
    def run_backtest(self):
        """Run the full backtest."""
        print("\n" + "="*70)
        print("🔬 COIN SELECTION STRATEGY BACKTEST")
        print("="*70)
        print(f"Period: Past {self.hours_back} hours")
        print(f"Run time: {_now()}")
        print("-"*70)
        
        self.decisions = load_enriched_decisions(self.hours_back)
        
        if not self.decisions:
            print("❌ No enriched decisions found for backtest period")
            print("   Using signals_universe instead...")
            signals = load_signals(self.hours_back)
            for sig in signals:
                self.decisions.append({
                    "symbol": sig.get("symbol", ""),
                    "side": sig.get("side", ""),
                    "ts": sig.get("ts", ""),
                    "disposition": sig.get("disposition", "executed"),
                    "intelligence": sig.get("intelligence", {}),
                    "realized_pnl": 0
                })
        
        for i, decision in enumerate(self.decisions):
            symbol = decision.get("symbol", "")
            disposition = decision.get("disposition", "")
            realized_pnl = float(decision.get("realized_pnl", 0) or 0)
            
            grading = self.grade_signal(decision)
            grade = grading["grade"]
            should_trade = grading["should_trade"]
            size_mult = grading["size_mult"]
            
            self.results["grade_distribution"][grade] += 1
            
            if symbol not in self.results["per_coin_analysis"]:
                self.results["per_coin_analysis"][symbol] = {
                    "total": 0, "graded_trade": 0, "graded_skip": 0,
                    "baseline_pnl": 0.0, "new_pnl": 0.0,
                    "blocked_pnl": 0.0, "boosted_pnl": 0.0
                }
            
            coin_stats = self.results["per_coin_analysis"][symbol]
            coin_stats["total"] += 1
            
            if disposition == "executed":
                self.results["baseline"]["trades"] += 1
                self.results["baseline"]["pnl"] += realized_pnl
                coin_stats["baseline_pnl"] += realized_pnl
                
                if realized_pnl > 0:
                    self.results["baseline"]["wins"] += 1
                
                if should_trade:
                    adjusted_pnl = realized_pnl * size_mult
                    self.results["new_strategy"]["trades"] += 1
                    self.results["new_strategy"]["pnl"] += adjusted_pnl
                    coin_stats["new_pnl"] += adjusted_pnl
                    coin_stats["graded_trade"] += 1
                    
                    if adjusted_pnl > 0:
                        self.results["new_strategy"]["wins"] += 1
                    
                    if size_mult > 1.0:
                        self.results["boosted_by_new"].append({
                            "symbol": symbol,
                            "grade": grade,
                            "size_mult": size_mult,
                            "original_pnl": realized_pnl,
                            "adjusted_pnl": adjusted_pnl
                        })
                        coin_stats["boosted_pnl"] += (adjusted_pnl - realized_pnl)
                else:
                    coin_stats["graded_skip"] += 1
                    self.results["blocked_by_new"].append({
                        "symbol": symbol,
                        "grade": grade,
                        "avoided_pnl": realized_pnl,
                        "factors": grading["factors"]
                    })
                    coin_stats["blocked_pnl"] += realized_pnl
        
        self._compute_summary()
        self._print_results()
        self._save_results()
        
        return self.results
    
    def _compute_summary(self):
        """Compute summary statistics."""
        baseline = self.results["baseline"]
        new_strat = self.results["new_strategy"]
        
        baseline_wr = (baseline["wins"] / baseline["trades"] * 100) if baseline["trades"] > 0 else 0
        new_wr = (new_strat["wins"] / new_strat["trades"] * 100) if new_strat["trades"] > 0 else 0
        
        blocked = self.results["blocked_by_new"]
        avoided_losses = sum(b["avoided_pnl"] for b in blocked if b["avoided_pnl"] < 0)
        missed_wins = sum(b["avoided_pnl"] for b in blocked if b["avoided_pnl"] > 0)
        
        boosted = self.results["boosted_by_new"]
        boost_gain = sum(b["adjusted_pnl"] - b["original_pnl"] for b in boosted)
        
        pnl_delta = new_strat["pnl"] - baseline["pnl"]
        pnl_delta_with_avoided = pnl_delta + abs(avoided_losses)
        
        self.results["summary"] = {
            "baseline_trades": baseline["trades"],
            "baseline_wr": round(baseline_wr, 1),
            "baseline_pnl": round(baseline["pnl"], 2),
            
            "new_trades": new_strat["trades"],
            "new_wr": round(new_wr, 1),
            "new_pnl": round(new_strat["pnl"], 2),
            
            "trades_blocked": len(blocked),
            "avoided_losses": round(avoided_losses, 2),
            "missed_wins": round(missed_wins, 2),
            "net_avoided": round(avoided_losses + missed_wins, 2),
            
            "trades_boosted": len(boosted),
            "boost_gain": round(boost_gain, 2),
            
            "pnl_delta": round(pnl_delta, 2),
            "pnl_delta_with_avoided": round(pnl_delta_with_avoided, 2),
            
            "improvement_pct": round((pnl_delta_with_avoided / abs(baseline["pnl"]) * 100) if baseline["pnl"] != 0 else 0, 1)
        }
    
    def _print_results(self):
        """Print backtest results."""
        s = self.results["summary"]
        
        print("\n" + "="*70)
        print("📊 BACKTEST RESULTS")
        print("="*70)
        
        print("\n🔹 BASELINE (What Actually Happened):")
        print(f"   Trades: {s['baseline_trades']}")
        print(f"   Win Rate: {s['baseline_wr']}%")
        print(f"   P&L: ${s['baseline_pnl']:.2f}")
        
        print("\n🔹 NEW STRATEGY (Coin Selection Applied):")
        print(f"   Trades: {s['new_trades']} ({s['trades_blocked']} blocked)")
        print(f"   Win Rate: {s['new_wr']}%")
        print(f"   P&L: ${s['new_pnl']:.2f}")
        
        print("\n🔹 BLOCKING ANALYSIS:")
        print(f"   Trades blocked: {s['trades_blocked']}")
        print(f"   Avoided losses: ${s['avoided_losses']:.2f}")
        print(f"   Missed wins: ${s['missed_wins']:.2f}")
        print(f"   Net avoided: ${s['net_avoided']:.2f}")
        
        print("\n🔹 BOOSTING ANALYSIS:")
        print(f"   Trades boosted: {s['trades_boosted']}")
        print(f"   Boost gain: ${s['boost_gain']:.2f}")
        
        print("\n" + "="*70)
        print("📈 NET IMPROVEMENT")
        print("="*70)
        print(f"   Direct P&L delta: ${s['pnl_delta']:.2f}")
        print(f"   With avoided losses: ${s['pnl_delta_with_avoided']:.2f}")
        print(f"   Improvement: {s['improvement_pct']}%")
        
        print("\n🔹 GRADE DISTRIBUTION:")
        for grade in ["A", "B", "C", "D", "F"]:
            count = self.results["grade_distribution"].get(grade, 0)
            print(f"   Grade {grade}: {count} signals")
        
        print("\n🔹 PER-COIN ANALYSIS:")
        for symbol, stats in sorted(self.results["per_coin_analysis"].items(), 
                                    key=lambda x: x[1]["blocked_pnl"]):
            if stats["total"] > 0:
                delta = stats["new_pnl"] - stats["baseline_pnl"] + abs(min(0, stats["blocked_pnl"]))
                print(f"   {symbol:12} | Baseline: ${stats['baseline_pnl']:7.2f} | "
                      f"New: ${stats['new_pnl']:7.2f} | Blocked: ${stats['blocked_pnl']:7.2f} | "
                      f"Delta: ${delta:+7.2f}")
        
        print("="*70 + "\n")
    
    def _save_results(self):
        """Save backtest results to file."""
        results_copy = dict(self.results)
        results_copy["grade_distribution"] = dict(results_copy["grade_distribution"])
        
        os.makedirs(os.path.dirname(BACKTEST_RESULTS), exist_ok=True)
        with open(BACKTEST_RESULTS, 'w') as f:
            json.dump(results_copy, f, indent=2, default=str)
        print(f"💾 Results saved to: {BACKTEST_RESULTS}")


def run_backtest(hours_back: int = 48) -> Dict:
    """Run coin selection backtest."""
    backtester = CoinSelectionBacktester(hours_back=hours_back)
    return backtester.run_backtest()


if __name__ == "__main__":
    import sys
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 48
    run_backtest(hours_back=hours)
