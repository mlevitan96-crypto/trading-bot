#!/usr/bin/env python3
"""
Deep Profitability Analyzer - Comprehensive Trading Bot Analysis
Analyzes all trades, signals, and decisions to identify profitable patterns
and provide concrete optimization recommendations.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Any
import statistics

class DeepProfitabilityAnalyzer:
    def __init__(self):
        self.positions_file = "logs/positions_futures.json"
        self.enriched_file = "logs/enriched_decisions.jsonl"
        self.signals_file = "logs/signals_universe.jsonl"
        self.learning_rules_file = "feature_store/daily_learning_rules.json"
        self.thresholds_file = "feature_store/optimal_thresholds.json"
        self.feedback_file = "feature_store/feedback_loop_summary.json"
        
        self.closed_trades = []
        self.open_positions = []
        self.enriched_decisions = []
        self.signals = []
        self.analysis_results = {}
        
    def load_all_data(self):
        """Load all trading data sources."""
        print("=" * 70)
        print("LOADING DATA SOURCES")
        print("=" * 70)
        
        if os.path.exists(self.positions_file):
            with open(self.positions_file, 'r') as f:
                data = json.load(f)
                self.closed_trades = data.get('closed_positions', [])
                self.open_positions = data.get('open_positions', [])
                print(f"  Closed trades: {len(self.closed_trades)}")
                print(f"  Open positions: {len(self.open_positions)}")
        
        if os.path.exists(self.enriched_file):
            with open(self.enriched_file, 'r') as f:
                for line in f:
                    try:
                        self.enriched_decisions.append(json.loads(line.strip()))
                    except:
                        pass
            print(f"  Enriched decisions: {len(self.enriched_decisions)}")
        
        if os.path.exists(self.signals_file):
            with open(self.signals_file, 'r') as f:
                for line in f:
                    try:
                        self.signals.append(json.loads(line.strip()))
                    except:
                        pass
            print(f"  Signal universe: {len(self.signals)}")
        
        print()
        
    def analyze_closed_trades(self) -> Dict:
        """Deep analysis of all closed trades."""
        print("=" * 70)
        print("CLOSED TRADES ANALYSIS")
        print("=" * 70)
        
        if not self.closed_trades:
            print("  No closed trades to analyze")
            return {}
        
        alpha_trades = [t for t in self.closed_trades if t.get('bot_type', 'alpha') == 'alpha']
        beta_trades = [t for t in self.closed_trades if t.get('bot_type') == 'beta']
        
        print(f"\n  Total closed: {len(self.closed_trades)}")
        print(f"  Alpha trades: {len(alpha_trades)}")
        print(f"  Beta trades: {len(beta_trades)}")
        
        results = {
            'alpha': self._analyze_trade_set(alpha_trades, "ALPHA"),
            'beta': self._analyze_trade_set(beta_trades, "BETA"),
            'combined': self._analyze_trade_set(self.closed_trades, "COMBINED")
        }
        
        return results
    
    def _analyze_trade_set(self, trades: List[Dict], label: str) -> Dict:
        """Analyze a set of trades."""
        if not trades:
            return {}
        
        print(f"\n  --- {label} ANALYSIS ({len(trades)} trades) ---")
        
        total_pnl = sum(t.get('realized_pnl', t.get('pnl', 0)) or 0 for t in trades)
        winners = [t for t in trades if (t.get('realized_pnl', t.get('pnl', 0)) or 0) > 0]
        losers = [t for t in trades if (t.get('realized_pnl', t.get('pnl', 0)) or 0) < 0]
        
        win_rate = len(winners) / len(trades) * 100 if trades else 0
        avg_pnl = total_pnl / len(trades) if trades else 0
        avg_win = sum(t.get('realized_pnl', t.get('pnl', 0)) or 0 for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t.get('realized_pnl', t.get('pnl', 0)) or 0 for t in losers) / len(losers) if losers else 0
        
        print(f"  Total P&L: ${total_pnl:.2f}")
        print(f"  Win Rate: {win_rate:.1f}% ({len(winners)}/{len(trades)})")
        print(f"  Avg P&L: ${avg_pnl:.2f}")
        print(f"  Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}")
        
        if avg_loss != 0:
            rr_ratio = abs(avg_win / avg_loss)
            print(f"  Risk/Reward: {rr_ratio:.2f}")
        
        by_symbol = defaultdict(list)
        by_direction = defaultdict(list)
        by_strategy = defaultdict(list)
        by_hour = defaultdict(list)
        by_dow = defaultdict(list)
        
        for t in trades:
            symbol = t.get('symbol', 'UNKNOWN')
            direction = t.get('direction', t.get('side', 'UNKNOWN'))
            strategy = t.get('strategy', 'unknown')
            pnl = t.get('realized_pnl', t.get('pnl', 0)) or 0
            
            by_symbol[symbol].append(pnl)
            by_direction[direction].append(pnl)
            by_strategy[strategy].append(pnl)
            
            entry_time = t.get('entry_time', t.get('timestamp', ''))
            if entry_time:
                try:
                    if isinstance(entry_time, str):
                        dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromtimestamp(entry_time)
                    by_hour[dt.hour].append(pnl)
                    by_dow[dt.strftime('%A')].append(pnl)
                except:
                    pass
        
        print(f"\n  BY SYMBOL:")
        symbol_stats = {}
        for sym, pnls in sorted(by_symbol.items(), key=lambda x: sum(x[1]), reverse=True):
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100 if pnls else 0
            ev = total / len(pnls) if pnls else 0
            symbol_stats[sym] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
            status = "PROFITABLE" if total > 0 else "LOSING"
            print(f"    {sym}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        print(f"\n  BY DIRECTION:")
        direction_stats = {}
        for dir, pnls in sorted(by_direction.items(), key=lambda x: sum(x[1]), reverse=True):
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100 if pnls else 0
            ev = total / len(pnls) if pnls else 0
            direction_stats[dir] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
            status = "PROFITABLE" if total > 0 else "LOSING"
            print(f"    {dir}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        print(f"\n  BY STRATEGY:")
        strategy_stats = {}
        for strat, pnls in sorted(by_strategy.items(), key=lambda x: sum(x[1]), reverse=True):
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100 if pnls else 0
            ev = total / len(pnls) if pnls else 0
            strategy_stats[strat] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
            status = "PROFITABLE" if total > 0 else "LOSING"
            print(f"    {strat}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        print(f"\n  BY DAY OF WEEK:")
        dow_stats = {}
        dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for dow in dow_order:
            if dow in by_dow:
                pnls = by_dow[dow]
                total = sum(pnls)
                wins = len([p for p in pnls if p > 0])
                wr = wins / len(pnls) * 100 if pnls else 0
                dow_stats[dow] = {'total_pnl': total, 'win_rate': wr, 'n': len(pnls)}
                status = "PROFITABLE" if total > 0 else "LOSING"
                print(f"    {dow}: ${total:+.2f} | WR={wr:.0f}% | n={len(pnls)} [{status}]")
        
        print(f"\n  BY HOUR (UTC):")
        hour_stats = {}
        for hour in range(24):
            if hour in by_hour:
                pnls = by_hour[hour]
                total = sum(pnls)
                wins = len([p for p in pnls if p > 0])
                wr = wins / len(pnls) * 100 if pnls else 0
                hour_stats[hour] = {'total_pnl': total, 'win_rate': wr, 'n': len(pnls)}
                if len(pnls) >= 5:
                    status = "PROFITABLE" if total > 0 else "LOSING"
                    print(f"    {hour:02d}:00 UTC: ${total:+.2f} | WR={wr:.0f}% | n={len(pnls)} [{status}]")
        
        return {
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'avg_pnl': avg_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'by_symbol': symbol_stats,
            'by_direction': direction_stats,
            'by_strategy': strategy_stats,
            'by_dow': dow_stats,
            'by_hour': hour_stats
        }
    
    def analyze_enriched_decisions(self) -> Dict:
        """Analyze enriched decision data for signal quality."""
        print("\n" + "=" * 70)
        print("ENRICHED DECISIONS ANALYSIS")
        print("=" * 70)
        
        if not self.enriched_decisions:
            print("  No enriched decisions to analyze")
            return {}
        
        by_ofi_bucket = defaultdict(list)
        by_ensemble_bucket = defaultdict(list)
        by_alignment = defaultdict(list)
        
        for d in self.enriched_decisions:
            pnl = d.get('pnl', 0) or 0
            
            ofi = abs(d.get('ofi', 0) or 0)
            if ofi < 0.3:
                bucket = 'weak (<0.3)'
            elif ofi < 0.5:
                bucket = 'moderate (0.3-0.5)'
            elif ofi < 0.7:
                bucket = 'strong (0.5-0.7)'
            elif ofi < 0.9:
                bucket = 'very_strong (0.7-0.9)'
            else:
                bucket = 'extreme (≥0.9)'
            by_ofi_bucket[bucket].append(pnl)
            
            ensemble = abs(d.get('ensemble', d.get('composite', 0)) or 0)
            if ensemble < 0.03:
                ens_bucket = 'neutral (<0.03)'
            elif ensemble < 0.05:
                ens_bucket = 'weak (0.03-0.05)'
            elif ensemble < 0.08:
                ens_bucket = 'moderate (0.05-0.08)'
            elif ensemble < 0.12:
                ens_bucket = 'strong (0.08-0.12)'
            else:
                ens_bucket = 'extreme (≥0.12)'
            by_ensemble_bucket[ens_bucket].append(pnl)
            
            alignment = d.get('alignment', 'unknown')
            by_alignment[alignment].append(pnl)
        
        print(f"\n  BY OFI BUCKET:")
        ofi_stats = {}
        for bucket, pnls in sorted(by_ofi_bucket.items()):
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100 if pnls else 0
            ev = total / len(pnls) if pnls else 0
            ofi_stats[bucket] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
            status = "PROFITABLE" if total > 0 else "LOSING"
            print(f"    {bucket}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        print(f"\n  BY ENSEMBLE BUCKET:")
        ensemble_stats = {}
        for bucket, pnls in sorted(by_ensemble_bucket.items()):
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100 if pnls else 0
            ev = total / len(pnls) if pnls else 0
            ensemble_stats[bucket] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
            status = "PROFITABLE" if total > 0 else "LOSING"
            print(f"    {bucket}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        print(f"\n  BY INTELLIGENCE ALIGNMENT:")
        alignment_stats = {}
        for alignment, pnls in sorted(by_alignment.items(), key=lambda x: sum(x[1]), reverse=True):
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100 if pnls else 0
            ev = total / len(pnls) if pnls else 0
            alignment_stats[alignment] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
            status = "PROFITABLE" if total > 0 else "LOSING"
            print(f"    {alignment}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        return {
            'by_ofi': ofi_stats,
            'by_ensemble': ensemble_stats,
            'by_alignment': alignment_stats
        }
    
    def find_profitable_patterns(self) -> List[Dict]:
        """Identify specific profitable patterns from trades."""
        print("\n" + "=" * 70)
        print("PROFITABLE PATTERN DISCOVERY")
        print("=" * 70)
        
        patterns = defaultdict(list)
        
        for t in self.closed_trades:
            symbol = t.get('symbol', 'UNKNOWN')
            direction = t.get('direction', t.get('side', 'UNKNOWN'))
            strategy = t.get('strategy', 'unknown')
            pnl = t.get('realized_pnl', t.get('pnl', 0)) or 0
            
            context = t.get('signal_context', {})
            ofi = abs(context.get('ofi', 0) or 0)
            ensemble = abs(context.get('ensemble', 0) or 0)
            
            if ofi < 0.3:
                ofi_b = 'weak'
            elif ofi < 0.5:
                ofi_b = 'moderate'
            elif ofi < 0.7:
                ofi_b = 'strong'
            elif ofi < 0.9:
                ofi_b = 'very_strong'
            else:
                ofi_b = 'extreme'
            
            pattern_key = f"{symbol}|{direction}|{ofi_b}"
            patterns[pattern_key].append(pnl)
        
        profitable = []
        losing = []
        
        for pattern, pnls in patterns.items():
            if len(pnls) < 3:
                continue
            
            total = sum(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = wins / len(pnls) * 100
            ev = total / len(pnls)
            
            result = {
                'pattern': pattern,
                'total_pnl': total,
                'win_rate': wr,
                'ev': ev,
                'n': len(pnls)
            }
            
            if total > 0:
                profitable.append(result)
            else:
                losing.append(result)
        
        profitable.sort(key=lambda x: x['total_pnl'], reverse=True)
        losing.sort(key=lambda x: x['total_pnl'])
        
        print(f"\n  TOP PROFITABLE PATTERNS (n≥3):")
        for p in profitable[:15]:
            parts = p['pattern'].split('|')
            print(f"    {p['pattern']}: ${p['total_pnl']:+.2f} | WR={p['win_rate']:.0f}% | EV=${p['ev']:.2f} | n={p['n']}")
        
        print(f"\n  TOP LOSING PATTERNS (n≥3):")
        for p in losing[:15]:
            print(f"    {p['pattern']}: ${p['total_pnl']:+.2f} | WR={p['win_rate']:.0f}% | EV=${p['ev']:.2f} | n={p['n']}")
        
        return {'profitable': profitable, 'losing': losing}
    
    def analyze_hold_durations(self) -> Dict:
        """Analyze trade hold durations and exit timing."""
        print("\n" + "=" * 70)
        print("HOLD DURATION & EXIT TIMING ANALYSIS")
        print("=" * 70)
        
        durations = []
        
        for t in self.closed_trades:
            entry_time = t.get('entry_time', t.get('timestamp'))
            exit_time = t.get('exit_time', t.get('close_time'))
            pnl = t.get('realized_pnl', t.get('pnl', 0)) or 0
            
            if entry_time and exit_time:
                try:
                    if isinstance(entry_time, str):
                        entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    else:
                        entry_dt = datetime.fromtimestamp(entry_time)
                    
                    if isinstance(exit_time, str):
                        exit_dt = datetime.fromisoformat(exit_time.replace('Z', '+00:00'))
                    else:
                        exit_dt = datetime.fromtimestamp(exit_time)
                    
                    hold_seconds = (exit_dt - entry_dt).total_seconds()
                    durations.append({
                        'seconds': hold_seconds,
                        'pnl': pnl,
                        'symbol': t.get('symbol'),
                        'direction': t.get('direction', t.get('side'))
                    })
                except:
                    pass
        
        if not durations:
            print("  Insufficient duration data")
            return {}
        
        quick = [d for d in durations if d['seconds'] < 60]
        short = [d for d in durations if 60 <= d['seconds'] < 300]
        medium = [d for d in durations if 300 <= d['seconds'] < 900]
        long = [d for d in durations if d['seconds'] >= 900]
        
        buckets = [
            ('Quick (<1 min)', quick),
            ('Short (1-5 min)', short),
            ('Medium (5-15 min)', medium),
            ('Long (>15 min)', long)
        ]
        
        print(f"\n  PERFORMANCE BY HOLD DURATION:")
        duration_stats = {}
        for name, group in buckets:
            if group:
                pnls = [d['pnl'] for d in group]
                total = sum(pnls)
                wins = len([p for p in pnls if p > 0])
                wr = wins / len(pnls) * 100
                ev = total / len(pnls)
                duration_stats[name] = {'total_pnl': total, 'win_rate': wr, 'ev': ev, 'n': len(pnls)}
                status = "PROFITABLE" if total > 0 else "LOSING"
                print(f"    {name}: ${total:+.2f} | WR={wr:.0f}% | EV=${ev:.2f} | n={len(pnls)} [{status}]")
        
        avg_duration = statistics.mean([d['seconds'] for d in durations])
        median_duration = statistics.median([d['seconds'] for d in durations])
        
        print(f"\n  Duration Stats:")
        print(f"    Average hold: {avg_duration:.0f}s ({avg_duration/60:.1f} min)")
        print(f"    Median hold: {median_duration:.0f}s ({median_duration/60:.1f} min)")
        
        return duration_stats
    
    def generate_recommendations(self, trade_analysis: Dict, pattern_analysis: Dict, duration_analysis: Dict) -> List[str]:
        """Generate concrete optimization recommendations."""
        print("\n" + "=" * 70)
        print("OPTIMIZATION RECOMMENDATIONS")
        print("=" * 70)
        
        recommendations = []
        
        if pattern_analysis.get('profitable'):
            print("\n  [1] FOCUS ON PROFITABLE PATTERNS:")
            for p in pattern_analysis['profitable'][:5]:
                parts = p['pattern'].split('|')
                if len(parts) >= 3:
                    symbol, direction, ofi = parts[0], parts[1], parts[2]
                    rec = f"    PRIORITIZE: {symbol} {direction} when OFI={ofi} (${p['total_pnl']:+.2f}, WR={p['win_rate']:.0f}%)"
                    print(rec)
                    recommendations.append(f"Prioritize {symbol} {direction} with {ofi} OFI")
        
        if pattern_analysis.get('losing'):
            print("\n  [2] AVOID LOSING PATTERNS:")
            for p in pattern_analysis['losing'][:5]:
                parts = p['pattern'].split('|')
                if len(parts) >= 3:
                    symbol, direction, ofi = parts[0], parts[1], parts[2]
                    rec = f"    AVOID: {symbol} {direction} when OFI={ofi} (${p['total_pnl']:+.2f}, WR={p['win_rate']:.0f}%)"
                    print(rec)
                    recommendations.append(f"Block {symbol} {direction} with {ofi} OFI")
        
        print("\n  [3] HOLD DURATION ADJUSTMENTS:")
        if duration_analysis:
            profitable_durations = [(k, v) for k, v in duration_analysis.items() if v.get('total_pnl', 0) > 0]
            losing_durations = [(k, v) for k, v in duration_analysis.items() if v.get('total_pnl', 0) <= 0]
            
            for name, stats in profitable_durations:
                print(f"    EXTEND towards: {name} (EV=${stats['ev']:.2f})")
                recommendations.append(f"Target {name} hold times")
            
            for name, stats in losing_durations:
                print(f"    AVOID: {name} (EV=${stats['ev']:.2f})")
                recommendations.append(f"Avoid {name} exits")
        
        print("\n  [4] THRESHOLD ADJUSTMENTS:")
        print("    - Raise OFI threshold to ≥0.7 for entries (filter weak signals)")
        print("    - Require Ensemble ≥0.08 for confirmation (stronger conviction)")
        print("    - Implement session filters: Avoid Sunday, Asia-night hours")
        print("    - Increase R:R targets from 1.5 to 2.5 minimum")
        
        recommendations.extend([
            "Raise OFI threshold to ≥0.7",
            "Require Ensemble ≥0.08",
            "Block Sunday trading",
            "Block Asia-night session (00:00-06:00 UTC)",
            "Increase R:R target to 2.5"
        ])
        
        print("\n  [5] BETA STRATEGY ADJUSTMENTS:")
        print("    - Restrict Beta to DOTUSDT and BNBUSDT only (proven inversion edge)")
        print("    - Halve Beta position sizes (reduce drawdown contribution)")
        print("    - Require independent intel alignment before Beta inversion")
        
        recommendations.extend([
            "Restrict Beta to DOT/BNB symbols",
            "Reduce Beta position sizes by 50%",
            "Require strong intel alignment for Beta"
        ])
        
        return recommendations
    
    def run_full_analysis(self) -> Dict:
        """Run complete profitability analysis."""
        print("\n" + "=" * 70)
        print("DEEP PROFITABILITY ANALYSIS")
        print(f"Run Time: {datetime.now().isoformat()}")
        print("=" * 70)
        
        self.load_all_data()
        
        trade_analysis = self.analyze_closed_trades()
        enriched_analysis = self.analyze_enriched_decisions()
        pattern_analysis = self.find_profitable_patterns()
        duration_analysis = self.analyze_hold_durations()
        recommendations = self.generate_recommendations(trade_analysis, pattern_analysis, duration_analysis)
        
        print("\n" + "=" * 70)
        print("EXECUTIVE SUMMARY")
        print("=" * 70)
        
        combined = trade_analysis.get('combined', {})
        if combined:
            print(f"\n  Overall P&L: ${combined.get('total_pnl', 0):.2f}")
            print(f"  Overall Win Rate: {combined.get('win_rate', 0):.1f}%")
            print(f"  Expected Value: ${combined.get('avg_pnl', 0):.2f} per trade")
        
        alpha = trade_analysis.get('alpha', {})
        if alpha:
            print(f"\n  Alpha Bot: ${alpha.get('total_pnl', 0):.2f} | WR={alpha.get('win_rate', 0):.1f}%")
        
        beta = trade_analysis.get('beta', {})
        if beta:
            print(f"  Beta Bot: ${beta.get('total_pnl', 0):.2f} | WR={beta.get('win_rate', 0):.1f}%")
        
        print(f"\n  Profitable Patterns Found: {len(pattern_analysis.get('profitable', []))}")
        print(f"  Losing Patterns Found: {len(pattern_analysis.get('losing', []))}")
        print(f"  Recommendations Generated: {len(recommendations)}")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'trade_analysis': trade_analysis,
            'enriched_analysis': enriched_analysis,
            'pattern_analysis': pattern_analysis,
            'duration_analysis': duration_analysis,
            'recommendations': recommendations
        }
        
        Path("reports").mkdir(exist_ok=True)
        with open("reports/deep_profitability_analysis.json", 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n  Full report saved to: reports/deep_profitability_analysis.json")
        
        return results


if __name__ == "__main__":
    analyzer = DeepProfitabilityAnalyzer()
    analyzer.run_full_analysis()
