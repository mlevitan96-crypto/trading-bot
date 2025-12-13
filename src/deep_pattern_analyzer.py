#!/usr/bin/env python3
"""
DEEP PATTERN ANALYZER - Comprehensive Profitability Discovery
==============================================================
Reusable template for slicing and dicing ALL trade data across every dimension
to discover profitable patterns and anti-patterns.

USAGE:
    python src/deep_pattern_analyzer.py                    # Full analysis
    python src/deep_pattern_analyzer.py --days 7           # Last 7 days only
    python src/deep_pattern_analyzer.py --export report    # Export to JSON report
    python src/deep_pattern_analyzer.py --symbol BTCUSDT   # Focus on one symbol

DIMENSIONS ANALYZED:
    - Symbol (per-coin performance)
    - Direction (LONG vs SHORT)
    - Strategy (which strategies work)
    - Session (time of day patterns)
    - Regime (trend/chop/volatile)
    - OFI bucket (order flow imbalance)
    - Ensemble score bucket
    - Leverage used
    - Position size bucket
    - Duration bucket
    - Day of week
    - Bot type (Alpha vs Beta)
    - Cross-coin correlations
    - Sequential patterns (winning/losing streaks)

OUTPUT:
    - Console summary with top patterns
    - JSON report at reports/deep_pattern_analysis.json
    - Actionable recommendations for thresholds
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any
import statistics

try:
    from dateutil import parser as dateutil_parser
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False

from src.data_registry import DataRegistry as DR

MIN_TRADES_FOR_PATTERN = 10

REPORT_PATH = "reports/deep_pattern_analysis.json"
os.makedirs("reports", exist_ok=True)


def load_trades() -> List[Dict]:
    """Load all trades from canonical source."""
    path = DR.POSITIONS_FUTURES
    if not os.path.exists(path):
        print(f"ERROR: Canonical trades file not found: {path}")
        return []
    
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        
        trades = []
        trades.extend(data.get("closed_positions", []))
        
        print(f"Loaded {len(trades)} closed trades from {path}")
        return trades
    except Exception as e:
        print(f"ERROR loading trades: {e}")
        return []


def load_enriched_decisions() -> List[Dict]:
    """Load enriched decision records for signal context."""
    path = DR.ENRICHED_DECISIONS
    if not os.path.exists(path):
        return []
    
    records = []
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except:
        pass
    
    print(f"Loaded {len(records)} enriched decisions for context")
    return records


def load_signals() -> List[Dict]:
    """Load signal universe for counterfactual analysis."""
    path = DR.SIGNALS_UNIVERSE
    if not os.path.exists(path):
        return []
    
    records = []
    try:
        with open(path, 'r') as f:
            for line in f:
                try:
                    records.append(json.loads(line.strip()))
                except:
                    continue
    except:
        pass
    
    print(f"Loaded {len(records)} signals for counterfactual context")
    return records


def parse_timestamp(ts_val) -> Optional[datetime]:
    """Parse various timestamp formats including timezone-aware strings.
    
    Uses dateutil if available for robust parsing, converts to UTC.
    """
    if not ts_val:
        return None
    
    if isinstance(ts_val, (int, float)):
        if ts_val > 1e12:
            ts_val = ts_val / 1000
        return datetime.fromtimestamp(ts_val, tz=timezone.utc).replace(tzinfo=None)
    
    if isinstance(ts_val, str):
        if HAS_DATEUTIL:
            try:
                parsed = dateutil_parser.parse(ts_val)
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                return parsed
            except:
                pass
        
        clean_ts = ts_val
        if "+" in clean_ts and clean_ts.count(":") >= 2:
            clean_ts = clean_ts.rsplit("+", 1)[0]
        if "-" in clean_ts and clean_ts.count("-") > 2:
            parts = clean_ts.rsplit("-", 1)
            if len(parts[1]) <= 5 and ":" in parts[1]:
                clean_ts = parts[0]
        clean_ts = clean_ts.replace("Z", "")
        
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ]:
            try:
                return datetime.strptime(clean_ts, fmt)
            except:
                continue
    
    return None


def get_session(dt: datetime) -> str:
    """Classify time into trading session."""
    if not dt:
        return "unknown"
    
    hour = dt.hour
    if 0 <= hour < 4:
        return "asia_night"
    elif 4 <= hour < 8:
        return "asia_morning"
    elif 8 <= hour < 12:
        return "europe_morning"
    elif 12 <= hour < 16:
        return "us_morning"
    elif 16 <= hour < 20:
        return "us_afternoon"
    else:
        return "evening"


def get_day_of_week(dt: datetime) -> str:
    """Get day of week."""
    if not dt:
        return "unknown"
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days[dt.weekday()]


def bucket_value(val, buckets: List[Tuple[float, str]]) -> str:
    """Bucket a numeric value into named ranges."""
    if val is None:
        return "unknown"
    
    for threshold, name in buckets:
        if val <= threshold:
            return name
    return buckets[-1][1] if buckets else "high"


def get_ofi_bucket(ofi: float) -> str:
    """Bucket OFI score."""
    if ofi is None:
        return "unknown"
    
    abs_ofi = abs(ofi)
    if abs_ofi < 0.3:
        return "weak"
    elif abs_ofi < 0.5:
        return "moderate"
    elif abs_ofi < 0.7:
        return "strong"
    elif abs_ofi < 0.9:
        return "very_strong"
    else:
        return "extreme"


def get_ensemble_bucket(score: float) -> str:
    """Bucket ensemble score."""
    if score is None:
        return "unknown"
    
    if score < -0.5:
        return "strong_bear"
    elif score < -0.2:
        return "bear"
    elif score < 0.2:
        return "neutral"
    elif score < 0.5:
        return "bull"
    else:
        return "strong_bull"


def get_leverage_bucket(lev: int) -> str:
    """Bucket leverage."""
    if lev is None:
        return "unknown"
    if lev <= 2:
        return "low_1-2x"
    elif lev <= 5:
        return "medium_3-5x"
    elif lev <= 10:
        return "high_6-10x"
    else:
        return "extreme_10x+"


def get_size_bucket(size: float) -> str:
    """Bucket position size in USD."""
    if size is None:
        return "unknown"
    if size < 50:
        return "tiny_<50"
    elif size < 100:
        return "small_50-100"
    elif size < 250:
        return "medium_100-250"
    elif size < 500:
        return "large_250-500"
    else:
        return "xlarge_500+"


def get_duration_bucket(opened_at, closed_at) -> str:
    """Bucket trade duration."""
    dt_open = parse_timestamp(opened_at)
    dt_close = parse_timestamp(closed_at)
    
    if not dt_open or not dt_close:
        return "unknown"
    
    duration_mins = (dt_close - dt_open).total_seconds() / 60
    
    if duration_mins < 5:
        return "scalp_<5min"
    elif duration_mins < 30:
        return "short_5-30min"
    elif duration_mins < 120:
        return "medium_30min-2h"
    elif duration_mins < 480:
        return "long_2-8h"
    else:
        return "swing_8h+"


class SliceStats:
    """Statistics for a slice of trades."""
    
    def __init__(self, name: str):
        self.name = name
        self.trades: List[Dict] = []
    
    def add(self, trade: Dict):
        self.trades.append(trade)
    
    def compute(self) -> Dict:
        if not self.trades:
            return {"name": self.name, "n": 0}
        
        pnls = []
        for t in self.trades:
            pnl = t.get("net_pnl") or t.get("pnl") or t.get("realized_pnl") or 0
            if isinstance(pnl, str):
                try:
                    pnl = float(pnl)
                except:
                    pnl = 0
            pnls.append(pnl)
        
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / n if n > 0 else 0
        win_rate = wins / n * 100 if n > 0 else 0
        
        winning_pnls = [p for p in pnls if p > 0]
        losing_pnls = [p for p in pnls if p < 0]
        
        avg_win = statistics.mean(winning_pnls) if winning_pnls else 0
        avg_loss = abs(statistics.mean(losing_pnls)) if losing_pnls else 0.01
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
        
        expectancy = (win_rate/100 * avg_win) - ((100 - win_rate)/100 * avg_loss)
        
        return {
            "name": self.name,
            "n": n,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "risk_reward": round(risk_reward, 2),
            "expectancy": round(expectancy, 2),
        }


class DimensionAnalyzer:
    """Analyzes trades across a single dimension."""
    
    def __init__(self, name: str, extractor):
        self.name = name
        self.extractor = extractor
        self.slices: Dict[str, SliceStats] = defaultdict(lambda: SliceStats(""))
    
    def add_trade(self, trade: Dict):
        key = self.extractor(trade)
        if key not in self.slices:
            self.slices[key] = SliceStats(key)
        self.slices[key].add(trade)
    
    def compute_all(self) -> List[Dict]:
        results = []
        for key, stats in self.slices.items():
            r = stats.compute()
            r["dimension"] = self.name
            results.append(r)
        return sorted(results, key=lambda x: x.get("total_pnl", 0), reverse=True)


class MultiDimensionAnalyzer:
    """Analyzes trades across multiple dimension combinations."""
    
    def __init__(self, dimensions: List[Tuple[str, callable]]):
        self.dimensions = dimensions
        self.slices: Dict[str, SliceStats] = {}
    
    def add_trade(self, trade: Dict):
        keys = []
        for name, extractor in self.dimensions:
            keys.append(f"{name}={extractor(trade)}")
        
        combo_key = "|".join(keys)
        if combo_key not in self.slices:
            self.slices[combo_key] = SliceStats(combo_key)
        self.slices[combo_key].add(trade)
    
    def compute_all(self, min_trades: int = 5) -> List[Dict]:
        results = []
        for key, stats in self.slices.items():
            r = stats.compute()
            if r["n"] >= min_trades:
                r["combo"] = key
                results.append(r)
        return sorted(results, key=lambda x: x.get("total_pnl", 0), reverse=True)


class DeepPatternAnalyzer:
    """
    Master analyzer that runs comprehensive pattern discovery.
    This is the main reusable template.
    """
    
    def __init__(self, days: Optional[int] = None, symbol: Optional[str] = None):
        self.days = days
        self.symbol = symbol
        self.trades = []
        self.enriched = []
        self.signals = []
        self.results = {}
        
    def load_data(self):
        """Load all required data."""
        print("\n" + "=" * 70)
        print("DEEP PATTERN ANALYZER - Loading Data")
        print("=" * 70)
        
        self.trades = load_trades()
        self.enriched = load_enriched_decisions()
        self.signals = load_signals()
        
        if self.days:
            cutoff = datetime.utcnow() - timedelta(days=self.days)
            filtered = []
            for t in self.trades:
                dt = parse_timestamp(t.get("closed_at") or t.get("opened_at"))
                if dt and dt >= cutoff:
                    filtered.append(t)
            print(f"Filtered to last {self.days} days: {len(filtered)} trades")
            self.trades = filtered
        
        if self.symbol:
            self.trades = [t for t in self.trades if t.get("symbol") == self.symbol]
            print(f"Filtered to symbol {self.symbol}: {len(self.trades)} trades")
        
        print(f"\nTotal trades for analysis: {len(self.trades)}")
    
    def _extract_symbol(self, t: Dict) -> str:
        return t.get("symbol", "unknown")
    
    def _extract_direction(self, t: Dict) -> str:
        return t.get("direction", t.get("side", "unknown"))
    
    def _extract_strategy(self, t: Dict) -> str:
        return t.get("strategy", "unknown")
    
    def _extract_session(self, t: Dict) -> str:
        dt = parse_timestamp(t.get("opened_at"))
        return get_session(dt)
    
    def _extract_day_of_week(self, t: Dict) -> str:
        dt = parse_timestamp(t.get("opened_at"))
        return get_day_of_week(dt)
    
    def _extract_regime(self, t: Dict) -> str:
        return t.get("regime", "unknown")
    
    def _extract_ofi_bucket(self, t: Dict) -> str:
        ofi = t.get("ofi_score")
        return get_ofi_bucket(ofi)
    
    def _extract_ensemble_bucket(self, t: Dict) -> str:
        ens = t.get("ensemble_score")
        return get_ensemble_bucket(ens)
    
    def _extract_leverage_bucket(self, t: Dict) -> str:
        lev = t.get("leverage")
        return get_leverage_bucket(lev)
    
    def _extract_size_bucket(self, t: Dict) -> str:
        size = t.get("size") or t.get("margin_collateral")
        return get_size_bucket(size)
    
    def _extract_duration_bucket(self, t: Dict) -> str:
        return get_duration_bucket(t.get("opened_at"), t.get("closed_at"))
    
    def _extract_bot_type(self, t: Dict) -> str:
        return t.get("bot_type", "alpha")
    
    def _extract_close_reason(self, t: Dict) -> str:
        return t.get("close_reason", "unknown")
    
    def _extract_hour(self, t: Dict) -> str:
        dt = parse_timestamp(t.get("opened_at"))
        if dt:
            return f"hour_{dt.hour:02d}"
        return "unknown"
    
    def analyze_single_dimensions(self):
        """Analyze each dimension independently."""
        print("\n" + "=" * 70)
        print("SINGLE DIMENSION ANALYSIS")
        print("=" * 70)
        
        dimensions = [
            ("symbol", self._extract_symbol),
            ("direction", self._extract_direction),
            ("strategy", self._extract_strategy),
            ("session", self._extract_session),
            ("day_of_week", self._extract_day_of_week),
            ("regime", self._extract_regime),
            ("ofi_bucket", self._extract_ofi_bucket),
            ("ensemble_bucket", self._extract_ensemble_bucket),
            ("leverage_bucket", self._extract_leverage_bucket),
            ("size_bucket", self._extract_size_bucket),
            ("duration_bucket", self._extract_duration_bucket),
            ("bot_type", self._extract_bot_type),
            ("close_reason", self._extract_close_reason),
            ("hour", self._extract_hour),
        ]
        
        self.results["single_dimensions"] = {}
        
        for dim_name, extractor in dimensions:
            analyzer = DimensionAnalyzer(dim_name, extractor)
            for trade in self.trades:
                analyzer.add_trade(trade)
            
            results = analyzer.compute_all()
            self.results["single_dimensions"][dim_name] = results
            
            print(f"\n{dim_name.upper()}:")
            print("-" * 50)
            for r in results[:10]:
                if r["n"] >= 3:
                    pnl_color = "+" if r["total_pnl"] >= 0 else ""
                    print(f"  {r['name']:20s} n={r['n']:4d}  WR={r['win_rate']:5.1f}%  "
                          f"P&L=${pnl_color}{r['total_pnl']:8.2f}  EV=${r['expectancy']:6.2f}  R/R={r['risk_reward']:.2f}")
    
    def analyze_multi_dimensions(self):
        """Analyze 2-way and 3-way dimension combinations."""
        print("\n" + "=" * 70)
        print("MULTI-DIMENSIONAL COMBINATION ANALYSIS")
        print("=" * 70)
        
        key_dimensions = [
            ("sym", self._extract_symbol),
            ("dir", self._extract_direction),
            ("ofi", self._extract_ofi_bucket),
            ("ens", self._extract_ensemble_bucket),
            ("sess", self._extract_session),
            ("dur", self._extract_duration_bucket),
        ]
        
        self.results["profitable_combos"] = []
        self.results["unprofitable_combos"] = []
        
        for i in range(len(key_dimensions)):
            for j in range(i + 1, len(key_dimensions)):
                dims = [key_dimensions[i], key_dimensions[j]]
                analyzer = MultiDimensionAnalyzer(dims)
                
                for trade in self.trades:
                    analyzer.add_trade(trade)
                
                results = analyzer.compute_all(min_trades=MIN_TRADES_FOR_PATTERN)
                
                for r in results:
                    if r["total_pnl"] > 0 and r["win_rate"] >= 40 and r["n"] >= MIN_TRADES_FOR_PATTERN:
                        self.results["profitable_combos"].append(r)
                    elif r["total_pnl"] < -50 and r["n"] >= MIN_TRADES_FOR_PATTERN:
                        self.results["unprofitable_combos"].append(r)
        
        for i in range(len(key_dimensions)):
            for j in range(i + 1, len(key_dimensions)):
                for k in range(j + 1, len(key_dimensions)):
                    dims = [key_dimensions[i], key_dimensions[j], key_dimensions[k]]
                    analyzer = MultiDimensionAnalyzer(dims)
                    
                    for trade in self.trades:
                        analyzer.add_trade(trade)
                    
                    results = analyzer.compute_all(min_trades=MIN_TRADES_FOR_PATTERN)
                    
                    for r in results:
                        if r["total_pnl"] > 10 and r["win_rate"] >= 45 and r["n"] >= MIN_TRADES_FOR_PATTERN:
                            self.results["profitable_combos"].append(r)
                        elif r["total_pnl"] < -100 and r["n"] >= MIN_TRADES_FOR_PATTERN:
                            self.results["unprofitable_combos"].append(r)
        
        self.results["profitable_combos"].sort(key=lambda x: x["total_pnl"], reverse=True)
        self.results["unprofitable_combos"].sort(key=lambda x: x["total_pnl"])
        
        print("\nTOP PROFITABLE PATTERNS:")
        print("-" * 70)
        for r in self.results["profitable_combos"][:20]:
            print(f"  {r['combo']:50s}")
            print(f"      n={r['n']:4d}  WR={r['win_rate']:5.1f}%  P&L=${r['total_pnl']:+8.2f}  "
                  f"EV=${r['expectancy']:+6.2f}  R/R={r['risk_reward']:.2f}")
        
        print("\n\nTOP UNPROFITABLE PATTERNS (AVOID):")
        print("-" * 70)
        for r in self.results["unprofitable_combos"][:15]:
            print(f"  {r['combo']:50s}")
            print(f"      n={r['n']:4d}  WR={r['win_rate']:5.1f}%  P&L=${r['total_pnl']:+8.2f}  "
                  f"EV=${r['expectancy']:+6.2f}  R/R={r['risk_reward']:.2f}")
    
    def analyze_correlations(self):
        """Analyze cross-coin correlations and rotation patterns."""
        print("\n" + "=" * 70)
        print("CROSS-COIN CORRELATION ANALYSIS")
        print("=" * 70)
        
        by_symbol = defaultdict(list)
        for t in self.trades:
            sym = t.get("symbol", "unknown")
            pnl = t.get("net_pnl") or t.get("pnl") or 0
            dt = parse_timestamp(t.get("closed_at"))
            if dt:
                by_symbol[sym].append({"pnl": pnl, "ts": dt})
        
        symbol_hourly_pnl = {}
        for sym, trades in by_symbol.items():
            hourly = defaultdict(float)
            for t in trades:
                hour_key = t["ts"].strftime("%Y-%m-%d-%H")
                hourly[hour_key] += t["pnl"]
            symbol_hourly_pnl[sym] = hourly
        
        correlations = {}
        symbols = list(symbol_hourly_pnl.keys())
        
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                s1, s2 = symbols[i], symbols[j]
                h1, h2 = symbol_hourly_pnl[s1], symbol_hourly_pnl[s2]
                
                common_hours = set(h1.keys()) & set(h2.keys())
                if len(common_hours) < 10:
                    continue
                
                vals1 = [h1[h] for h in common_hours]
                vals2 = [h2[h] for h in common_hours]
                
                if len(vals1) >= 2 and statistics.stdev(vals1) > 0 and statistics.stdev(vals2) > 0:
                    mean1, mean2 = statistics.mean(vals1), statistics.mean(vals2)
                    std1, std2 = statistics.stdev(vals1), statistics.stdev(vals2)
                    
                    cov = sum((v1 - mean1) * (v2 - mean2) for v1, v2 in zip(vals1, vals2)) / len(vals1)
                    corr = cov / (std1 * std2) if std1 * std2 > 0 else 0
                    
                    correlations[(s1, s2)] = round(corr, 3)
        
        self.results["correlations"] = correlations
        
        sorted_corrs = sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)
        
        print("\nSTRONGEST CORRELATIONS:")
        for (s1, s2), corr in sorted_corrs[:15]:
            direction = "positive" if corr > 0 else "negative"
            print(f"  {s1} <-> {s2}: {corr:+.3f} ({direction})")
    
    def analyze_streaks(self):
        """Analyze winning and losing streak patterns."""
        print("\n" + "=" * 70)
        print("STREAK PATTERN ANALYSIS")
        print("=" * 70)
        
        sorted_trades = sorted(self.trades, key=lambda t: str(t.get("closed_at", "")))
        
        current_streak = 0
        streak_results = {"after_win_streak": [], "after_loss_streak": []}
        
        for i, trade in enumerate(sorted_trades):
            pnl = trade.get("net_pnl") or trade.get("pnl") or 0
            
            if i > 0:
                prev_pnl = sorted_trades[i-1].get("net_pnl") or sorted_trades[i-1].get("pnl") or 0
                
                if prev_pnl > 0:
                    if current_streak >= 0:
                        current_streak += 1
                    else:
                        current_streak = 1
                else:
                    if current_streak <= 0:
                        current_streak -= 1
                    else:
                        current_streak = -1
                
                if current_streak >= 3:
                    streak_results["after_win_streak"].append(pnl)
                elif current_streak <= -3:
                    streak_results["after_loss_streak"].append(pnl)
        
        self.results["streak_analysis"] = {}
        
        for streak_type, pnls in streak_results.items():
            if pnls:
                wins = sum(1 for p in pnls if p > 0)
                wr = wins / len(pnls) * 100
                avg_pnl = statistics.mean(pnls)
                total = sum(pnls)
                
                self.results["streak_analysis"][streak_type] = {
                    "count": len(pnls),
                    "win_rate": round(wr, 1),
                    "avg_pnl": round(avg_pnl, 2),
                    "total_pnl": round(total, 2)
                }
                
                print(f"\n{streak_type.upper().replace('_', ' ')}:")
                print(f"  Trades: {len(pnls)}, Win Rate: {wr:.1f}%, Avg P&L: ${avg_pnl:.2f}, Total: ${total:.2f}")
    
    def generate_recommendations(self):
        """Generate actionable recommendations based on analysis."""
        print("\n" + "=" * 70)
        print("ACTIONABLE RECOMMENDATIONS")
        print("=" * 70)
        
        recommendations = []
        
        symbol_stats = self.results.get("single_dimensions", {}).get("symbol", [])
        profitable_symbols = [s for s in symbol_stats if s.get("total_pnl", 0) > 0 and s.get("n", 0) >= 10]
        unprofitable_symbols = [s for s in symbol_stats if s.get("total_pnl", 0) < -50 and s.get("n", 0) >= 10]
        
        if profitable_symbols:
            syms = [s["name"] for s in profitable_symbols[:5]]
            recommendations.append({
                "type": "BOOST",
                "action": f"Increase allocation to profitable symbols: {', '.join(syms)}",
                "confidence": "HIGH"
            })
        
        if unprofitable_symbols:
            syms = [s["name"] for s in unprofitable_symbols[:3]]
            recommendations.append({
                "type": "REDUCE",
                "action": f"Reduce or disable unprofitable symbols: {', '.join(syms)}",
                "confidence": "HIGH"
            })
        
        direction_stats = self.results.get("single_dimensions", {}).get("direction", [])
        for d in direction_stats:
            if d.get("n", 0) >= 20:
                if d["name"] == "LONG" and d.get("total_pnl", 0) > 0 and d.get("win_rate", 0) < 50:
                    recommendations.append({
                        "type": "FILTER",
                        "action": "LONG trades profitable but low WR - tighten entry filters",
                        "confidence": "MEDIUM"
                    })
                elif d["name"] == "SHORT" and d.get("win_rate", 0) > 50:
                    recommendations.append({
                        "type": "BOOST",
                        "action": "SHORT trades performing well - consider increasing SHORT allocation",
                        "confidence": "MEDIUM"
                    })
        
        session_stats = self.results.get("single_dimensions", {}).get("session", [])
        for s in session_stats:
            if s.get("n", 0) >= 20:
                if s.get("total_pnl", 0) < -50:
                    recommendations.append({
                        "type": "AVOID",
                        "action": f"Consider reducing trading during {s['name']} session (P&L: ${s['total_pnl']:.2f})",
                        "confidence": "MEDIUM"
                    })
                elif s.get("total_pnl", 0) > 50:
                    recommendations.append({
                        "type": "FOCUS",
                        "action": f"Focus trading during {s['name']} session (P&L: ${s['total_pnl']:.2f})",
                        "confidence": "MEDIUM"
                    })
        
        profitable_combos = self.results.get("profitable_combos", [])[:5]
        for combo in profitable_combos:
            recommendations.append({
                "type": "PATTERN",
                "action": f"Profitable pattern: {combo['combo']} (WR: {combo['win_rate']:.1f}%, P&L: ${combo['total_pnl']:.2f})",
                "confidence": "HIGH" if combo["n"] >= 20 else "MEDIUM"
            })
        
        self.results["recommendations"] = recommendations
        
        for rec in recommendations:
            emoji = {"BOOST": "🚀", "REDUCE": "⚠️", "AVOID": "🚫", "FOCUS": "🎯", "FILTER": "🔧", "PATTERN": "✨"}.get(rec["type"], "📌")
            print(f"\n{emoji} [{rec['type']}] ({rec['confidence']})")
            print(f"   {rec['action']}")
    
    def generate_thresholds(self):
        """Generate optimal threshold recommendations."""
        print("\n" + "=" * 70)
        print("OPTIMAL THRESHOLD RECOMMENDATIONS")
        print("=" * 70)
        
        thresholds = {}
        
        ofi_stats = self.results.get("single_dimensions", {}).get("ofi_bucket", [])
        best_ofi = max(ofi_stats, key=lambda x: x.get("expectancy", -999)) if ofi_stats else None
        if best_ofi and best_ofi.get("n", 0) >= 10:
            thresholds["ofi_bucket"] = {
                "best": best_ofi["name"],
                "expectancy": best_ofi["expectancy"],
                "recommendation": f"Focus on {best_ofi['name']} OFI conditions"
            }
            print(f"\nOFI: Best bucket is '{best_ofi['name']}' (EV: ${best_ofi['expectancy']:.2f})")
        
        ens_stats = self.results.get("single_dimensions", {}).get("ensemble_bucket", [])
        best_ens = max(ens_stats, key=lambda x: x.get("expectancy", -999)) if ens_stats else None
        if best_ens and best_ens.get("n", 0) >= 10:
            thresholds["ensemble_bucket"] = {
                "best": best_ens["name"],
                "expectancy": best_ens["expectancy"],
                "recommendation": f"Focus on {best_ens['name']} ensemble conditions"
            }
            print(f"ENSEMBLE: Best bucket is '{best_ens['name']}' (EV: ${best_ens['expectancy']:.2f})")
        
        lev_stats = self.results.get("single_dimensions", {}).get("leverage_bucket", [])
        best_lev = max(lev_stats, key=lambda x: x.get("expectancy", -999)) if lev_stats else None
        if best_lev and best_lev.get("n", 0) >= 10:
            thresholds["leverage"] = {
                "best": best_lev["name"],
                "expectancy": best_lev["expectancy"],
                "recommendation": f"Optimal leverage range: {best_lev['name']}"
            }
            print(f"LEVERAGE: Best range is '{best_lev['name']}' (EV: ${best_lev['expectancy']:.2f})")
        
        dur_stats = self.results.get("single_dimensions", {}).get("duration_bucket", [])
        best_dur = max(dur_stats, key=lambda x: x.get("expectancy", -999)) if dur_stats else None
        if best_dur and best_dur.get("n", 0) >= 10:
            thresholds["duration"] = {
                "best": best_dur["name"],
                "expectancy": best_dur["expectancy"],
                "recommendation": f"Optimal hold duration: {best_dur['name']}"
            }
            print(f"DURATION: Best range is '{best_dur['name']}' (EV: ${best_dur['expectancy']:.2f})")
        
        self.results["thresholds"] = thresholds
    
    def save_report(self, path: str = None):
        """Save complete analysis to JSON report."""
        path = path or REPORT_PATH
        
        report = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "config": {
                "days_filter": self.days,
                "symbol_filter": self.symbol,
                "total_trades_analyzed": len(self.trades)
            },
            "analysis": self.results
        }
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\n📄 Full report saved to: {path}")
    
    def run_full_analysis(self):
        """Run the complete analysis pipeline."""
        start = time.time()
        
        print("\n" + "=" * 70)
        print("🔬 DEEP PATTERN ANALYZER - COMPREHENSIVE PROFITABILITY DISCOVERY")
        print("=" * 70)
        print(f"Started: {datetime.utcnow().isoformat()}Z")
        
        self.load_data()
        
        if not self.trades:
            print("\n❌ No trades to analyze!")
            return self.results
        
        self.analyze_single_dimensions()
        self.analyze_multi_dimensions()
        self.analyze_correlations()
        self.analyze_streaks()
        self.generate_thresholds()
        self.generate_recommendations()
        self.save_report()
        
        elapsed = time.time() - start
        
        print("\n" + "=" * 70)
        print(f"✅ ANALYSIS COMPLETE")
        print(f"   Trades analyzed: {len(self.trades)}")
        print(f"   Profitable patterns found: {len(self.results.get('profitable_combos', []))}")
        print(f"   Recommendations generated: {len(self.results.get('recommendations', []))}")
        print(f"   Time elapsed: {elapsed:.1f}s")
        print("=" * 70)
        
        return self.results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Deep Pattern Analyzer - Comprehensive Profitability Discovery")
    parser.add_argument("--days", type=int, help="Analyze only last N days")
    parser.add_argument("--symbol", type=str, help="Focus on specific symbol")
    parser.add_argument("--export", type=str, help="Export path for JSON report")
    
    args = parser.parse_args()
    
    analyzer = DeepPatternAnalyzer(days=args.days, symbol=args.symbol)
    results = analyzer.run_full_analysis()
    
    if args.export:
        analyzer.save_report(args.export)
    
    return results


if __name__ == "__main__":
    main()
