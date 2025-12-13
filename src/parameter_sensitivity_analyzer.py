#!/usr/bin/env python3
"""
PARAMETER SENSITIVITY ANALYZER - "What-If" Framework
=====================================================
Counterfactual simulator that replays enriched_decisions with parameter sweeps
to show how adjustments impact win rate and profitability.

Instead of "disable X", this tool shows:
- "If OFI threshold was 0.6 instead of 0.5, win rate would be 45% vs 38%"
- "Ensemble floor 0.1 vs 0.05: +$127 improvement"

Usage:
    python src/parameter_sensitivity_analyzer.py
    python src/parameter_sensitivity_analyzer.py --focus OFI
    python src/parameter_sensitivity_analyzer.py --symbol BTCUSDT
    python src/parameter_sensitivity_analyzer.py --export
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import numpy as np
except ImportError:
    np = None


class ParameterSensitivityAnalyzer:
    """
    What-if analysis for trading parameters.
    Replays historical trades with different parameter configurations.
    """
    
    PARAMETER_SWEEPS = {
        "ofi_threshold": {
            "description": "Minimum OFI strength to enter trade",
            "values": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
            "current": 0.5,
            "field": "ofi"
        },
        "ensemble_floor": {
            "description": "Minimum ensemble alignment score",
            "values": [-0.2, -0.1, 0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08],
            "current": 0.05,
            "field": "ensemble"
        },
        "leverage_multiplier": {
            "description": "Leverage applied to positions",
            "values": [1, 2, 3, 5, 7, 10],
            "current": 5,
            "field": None  # Applied to P&L calculation
        }
    }
    
    DAY_OF_WEEK_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    REGIME_WEIGHTS = {
        "ofi_weight_by_regime": {
            "description": "OFI signal weight by market regime",
            "values": {"Stable": [0.5, 0.75, 1.0], "Volatile": [0.3, 0.5, 0.7], "Trending": [0.7, 1.0, 1.2]},
            "current": {"Stable": 1.0, "Volatile": 0.5, "Trending": 0.7}
        }
    }
    
    def __init__(self, decisions_path: str = "logs/enriched_decisions.jsonl"):
        self.decisions_path = os.path.join(PROJECT_ROOT, decisions_path)
        self.decisions = []
        self.current_config = {
            "ofi_threshold": 0.5,
            "ensemble_floor": 0.05,
            "leverage_multiplier": 5
        }
        
    def load_decisions(self, min_days: int = None) -> int:
        """Load enriched decisions from JSONL file."""
        self.decisions = []
        
        if not os.path.exists(self.decisions_path):
            print(f"[WARN] No decisions file at {self.decisions_path}")
            return 0
            
        cutoff_ts = 0
        if min_days:
            cutoff_ts = int(datetime.utcnow().timestamp()) - (min_days * 86400)
            
        with open(self.decisions_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if min_days and d.get('ts', 0) < cutoff_ts:
                        continue
                    self.decisions.append(d)
                except json.JSONDecodeError:
                    continue
                    
        print(f"[INFO] Loaded {len(self.decisions)} decisions")
        return len(self.decisions)
    
    def _extract_features(self, decision: Dict) -> Dict:
        """Extract signal features from decision record."""
        sig = decision.get('signal_ctx', {})
        out = decision.get('outcome', {})
        
        return {
            "symbol": decision.get('symbol', 'UNKNOWN'),
            "ofi": abs(sig.get('ofi', 0)),  # OFI uses absolute value (strength)
            "ofi_raw": sig.get('ofi', 0),
            "ensemble": sig.get('ensemble', 0),  # Ensemble uses signed value (direction alignment)
            "regime": sig.get('regime', 'Unknown'),
            "side": sig.get('side', 'UNKNOWN'),
            "pnl_usd": out.get('pnl_usd', 0),
            "pnl_pct": out.get('pnl_pct', 0),
            "leverage": out.get('leverage', 5),
            "fees": out.get('fees', 0),
            "ts": decision.get('ts', 0)
        }
    
    def simulate_parameter(self, param_name: str, param_value: float, 
                          symbol_filter: str = None, regime_filter: str = None) -> Dict:
        """
        Simulate trading with a specific parameter value.
        Returns win rate, total P&L, and trade count.
        
        NOTE: Ensemble floor uses SIGNED values, requiring ensemble to be >= floor.
        Positive floors filter out weak/negative alignment.
        Negative floors allow contrarian trades with proper alignment.
        """
        sweep = self.PARAMETER_SWEEPS.get(param_name, {})
        field = sweep.get('field')
        
        trades_taken = []
        trades_skipped = []
        
        for dec in self.decisions:
            feat = self._extract_features(dec)
            
            # Apply filters
            if symbol_filter and feat['symbol'] != symbol_filter:
                continue
            if regime_filter and feat['regime'] != regime_filter:
                continue
            
            # Check if trade passes threshold
            if param_name == "ofi_threshold":
                if feat['ofi'] >= param_value:
                    trades_taken.append(feat)
                else:
                    trades_skipped.append(feat)
                    
            elif param_name == "ensemble_floor":
                # Use SIGNED ensemble: require alignment >= floor
                # Positive floor = require positive ensemble alignment
                # For directional trades, ensemble should match direction
                if feat['ensemble'] >= param_value:
                    trades_taken.append(feat)
                else:
                    trades_skipped.append(feat)
                    
            elif param_name == "leverage_multiplier":
                # Scale P&L proportionally based on counterfactual leverage
                # Uses percentage return * new leverage to approximate
                adjusted_feat = feat.copy()
                pnl_pct = feat.get('pnl_pct', 0) / 100  # Convert to decimal
                # Reconstruct notional from P&L and percentage
                # If pnl_pct > 0, notional = pnl_usd / pnl_pct
                if abs(pnl_pct) > 0.0001:
                    base_notional = abs(feat['pnl_usd'] / pnl_pct)
                    new_pnl = pnl_pct * base_notional * (param_value / 5)  # Base leverage is 5x
                    adjusted_feat['pnl_usd'] = new_pnl
                else:
                    # Small P&L, scale linearly (less accurate)
                    adjusted_feat['pnl_usd'] = feat['pnl_usd'] * (param_value / 5)
                trades_taken.append(adjusted_feat)
                
        # Calculate metrics
        total_pnl = sum(t['pnl_usd'] for t in trades_taken)
        wins = len([t for t in trades_taken if t['pnl_usd'] > 0])
        losses = len([t for t in trades_taken if t['pnl_usd'] <= 0])
        trade_count = len(trades_taken)
        
        win_rate = (wins / trade_count * 100) if trade_count > 0 else 0
        avg_pnl = total_pnl / trade_count if trade_count > 0 else 0
        
        # Calculate skip opportunity cost (what we missed)
        skip_pnl = sum(t['pnl_usd'] for t in trades_skipped)
        skip_wins = len([t for t in trades_skipped if t['pnl_usd'] > 0])
        
        return {
            "param_name": param_name,
            "param_value": param_value,
            "trades_taken": trade_count,
            "trades_skipped": len(trades_skipped),
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(avg_pnl, 4),
            "wins": wins,
            "losses": losses,
            "skipped_pnl": round(skip_pnl, 2),
            "skipped_wins": skip_wins
        }
    
    def sweep_parameter(self, param_name: str, symbol_filter: str = None,
                       regime_filter: str = None) -> List[Dict]:
        """Run full sweep of a parameter and return comparative results."""
        sweep = self.PARAMETER_SWEEPS.get(param_name)
        if not sweep:
            print(f"[ERROR] Unknown parameter: {param_name}")
            return []
            
        results = []
        for value in sweep['values']:
            result = self.simulate_parameter(param_name, value, 
                                            symbol_filter, regime_filter)
            result['is_current'] = (value == sweep['current'])
            results.append(result)
            
        return results
    
    def find_optimal_parameters(self, symbol_filter: str = None,
                               regime_filter: str = None) -> Dict:
        """Find optimal parameter combination by sweeping all parameters."""
        optimals = {}
        
        for param_name, sweep in self.PARAMETER_SWEEPS.items():
            results = self.sweep_parameter(param_name, symbol_filter, regime_filter)
            
            if not results:
                continue
                
            # Find best by win rate (with minimum trade threshold)
            valid_results = [r for r in results if r['trades_taken'] >= 10]
            if valid_results:
                best_wr = max(valid_results, key=lambda x: x['win_rate'])
                best_pnl = max(valid_results, key=lambda x: x['total_pnl'])
                current = next((r for r in results if r['is_current']), results[0])
                
                optimals[param_name] = {
                    "current_value": sweep['current'],
                    "current_wr": current['win_rate'],
                    "current_pnl": current['total_pnl'],
                    "optimal_wr_value": best_wr['param_value'],
                    "optimal_wr": best_wr['win_rate'],
                    "optimal_wr_pnl": best_wr['total_pnl'],
                    "optimal_pnl_value": best_pnl['param_value'],
                    "optimal_pnl": best_pnl['total_pnl'],
                    "wr_improvement": round(best_wr['win_rate'] - current['win_rate'], 2),
                    "pnl_improvement": round(best_pnl['total_pnl'] - current['total_pnl'], 2),
                    "all_results": results
                }
                
        return optimals
    
    def generate_sensitivity_report(self, symbol_filter: str = None,
                                   regime_filter: str = None) -> str:
        """Generate human-readable sensitivity report."""
        lines = []
        lines.append("=" * 70)
        lines.append("PARAMETER SENSITIVITY ANALYSIS - What-If Framework")
        lines.append("=" * 70)
        lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
        lines.append(f"Total Decisions: {len(self.decisions)}")
        if symbol_filter:
            lines.append(f"Symbol Filter: {symbol_filter}")
        if regime_filter:
            lines.append(f"Regime Filter: {regime_filter}")
        lines.append("")
        
        optimals = self.find_optimal_parameters(symbol_filter, regime_filter)
        
        for param_name, data in optimals.items():
            sweep = self.PARAMETER_SWEEPS[param_name]
            lines.append("-" * 70)
            lines.append(f"PARAMETER: {param_name}")
            lines.append(f"Description: {sweep['description']}")
            lines.append("")
            
            # Current vs Optimal comparison
            lines.append("CURRENT vs OPTIMAL:")
            lines.append(f"  Current Value: {data['current_value']}")
            lines.append(f"    Win Rate: {data['current_wr']:.1f}%")
            lines.append(f"    Total P&L: ${data['current_pnl']:.2f}")
            lines.append("")
            
            if data['wr_improvement'] > 0:
                lines.append(f"  OPTIMAL for Win Rate: {data['optimal_wr_value']}")
                lines.append(f"    Win Rate: {data['optimal_wr']:.1f}% (+{data['wr_improvement']:.1f}%)")
                lines.append(f"    Total P&L: ${data['optimal_wr_pnl']:.2f}")
            else:
                lines.append(f"  Current setting is optimal for win rate")
                
            if data['pnl_improvement'] > 0:
                lines.append(f"  OPTIMAL for P&L: {data['optimal_pnl_value']}")
                lines.append(f"    Total P&L: ${data['optimal_pnl']:.2f} (+${data['pnl_improvement']:.2f})")
            else:
                lines.append(f"  Current setting is optimal for P&L")
            
            lines.append("")
            lines.append("FULL SWEEP RESULTS:")
            lines.append(f"  {'Value':>8} | {'Trades':>7} | {'WR%':>6} | {'P&L':>10} | {'Avg P&L':>8}")
            lines.append("  " + "-" * 50)
            
            for r in data['all_results']:
                marker = " *" if r['is_current'] else "  "
                lines.append(f"{marker}{r['param_value']:>7} | {r['trades_taken']:>7} | "
                           f"{r['win_rate']:>5.1f}% | ${r['total_pnl']:>9.2f} | ${r['avg_pnl']:>7.4f}")
            
            lines.append("  * = current setting")
            lines.append("")
            
        return "\n".join(lines)
    
    def analyze_day_of_week(self) -> Dict:
        """
        Analyze performance by day of week.
        Returns win rate and P&L for each day.
        """
        from collections import defaultdict
        
        day_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        
        for dec in self.decisions:
            feat = self._extract_features(dec)
            ts = feat.get('ts', 0)
            if ts <= 0:
                continue
                
            # Get day of week (0=Monday, 6=Sunday)
            day_idx = datetime.utcfromtimestamp(ts).weekday()
            day_name = self.DAY_OF_WEEK_NAMES[day_idx]
            
            day_stats[day_name]["trades"] += 1
            day_stats[day_name]["pnl"] += feat['pnl_usd']
            if feat['pnl_usd'] > 0:
                day_stats[day_name]["wins"] += 1
        
        # Calculate win rates
        results = {}
        for day in self.DAY_OF_WEEK_NAMES:
            stats = day_stats[day]
            trades = stats["trades"]
            wr = (stats["wins"] / trades * 100) if trades > 0 else 0
            results[day] = {
                "trades": trades,
                "wins": stats["wins"],
                "win_rate": round(wr, 2),
                "total_pnl": round(stats["pnl"], 2),
                "avg_pnl": round(stats["pnl"] / trades, 4) if trades > 0 else 0
            }
            
        return results
    
    def generate_day_of_week_report(self) -> str:
        """Generate day-of-week performance report."""
        lines = []
        lines.append("\nDAY OF WEEK ANALYSIS")
        lines.append("=" * 60)
        
        dow_data = self.analyze_day_of_week()
        
        # Find best and worst days
        valid_days = [(d, v) for d, v in dow_data.items() if v['trades'] >= 5]
        if valid_days:
            best_day = max(valid_days, key=lambda x: x[1]['win_rate'])
            worst_day = min(valid_days, key=lambda x: x[1]['win_rate'])
            lines.append(f"Best Day: {best_day[0]} ({best_day[1]['win_rate']:.1f}% WR, ${best_day[1]['total_pnl']:.2f})")
            lines.append(f"Worst Day: {worst_day[0]} ({worst_day[1]['win_rate']:.1f}% WR, ${worst_day[1]['total_pnl']:.2f})")
            lines.append("")
        
        lines.append(f"{'Day':>12} | {'Trades':>7} | {'WR%':>6} | {'P&L':>10} | {'Avg P&L':>8}")
        lines.append("-" * 55)
        
        for day in self.DAY_OF_WEEK_NAMES:
            data = dow_data[day]
            lines.append(f"{day:>12} | {data['trades']:>7} | {data['win_rate']:>5.1f}% | "
                        f"${data['total_pnl']:>9.2f} | ${data['avg_pnl']:>7.4f}")
        
        lines.append("")
        
        # Recommendations
        if valid_days:
            profit_days = [(d, v) for d, v in dow_data.items() if v['trades'] >= 5 and v['total_pnl'] > 0]
            loss_days = [(d, v) for d, v in dow_data.items() if v['trades'] >= 5 and v['total_pnl'] < -50]
            
            lines.append("RECOMMENDATIONS:")
            if profit_days:
                lines.append(f"  INCREASE trading on: {', '.join([d[0] for d in profit_days])}")
            if loss_days:
                lines.append(f"  REDUCE/SKIP trading on: {', '.join([d[0] for d in loss_days])}")
                
        return "\n".join(lines)
    
    def multi_dimensional_sweep(self, param1: str, param2: str,
                               symbol_filter: str = None) -> Dict:
        """
        Sweep two parameters simultaneously to find interaction effects.
        """
        sweep1 = self.PARAMETER_SWEEPS.get(param1)
        sweep2 = self.PARAMETER_SWEEPS.get(param2)
        
        if not sweep1 or not sweep2:
            return {}
            
        results = {}
        
        for v1 in sweep1['values']:
            results[v1] = {}
            for v2 in sweep2['values']:
                # Filter decisions that pass BOTH thresholds
                trades = []
                for dec in self.decisions:
                    feat = self._extract_features(dec)
                    
                    if symbol_filter and feat['symbol'] != symbol_filter:
                        continue
                        
                    # Check param1 (use signed ensemble for floor comparison)
                    if param1 == "ofi_threshold" and feat['ofi'] < v1:
                        continue
                    if param1 == "ensemble_floor" and feat['ensemble'] < v1:
                        continue
                        
                    # Check param2 (use signed ensemble for floor comparison)
                    if param2 == "ofi_threshold" and feat['ofi'] < v2:
                        continue
                    if param2 == "ensemble_floor" and feat['ensemble'] < v2:
                        continue
                        
                    trades.append(feat)
                
                # Calculate metrics
                total_pnl = sum(t['pnl_usd'] for t in trades)
                wins = len([t for t in trades if t['pnl_usd'] > 0])
                count = len(trades)
                wr = (wins / count * 100) if count > 0 else 0
                
                results[v1][v2] = {
                    "trades": count,
                    "win_rate": round(wr, 2),
                    "total_pnl": round(total_pnl, 2)
                }
                
        return {
            "param1": param1,
            "param2": param2,
            "results": results
        }
    
    def generate_heatmap_report(self, param1: str = "ofi_threshold",
                               param2: str = "ensemble_floor") -> str:
        """Generate ASCII heatmap of two-parameter interaction."""
        data = self.multi_dimensional_sweep(param1, param2)
        if not data:
            return "No data for heatmap"
            
        lines = []
        lines.append(f"\nHEATMAP: {param1} vs {param2}")
        lines.append("=" * 60)
        
        sweep1 = self.PARAMETER_SWEEPS[param1]
        sweep2 = self.PARAMETER_SWEEPS[param2]
        
        # Header row
        header = f"{'':>8} |"
        for v2 in sweep2['values']:
            header += f" {v2:>7} |"
        lines.append(header)
        lines.append("-" * len(header))
        
        # Data rows (Win Rate)
        lines.append("WIN RATE:")
        for v1 in sweep1['values']:
            row = f"{v1:>7} |"
            for v2 in sweep2['values']:
                cell = data['results'].get(v1, {}).get(v2, {})
                wr = cell.get('win_rate', 0)
                row += f" {wr:>5.1f}% |"
            lines.append(row)
            
        lines.append("")
        lines.append("TOTAL P&L:")
        for v1 in sweep1['values']:
            row = f"{v1:>7} |"
            for v2 in sweep2['values']:
                cell = data['results'].get(v1, {}).get(v2, {})
                pnl = cell.get('total_pnl', 0)
                row += f" ${pnl:>5.0f} |"
            lines.append(row)
            
        return "\n".join(lines)
    
    def export_to_json(self, filepath: str = "reports/parameter_sensitivity.json"):
        """Export analysis results to JSON."""
        output_path = os.path.join(PROJECT_ROOT, filepath)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        data = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "total_decisions": len(self.decisions),
            "parameter_sweeps": {},
            "optimal_settings": self.find_optimal_parameters(),
            "multi_dimensional": {
                "ofi_vs_ensemble": self.multi_dimensional_sweep("ofi_threshold", "ensemble_floor")
            }
        }
        
        for param in self.PARAMETER_SWEEPS:
            data["parameter_sweeps"][param] = self.sweep_parameter(param)
            
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
            
        print(f"[INFO] Exported to {output_path}")
        return output_path


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Parameter Sensitivity Analyzer")
    parser.add_argument("--focus", type=str, help="Focus on specific parameter (ofi_threshold, ensemble_floor)")
    parser.add_argument("--symbol", type=str, help="Filter by symbol")
    parser.add_argument("--regime", type=str, help="Filter by regime")
    parser.add_argument("--days", type=int, default=7, help="Days of history to analyze")
    parser.add_argument("--export", action="store_true", help="Export to JSON")
    parser.add_argument("--heatmap", action="store_true", help="Show 2D heatmap")
    parser.add_argument("--dow", action="store_true", help="Show day-of-week analysis")
    
    args = parser.parse_args()
    
    analyzer = ParameterSensitivityAnalyzer()
    count = analyzer.load_decisions(min_days=args.days)
    
    if count == 0:
        print("[ERROR] No decisions to analyze")
        return
        
    if args.focus:
        results = analyzer.sweep_parameter(args.focus, args.symbol, args.regime)
        print(f"\nParameter: {args.focus}")
        print("-" * 60)
        for r in results:
            marker = " *" if r['is_current'] else "  "
            print(f"{marker}{r['param_value']:>7} | Trades: {r['trades_taken']:>5} | "
                  f"WR: {r['win_rate']:>5.1f}% | P&L: ${r['total_pnl']:>8.2f}")
        print("  * = current setting")
    else:
        report = analyzer.generate_sensitivity_report(args.symbol, args.regime)
        print(report)
        
    if args.heatmap:
        heatmap = analyzer.generate_heatmap_report()
        print(heatmap)
        
    if args.dow:
        dow_report = analyzer.generate_day_of_week_report()
        print(dow_report)
        
    if args.export:
        analyzer.export_to_json()


if __name__ == "__main__":
    main()
