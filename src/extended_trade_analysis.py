#!/usr/bin/env python3
"""
Extended Trade Analysis - Full Historical Deep Dive
====================================================
Analyzes ALL trades across the complete trading history
to identify trends, patterns, and root causes.
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any

class ExtendedTradeAnalysis:
    """Extended analysis covering all historical data"""
    
    OFI_THRESHOLDS = {
        "extreme": 0.9,
        "very_strong": 0.7,
        "strong": 0.5,
        "moderate": 0.3,
        "weak": 0.0
    }
    
    def __init__(self):
        self.all_trades = []
        self.positions_data = None
        self.enriched_data = []
        
    def bucket_ofi(self, ofi_value: float) -> str:
        """Convert raw OFI value to bucket"""
        if ofi_value is None:
            return "unknown"
        abs_ofi = abs(ofi_value)
        if abs_ofi >= self.OFI_THRESHOLDS["extreme"]:
            return "extreme"
        elif abs_ofi >= self.OFI_THRESHOLDS["very_strong"]:
            return "very_strong"
        elif abs_ofi >= self.OFI_THRESHOLDS["strong"]:
            return "strong"
        elif abs_ofi >= self.OFI_THRESHOLDS["moderate"]:
            return "moderate"
        else:
            return "weak"
    
    def parse_timestamp(self, ts_val) -> datetime:
        """Parse various timestamp formats"""
        if ts_val is None:
            return None
        try:
            if isinstance(ts_val, str):
                return datetime.fromisoformat(ts_val.replace('Z', '+00:00').replace('+00:00', ''))
            elif isinstance(ts_val, (int, float)):
                if ts_val > 1e12:
                    ts_val = ts_val / 1000
                return datetime.fromtimestamp(ts_val)
        except:
            pass
        return None
    
    def get_session(self, dt: datetime) -> str:
        """Determine trading session from datetime"""
        if dt is None:
            return "unknown"
        hour = dt.hour
        if 5 <= hour < 9:
            return "asia_morning"
        elif 9 <= hour < 13:
            return "europe_morning"
        elif 13 <= hour < 16:
            return "us_morning"
        elif 16 <= hour < 20:
            return "us_afternoon"
        elif 20 <= hour < 24:
            return "evening"
        else:
            return "asia_night"
    
    def load_all_data(self):
        """Load all data sources"""
        print("=" * 70)
        print("LOADING ALL DATA SOURCES")
        print("=" * 70)
        
        if os.path.exists("logs/portfolio.json"):
            try:
                with open("logs/portfolio.json", 'r') as f:
                    data = json.load(f)
                trades = data.get("trades", [])
                for t in trades:
                    t["_source"] = "portfolio"
                self.all_trades.extend(trades)
                print(f"   ✅ portfolio.json: {len(trades)} trades")
            except Exception as e:
                print(f"   ❌ portfolio.json: {e}")
        
        if os.path.exists("logs/positions_futures.json"):
            try:
                with open("logs/positions_futures.json", 'r') as f:
                    self.positions_data = json.load(f)
                closed = self.positions_data.get("closed_positions", [])
                for p in closed:
                    p["_source"] = "positions_futures"
                print(f"   ✅ positions_futures.json: {len(closed)} closed positions")
            except Exception as e:
                print(f"   ❌ positions_futures.json: {e}")
        
        if os.path.exists("logs/enriched_decisions.jsonl"):
            try:
                with open("logs/enriched_decisions.jsonl", 'r') as f:
                    for line in f:
                        if line.strip():
                            self.enriched_data.append(json.loads(line))
                print(f"   ✅ enriched_decisions.jsonl: {len(self.enriched_data)} records")
            except Exception as e:
                print(f"   ❌ enriched_decisions.jsonl: {e}")
        
        print(f"\n📊 TOTAL DATA LOADED:")
        print(f"   - Portfolio trades: {len(self.all_trades)}")
        print(f"   - Closed positions: {len(self.positions_data.get('closed_positions', [])) if self.positions_data else 0}")
        print(f"   - Enriched decisions: {len(self.enriched_data)}")
    
    def analyze_portfolio_trades(self) -> Dict:
        """Analyze all trades from portfolio.json (most complete data)"""
        print("\n" + "=" * 70)
        print("FULL PORTFOLIO ANALYSIS (10,665 trades)")
        print("=" * 70)
        
        results = {
            "overall": {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0.0, "total_fees": 0.0},
            "by_symbol": defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "fees": 0.0}),
            "by_strategy": defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "fees": 0.0}),
            "by_side": defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0}),
            "by_session": defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0}),
            "by_date": defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "fees": 0.0}),
            "time_range": {"first": None, "last": None}
        }
        
        for trade in self.all_trades:
            pnl = float(trade.get("profit", trade.get("pnl", trade.get("realized_pnl", 0))))
            fees = float(trade.get("fees", trade.get("fee", 0)))
            is_win = pnl > 0
            
            results["overall"]["total"] += 1
            results["overall"]["total_pnl"] += pnl
            results["overall"]["total_fees"] += fees
            if is_win:
                results["overall"]["wins"] += 1
            else:
                results["overall"]["losses"] += 1
            
            symbol = trade.get("symbol", "unknown")
            results["by_symbol"][symbol]["count"] += 1
            results["by_symbol"][symbol]["pnl"] += pnl
            results["by_symbol"][symbol]["fees"] += fees
            if is_win:
                results["by_symbol"][symbol]["wins"] += 1
            
            strategy = trade.get("strategy", "unknown")
            results["by_strategy"][strategy]["count"] += 1
            results["by_strategy"][strategy]["pnl"] += pnl
            results["by_strategy"][strategy]["fees"] += fees
            if is_win:
                results["by_strategy"][strategy]["wins"] += 1
            
            side = trade.get("side", "unknown").upper()
            results["by_side"][side]["count"] += 1
            results["by_side"][side]["pnl"] += pnl
            if is_win:
                results["by_side"][side]["wins"] += 1
            
            ts = trade.get("timestamp", trade.get("entry_time", trade.get("ts")))
            dt = self.parse_timestamp(ts)
            if dt:
                session = self.get_session(dt)
                results["by_session"][session]["count"] += 1
                results["by_session"][session]["pnl"] += pnl
                if is_win:
                    results["by_session"][session]["wins"] += 1
                
                date_str = dt.strftime("%Y-%m-%d")
                results["by_date"][date_str]["count"] += 1
                results["by_date"][date_str]["pnl"] += pnl
                results["by_date"][date_str]["fees"] += fees
                if is_win:
                    results["by_date"][date_str]["wins"] += 1
                
                if results["time_range"]["first"] is None or dt < results["time_range"]["first"]:
                    results["time_range"]["first"] = dt
                if results["time_range"]["last"] is None or dt > results["time_range"]["last"]:
                    results["time_range"]["last"] = dt
        
        total = results["overall"]["total"]
        win_rate = (results["overall"]["wins"] / total * 100) if total > 0 else 0
        net_pnl = results["overall"]["total_pnl"] - results["overall"]["total_fees"]
        
        print(f"\n📅 TIME RANGE:")
        if results["time_range"]["first"]:
            print(f"   First trade: {results['time_range']['first']}")
            print(f"   Last trade: {results['time_range']['last']}")
            days = (results["time_range"]["last"] - results["time_range"]["first"]).days + 1
            print(f"   Trading days: {days}")
        
        print(f"\n📊 OVERALL PERFORMANCE:")
        print(f"   - Total trades: {total}")
        print(f"   - Wins: {results['overall']['wins']} | Losses: {results['overall']['losses']}")
        print(f"   - Win Rate: {win_rate:.1f}%")
        print(f"   - Gross P&L: ${results['overall']['total_pnl']:.2f}")
        print(f"   - Total Fees: ${results['overall']['total_fees']:.2f}")
        print(f"   - Net P&L: ${net_pnl:.2f}")
        print(f"   - Avg P&L/trade: ${results['overall']['total_pnl']/total:.2f}" if total > 0 else "")
        
        print(f"\n📈 BY STRATEGY (sorted by P&L):")
        sorted_strategies = sorted(results["by_strategy"].items(), key=lambda x: -x[1]["pnl"])
        for strategy, data in sorted_strategies[:10]:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            net = data["pnl"] - data["fees"]
            print(f"   {strategy}: n={data['count']}, WR={wr:.1f}%, Gross=${data['pnl']:.2f}, Net=${net:.2f}")
        
        print(f"\n🪙 BY SYMBOL - TOP 5 (Best Net P&L):")
        sorted_symbols = sorted(results["by_symbol"].items(), key=lambda x: x[1]["pnl"] - x[1]["fees"], reverse=True)
        for symbol, data in sorted_symbols[:5]:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            net = data["pnl"] - data["fees"]
            print(f"   {symbol}: n={data['count']}, WR={wr:.1f}%, Gross=${data['pnl']:.2f}, Net=${net:.2f}")
        
        print(f"\n💀 BY SYMBOL - BOTTOM 5 (Worst Net P&L):")
        for symbol, data in sorted_symbols[-5:]:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            net = data["pnl"] - data["fees"]
            print(f"   {symbol}: n={data['count']}, WR={wr:.1f}%, Gross=${data['pnl']:.2f}, Net=${net:.2f}")
        
        print(f"\n↕️ BY SIDE:")
        for side, data in sorted(results["by_side"].items()):
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   {side}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n⏰ BY SESSION:")
        for session, data in sorted(results["by_session"].items(), key=lambda x: -x[1]["pnl"]):
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   {session}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        return results
    
    def analyze_daily_trends(self, portfolio_results: Dict):
        """Analyze daily P&L trends"""
        print("\n" + "=" * 70)
        print("DAILY P&L TREND ANALYSIS")
        print("=" * 70)
        
        by_date = portfolio_results.get("by_date", {})
        if not by_date:
            print("   No daily data available")
            return
        
        sorted_dates = sorted(by_date.items())
        
        cumulative_pnl = 0.0
        cumulative_fees = 0.0
        daily_pnls = []
        
        print(f"\n📅 DAILY BREAKDOWN:")
        print(f"{'Date':<12} {'Trades':>7} {'WR%':>6} {'Gross':>10} {'Fees':>8} {'Net':>10} {'Cumul':>10}")
        print("-" * 70)
        
        for date_str, data in sorted_dates:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            net = data["pnl"] - data["fees"]
            cumulative_pnl += data["pnl"]
            cumulative_fees += data["fees"]
            cumulative_net = cumulative_pnl - cumulative_fees
            daily_pnls.append(net)
            
            print(f"{date_str:<12} {data['count']:>7} {wr:>5.1f}% ${data['pnl']:>8.2f} ${data['fees']:>6.2f} ${net:>8.2f} ${cumulative_net:>8.2f}")
        
        if daily_pnls:
            positive_days = sum(1 for p in daily_pnls if p > 0)
            negative_days = sum(1 for p in daily_pnls if p < 0)
            best_day = max(daily_pnls)
            worst_day = min(daily_pnls)
            avg_day = sum(daily_pnls) / len(daily_pnls)
            
            print(f"\n📊 DAILY STATISTICS:")
            print(f"   - Total days: {len(daily_pnls)}")
            print(f"   - Positive days: {positive_days} ({positive_days/len(daily_pnls)*100:.1f}%)")
            print(f"   - Negative days: {negative_days} ({negative_days/len(daily_pnls)*100:.1f}%)")
            print(f"   - Best day: ${best_day:.2f}")
            print(f"   - Worst day: ${worst_day:.2f}")
            print(f"   - Average day: ${avg_day:.2f}")
    
    def analyze_close_reasons(self):
        """Analyze why positions are being closed"""
        print("\n" + "=" * 70)
        print("CLOSE REASON ANALYSIS (from positions_futures.json)")
        print("=" * 70)
        
        if not self.positions_data:
            print("   No positions data available")
            return
        
        closed = self.positions_data.get("closed_positions", [])
        
        close_reasons = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
        
        for pos in closed:
            reason = pos.get("close_reason", pos.get("closeReason", "unknown"))
            pnl = float(pos.get("realized_pnl", pos.get("pnl", 0)))
            is_win = pnl > 0
            
            close_reasons[reason]["count"] += 1
            close_reasons[reason]["pnl"] += pnl
            if is_win:
                close_reasons[reason]["wins"] += 1
        
        total = len(closed)
        print(f"\n📋 CLOSE REASONS (Total: {total} positions):")
        print(f"{'Reason':<35} {'Count':>7} {'%':>6} {'WR%':>6} {'P&L':>12}")
        print("-" * 70)
        
        for reason, data in sorted(close_reasons.items(), key=lambda x: -x[1]["count"]):
            pct = (data["count"] / total * 100) if total > 0 else 0
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"{reason:<35} {data['count']:>7} {pct:>5.1f}% {wr:>5.1f}% ${data['pnl']:>10.2f}")
    
    def analyze_enriched_signals(self):
        """Analyze enriched decisions with proper OFI bucketing"""
        print("\n" + "=" * 70)
        print("ENRICHED SIGNAL ANALYSIS (with OFI bucketing)")
        print("=" * 70)
        
        if not self.enriched_data:
            print("   No enriched data available")
            return
        
        by_ofi = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})
        by_alignment = {"aligned": {"count": 0, "wins": 0, "pnl": 0.0}, "misaligned": {"count": 0, "wins": 0, "pnl": 0.0}}
        
        for record in self.enriched_data:
            signal_ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            pnl = float(outcome.get("pnl_usd", 0))
            is_win = pnl > 0
            
            ofi_raw = signal_ctx.get("ofi", 0)
            ofi_bucket = self.bucket_ofi(ofi_raw)
            by_ofi[ofi_bucket]["count"] += 1
            by_ofi[ofi_bucket]["pnl"] += pnl
            if is_win:
                by_ofi[ofi_bucket]["wins"] += 1
            
            direction = signal_ctx.get("side", "").upper()
            ofi_direction = "SHORT" if ofi_raw < 0 else "LONG"
            is_aligned = ofi_direction == direction
            alignment_key = "aligned" if is_aligned else "misaligned"
            by_alignment[alignment_key]["count"] += 1
            by_alignment[alignment_key]["pnl"] += pnl
            if is_win:
                by_alignment[alignment_key]["wins"] += 1
        
        print(f"\n📈 BY OFI STRENGTH (from enriched decisions):")
        for bucket in ["extreme", "very_strong", "strong", "moderate", "weak"]:
            if bucket in by_ofi:
                data = by_ofi[bucket]
                wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
                print(f"   {bucket}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n🎯 OFI-DIRECTION ALIGNMENT:")
        for alignment, data in by_alignment.items():
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   {alignment}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
    
    def generate_summary(self, portfolio_results: Dict):
        """Generate executive summary with recommendations"""
        print("\n" + "=" * 70)
        print("EXECUTIVE SUMMARY & RECOMMENDATIONS")
        print("=" * 70)
        
        overall = portfolio_results.get("overall", {})
        total = overall.get("total", 0)
        win_rate = (overall["wins"] / total * 100) if total > 0 else 0
        net_pnl = overall["total_pnl"] - overall["total_fees"]
        
        print(f"\n📊 OVERALL ASSESSMENT:")
        print(f"   - {total} trades analyzed over {len(portfolio_results.get('by_date', {}))} days")
        print(f"   - Win Rate: {win_rate:.1f}%")
        print(f"   - Net P&L: ${net_pnl:.2f}")
        print(f"   - Fees consumed: ${overall['total_fees']:.2f} ({abs(overall['total_fees']/net_pnl*100) if net_pnl != 0 else 0:.1f}% of net)")
        
        print(f"\n🔍 ROOT CAUSES IDENTIFIED:")
        
        by_session = portfolio_results.get("by_session", {})
        worst_sessions = sorted([(s, d) for s, d in by_session.items()], key=lambda x: x[1]["pnl"])[:2]
        for session, data in worst_sessions:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   - {session} session: {wr:.1f}% WR, ${data['pnl']:.2f} P&L (n={data['count']})")
        
        by_symbol = portfolio_results.get("by_symbol", {})
        worst_symbols = sorted([(s, d) for s, d in by_symbol.items()], key=lambda x: x[1]["pnl"] - x[1]["fees"])[:3]
        for symbol, data in worst_symbols:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            net = data["pnl"] - data["fees"]
            print(f"   - {symbol}: {wr:.1f}% WR, ${net:.2f} net P&L (n={data['count']})")
        
        print(f"\n🎯 RECOMMENDED ACTIONS:")
        print(f"   1. Block trades during worst-performing sessions")
        print(f"   2. Disable or increase thresholds for worst-performing symbols")
        print(f"   3. Require OFI-direction alignment before entry")
        print(f"   4. Reduce ladder reversal frequency")
        print(f"   5. Only trade when |OFI| > 0.3 (filter out weak signals)")
    
    def run_full_analysis(self):
        """Run complete extended analysis"""
        print("\n" + "=" * 70)
        print("EXTENDED TRADE ANALYSIS - FULL HISTORICAL DEEP DIVE")
        print("=" * 70)
        print(f"Analysis started: {datetime.now().isoformat()}")
        
        self.load_all_data()
        portfolio_results = self.analyze_portfolio_trades()
        self.analyze_daily_trends(portfolio_results)
        self.analyze_close_reasons()
        self.analyze_enriched_signals()
        self.generate_summary(portfolio_results)
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "portfolio_results": {
                "overall": portfolio_results["overall"],
                "time_range": {
                    "first": str(portfolio_results["time_range"]["first"]),
                    "last": str(portfolio_results["time_range"]["last"])
                }
            }
        }
        
        with open("logs/extended_analysis_report.json", "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n💾 Report saved to: logs/extended_analysis_report.json")
        
        print("\n" + "=" * 70)
        print("EXTENDED ANALYSIS COMPLETE")
        print("=" * 70)


if __name__ == "__main__":
    analyzer = ExtendedTradeAnalysis()
    analyzer.run_full_analysis()
