"""
Signal Quality Diagnostic - Full Root Cause Analysis

Analyzes why trading signals are systematically wrong and identifies:
- Direction bias (LONG vs SHORT accuracy)
- Strategy logic issues
- Symbol-specific patterns
- Entry/exit timing problems
- Data quality issues
- Indicator calculation errors
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
import statistics

EXEC_LOG = "logs/executed_trades.jsonl"
PORTFOLIO_FUTURES = "logs/portfolio_futures.json"
COMPOSITE_TRACE = "logs/composite_alpha_trace.jsonl"
STRATEGY_SIGNALS = "logs/strategy_signals.jsonl"

class SignalQualityDiagnostic:
    def __init__(self):
        self.trades = []
        self.signals = []
        self.findings = []
        
    def load_data(self):
        """Load all relevant data sources"""
        print("📂 Loading trade and signal data...")
        
        # Load executed trades
        if os.path.exists(EXEC_LOG):
            with open(EXEC_LOG, 'r') as f:
                self.trades = [json.loads(line) for line in f if line.strip()]
        
        print(f"   ✓ Loaded {len(self.trades)} trades")
        
        # Load signal traces (last 5000)
        if os.path.exists(COMPOSITE_TRACE):
            with open(COMPOSITE_TRACE, 'r') as f:
                lines = f.readlines()
                self.signals = [json.loads(line) for line in lines[-5000:] if line.strip()]
        
        print(f"   ✓ Loaded {len(self.signals)} signal traces")
    
    def analyze_directional_bias(self, window=100):
        """Analyze if LONG or SHORT signals are systematically wrong"""
        print(f"\n🔍 DIRECTIONAL BIAS ANALYSIS (last {window} trades)")
        print("="*80)
        
        recent = self.trades[-window:]
        
        by_direction = defaultdict(lambda: {
            'wins': 0, 'losses': 0, 'total_pnl': 0, 'gross_pnl': 0,
            'avg_price_move': [], 'avg_hold_time': [], 'fees': 0
        })
        
        for t in recent:
            direction = t.get('direction', 'UNKNOWN')
            pnl = t.get('net_pnl', 0)
            gross_pnl = t.get('gross_pnl', 0)
            fees = t.get('trading_fees', 0)
            
            is_win = pnl > 0
            by_direction[direction]['wins' if is_win else 'losses'] += 1
            by_direction[direction]['total_pnl'] += pnl
            by_direction[direction]['gross_pnl'] += gross_pnl
            by_direction[direction]['fees'] += fees
            
            # Price movement analysis
            entry = t.get('entry_price', 0)
            exit_price = t.get('exit_price', 0)
            if entry > 0:
                if direction == 'LONG':
                    move = (exit_price - entry) / entry
                else:
                    move = (entry - exit_price) / entry
                by_direction[direction]['avg_price_move'].append(move)
            
            # Hold time
            entry_ts = t.get('entry_ts', 0)
            exit_ts = t.get('exit_ts', 0)
            if entry_ts and exit_ts:
                hold_sec = exit_ts - entry_ts
                by_direction[direction]['avg_hold_time'].append(hold_sec)
        
        results = {}
        for direction, stats in by_direction.items():
            total = stats['wins'] + stats['losses']
            wr = (stats['wins'] / total * 100) if total > 0 else 0
            
            avg_move = statistics.mean(stats['avg_price_move']) if stats['avg_price_move'] else 0
            avg_hold = statistics.mean(stats['avg_hold_time']) if stats['avg_hold_time'] else 0
            
            results[direction] = {
                'win_rate': wr,
                'trades': total,
                'wins': stats['wins'],
                'losses': stats['losses'],
                'net_pnl': stats['total_pnl'],
                'gross_pnl': stats['gross_pnl'],
                'fees': stats['fees'],
                'avg_price_move_pct': avg_move * 100,
                'avg_hold_seconds': avg_hold
            }
            
            print(f"\n{direction}:")
            print(f"   Win Rate: {wr:.1f}% ({stats['wins']}W / {stats['losses']}L)")
            print(f"   Net P&L: ${stats['total_pnl']:.2f}")
            print(f"   Gross P&L: ${stats['gross_pnl']:.2f}")
            print(f"   Fees: ${stats['fees']:.2f}")
            print(f"   Avg Price Move: {avg_move*100:.3f}%")
            print(f"   Avg Hold Time: {avg_hold:.1f} seconds")
            
            # Diagnosis
            if wr < 30 and stats['gross_pnl'] < 0:
                finding = f"🚨 {direction} signals are FUNDAMENTALLY WRONG - {wr:.1f}% WR with negative gross P&L"
                print(f"   {finding}")
                self.findings.append(finding)
            elif stats['gross_pnl'] > 0 and stats['total_pnl'] < 0:
                finding = f"⚠️ {direction} signals are directionally CORRECT but killed by fees (gross: ${stats['gross_pnl']:.2f}, fees: ${stats['fees']:.2f})"
                print(f"   {finding}")
                self.findings.append(finding)
        
        return results
    
    def analyze_by_strategy(self, window=200):
        """Analyze each strategy's signal quality"""
        print(f"\n🔍 STRATEGY SIGNAL QUALITY (last {window} trades)")
        print("="*80)
        
        recent = self.trades[-window:]
        
        by_strategy = defaultdict(lambda: defaultdict(lambda: {
            'wins': 0, 'losses': 0, 'pnl': 0, 'gross_pnl': 0
        }))
        
        for t in recent:
            strategy = t.get('strategy_id', 'UNKNOWN')
            direction = t.get('direction', 'UNKNOWN')
            pnl = t.get('net_pnl', 0)
            gross = t.get('gross_pnl', 0)
            
            is_win = pnl > 0
            by_strategy[strategy][direction]['wins' if is_win else 'losses'] += 1
            by_strategy[strategy][direction]['pnl'] += pnl
            by_strategy[strategy][direction]['gross_pnl'] += gross
        
        results = {}
        for strategy, directions in by_strategy.items():
            print(f"\n{strategy}:")
            results[strategy] = {}
            
            for direction, stats in directions.items():
                total = stats['wins'] + stats['losses']
                wr = (stats['wins'] / total * 100) if total > 0 else 0
                
                results[strategy][direction] = {
                    'win_rate': wr,
                    'trades': total,
                    'net_pnl': stats['pnl'],
                    'gross_pnl': stats['gross_pnl']
                }
                
                print(f"   {direction}: {wr:.1f}% WR ({stats['wins']}W/{stats['losses']}L) | Net: ${stats['pnl']:.2f} | Gross: ${stats['gross_pnl']:.2f}")
                
                # Diagnosis
                if total >= 20 and wr < 25:
                    finding = f"🚨 {strategy} {direction} signals are INVERTED ({wr:.1f}% WR on {total} trades)"
                    print(f"      {finding}")
                    self.findings.append(finding)
        
        return results
    
    def analyze_by_symbol(self, window=200):
        """Analyze symbol-specific signal quality"""
        print(f"\n🔍 SYMBOL-SPECIFIC SIGNAL QUALITY (last {window} trades)")
        print("="*80)
        
        recent = self.trades[-window:]
        
        by_symbol = defaultdict(lambda: defaultdict(lambda: {
            'wins': 0, 'losses': 0, 'pnl': 0
        }))
        
        for t in recent:
            symbol = t.get('symbol', 'UNKNOWN')
            direction = t.get('direction', 'UNKNOWN')
            pnl = t.get('net_pnl', 0)
            
            is_win = pnl > 0
            by_symbol[symbol][direction]['wins' if is_win else 'losses'] += 1
            by_symbol[symbol][direction]['pnl'] += pnl
        
        results = {}
        for symbol in sorted(by_symbol.keys()):
            directions = by_symbol[symbol]
            print(f"\n{symbol}:")
            results[symbol] = {}
            
            for direction, stats in directions.items():
                total = stats['wins'] + stats['losses']
                wr = (stats['wins'] / total * 100) if total > 0 else 0
                
                results[symbol][direction] = {
                    'win_rate': wr,
                    'trades': total,
                    'pnl': stats['pnl']
                }
                
                print(f"   {direction}: {wr:.1f}% WR ({stats['wins']}W/{stats['losses']}L) | ${stats['pnl']:.2f}")
                
                # Diagnosis
                if total >= 10 and wr < 20:
                    finding = f"🚨 {symbol} {direction} signals failing ({wr:.1f}% WR)"
                    print(f"      {finding}")
                    self.findings.append(finding)
        
        return results
    
    def analyze_entry_exit_timing(self, window=100):
        """Analyze if entries/exits are mistimed"""
        print(f"\n🔍 ENTRY/EXIT TIMING ANALYSIS (last {window} trades)")
        print("="*80)
        
        recent = self.trades[-window:]
        
        instant_closes = []
        quick_losses = []
        
        for t in recent:
            entry_ts = t.get('entry_ts', 0)
            exit_ts = t.get('exit_ts', 0)
            
            if entry_ts and exit_ts:
                hold_time = exit_ts - entry_ts
                pnl = t.get('net_pnl', 0)
                
                # Instant closes (same second)
                if hold_time < 1:
                    instant_closes.append(t)
                
                # Quick losses (< 60 sec and losing)
                if hold_time < 60 and pnl < 0:
                    quick_losses.append(t)
        
        print(f"\nInstant Closes (<1 sec): {len(instant_closes)}")
        if instant_closes:
            avg_loss = statistics.mean([t.get('net_pnl', 0) for t in instant_closes])
            print(f"   Average P&L: ${avg_loss:.2f}")
            print(f"   Pattern: Positions opening and immediately closing")
            
            if len(instant_closes) > 10:
                finding = f"🚨 {len(instant_closes)} instant closes detected - likely risk cap or position sizing issue"
                print(f"   {finding}")
                self.findings.append(finding)
                
                # Sample one
                sample = instant_closes[0]
                print(f"\n   Sample instant close:")
                print(f"      {sample.get('symbol')} {sample.get('direction')} @ ${sample.get('entry_price')}")
                print(f"      Entry: {sample.get('entry_price')}, Exit: {sample.get('exit_price')}")
                print(f"      Size: ${sample.get('margin_collateral', 0):.2f}")
        
        print(f"\nQuick Losses (<60 sec, negative): {len(quick_losses)}")
        if quick_losses:
            avg_loss = statistics.mean([t.get('net_pnl', 0) for t in quick_losses])
            print(f"   Average Loss: ${avg_loss:.2f}")
            
            if len(quick_losses) > 20:
                finding = f"⚠️ {len(quick_losses)} trades exit at loss within 60 seconds - stop losses too tight or bad entries"
                print(f"   {finding}")
                self.findings.append(finding)
        
        return {
            'instant_closes': len(instant_closes),
            'quick_losses': len(quick_losses)
        }
    
    def analyze_signal_to_trade_correlation(self):
        """Check if executed trades match signal predictions"""
        print(f"\n🔍 SIGNAL-TO-TRADE CORRELATION ANALYSIS")
        print("="*80)
        
        if not self.signals:
            print("   ⚠️ No signal trace data available")
            return {}
        
        # Match recent signals to trades
        recent_trades = self.trades[-50:]
        
        matched = 0
        for trade in recent_trades:
            symbol = trade.get('symbol')
            direction = trade.get('direction')
            entry_ts = trade.get('entry_ts', 0)
            
            # Find signal within 60 seconds of entry
            for sig in self.signals:
                sig_ts = sig.get('ts', 0)
                sig_symbol = sig.get('symbol')
                
                if sig_symbol == symbol and abs(sig_ts - entry_ts) < 60:
                    matched += 1
                    break
        
        correlation_pct = (matched / len(recent_trades) * 100) if recent_trades else 0
        print(f"\nSignal-to-Trade Match Rate: {correlation_pct:.1f}%")
        print(f"   {matched}/{len(recent_trades)} trades matched to signals within 60 seconds")
        
        if correlation_pct < 50:
            finding = f"⚠️ Low signal correlation ({correlation_pct:.1f}%) - trades may not be following signals"
            print(f"   {finding}")
            self.findings.append(finding)
        
        return {'match_rate': correlation_pct}
    
    def generate_root_cause_report(self):
        """Generate comprehensive root cause analysis"""
        print("\n" + "="*80)
        print("📊 ROOT CAUSE ANALYSIS SUMMARY")
        print("="*80)
        
        if not self.findings:
            print("\n✓ No critical issues detected")
            return
        
        print(f"\n🚨 CRITICAL FINDINGS ({len(self.findings)}):\n")
        
        for i, finding in enumerate(self.findings, 1):
            print(f"{i}. {finding}")
        
        # Determine primary root cause
        print("\n" + "="*80)
        print("🎯 PRIMARY ROOT CAUSE HYPOTHESIS:")
        print("="*80)
        
        has_directional_inversion = any("FUNDAMENTALLY WRONG" in f for f in self.findings)
        has_fee_problem = any("killed by fees" in f for f in self.findings)
        has_timing_problem = any("instant closes" in f or "Quick losses" in f for f in self.findings)
        
        if has_directional_inversion:
            print("\n🚨 SIGNAL INVERSION DETECTED")
            print("   Diagnosis: Trading signals are predicting the OPPOSITE direction")
            print("   Evidence: Win rates <30% on gross P&L")
            print("   Root Cause Candidates:")
            print("      1. Indicator logic is inverted (buy when should sell)")
            print("      2. Market regime has fundamentally shifted")
            print("      3. Data feed delay causing late/wrong entries")
            print("      4. Strategy assumes mean reversion in trending market")
            
            print("\n   Recommended Actions:")
            print("      A. Review indicator calculations (EMA crossovers, momentum)")
            print("      B. Check if market regime changed (trending vs ranging)")
            print("      C. Verify data feed latency")
            print("      D. Test signal inversion overlay (flip LONG↔SHORT)")
        
        elif has_fee_problem:
            print("\n⚠️ FEE DRAG DOMINATING PERFORMANCE")
            print("   Diagnosis: Signals are directionally correct but fees erase profits")
            print("   Evidence: Positive gross P&L but negative net P&L")
            print("   Root Cause: Position sizes too small or hold times too short")
            
            print("\n   Recommended Actions:")
            print("      A. Increase minimum position size")
            print("      B. Add minimum profit targets before exit")
            print("      C. Use limit orders (maker fees) instead of market orders")
        
        elif has_timing_problem:
            print("\n⚠️ EXECUTION TIMING ISSUES")
            print("   Diagnosis: Positions opening/closing too quickly")
            print("   Evidence: Many instant closes or sub-60-second exits")
            print("   Root Cause: Risk caps triggering immediately or stops too tight")
            
            print("\n   Recommended Actions:")
            print("      A. Review risk cap settings (asset exposure limits)")
            print("      B. Adjust position sizing to avoid instant risk cap hits")
            print("      C. Widen stop losses or use time-based exits")
        
        # Save report to file
        report = {
            'timestamp': datetime.now().isoformat(),
            'findings': self.findings,
            'total_trades_analyzed': len(self.trades),
            'primary_diagnosis': 'signal_inversion' if has_directional_inversion else 
                               'fee_drag' if has_fee_problem else
                               'timing_issues' if has_timing_problem else 'unknown'
        }
        
        with open('logs/signal_quality_diagnostic.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print("\n📄 Full report saved to: logs/signal_quality_diagnostic.json")
        
        return report
    
    def run_full_diagnostic(self):
        """Run complete diagnostic suite"""
        print("\n" + "="*80)
        print("🔬 SIGNAL QUALITY DIAGNOSTIC - FULL ANALYSIS")
        print("="*80)
        
        self.load_data()
        
        if not self.trades:
            print("\n⚠️ No trade data available for analysis")
            return
        
        # Run all analyses
        directional = self.analyze_directional_bias(window=100)
        strategy = self.analyze_by_strategy(window=200)
        symbol = self.analyze_by_symbol(window=200)
        timing = self.analyze_entry_exit_timing(window=100)
        correlation = self.analyze_signal_to_trade_correlation()
        
        # Generate root cause report
        report = self.generate_root_cause_report()
        
        return {
            'directional': directional,
            'strategy': strategy,
            'symbol': symbol,
            'timing': timing,
            'correlation': correlation,
            'report': report
        }


if __name__ == "__main__":
    diagnostic = SignalQualityDiagnostic()
    results = diagnostic.run_full_diagnostic()
