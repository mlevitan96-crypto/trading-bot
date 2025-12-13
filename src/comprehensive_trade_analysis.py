#!/usr/bin/env python3
"""
Comprehensive Trade Analysis - Deep Dive Postmortem v2
=======================================================
Analyzes all trades to understand:
1. Execution bugs vs signal logic issues
2. Why trades are losing money
3. How to improve performance

Fixes from v1:
- Properly buckets raw OFI/ensemble values
- Loads Beta bot data from correct location
- Analyzes ladder reversal patterns

Phase 4 Migration: Uses SQLite for closed trades via DataRegistry.
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple
from pathlib import Path

try:
    from src.data_registry import DataRegistry as DR
except ImportError:
    import sys
    sys.path.insert(0, '/home/runner/workspace')
    from src.data_registry import DataRegistry as DR

class ComprehensiveTradeAnalysis:
    """Deep dive analysis of all trading activity"""
    
    OFI_THRESHOLDS = {
        "extreme": 0.9,
        "very_strong": 0.7,
        "strong": 0.5,
        "moderate": 0.3,
        "weak": 0.0
    }
    
    ENSEMBLE_THRESHOLDS = {
        "strong_bull": 0.5,
        "bull": 0.2,
        "neutral": -0.2,
        "bear": -0.5,
        "strong_bear": -1.0
    }
    
    def __init__(self):
        self.enriched_file = "logs/enriched_decisions.jsonl"
        self.signals_file = "logs/signals_universe.jsonl"
        self.alpha_trades_file = "logs/alpha_trades.jsonl"
        self.beta_portfolio_file = "logs/beta/portfolio.json"
        self.beta_blocked_file = "logs/beta/blocked_signals.jsonl"
        
        self.positions_data = None
        self.enriched_data = []
        self.signals_data = []
        self.alpha_trades = []
        self.beta_portfolio = None
        self.beta_blocked = []
        
        self.analysis_results = {
            "timestamp": datetime.now().isoformat(),
            "stage_0_data_assurance": {},
            "stage_1_execution_forensics": {},
            "stage_2_signal_analysis": {},
            "stage_3_alpha_beta_comparison": {},
            "stage_4_ladder_forensics": {},
            "stage_5_remediation": {}
        }
    
    def bucket_ofi(self, ofi_value: float) -> str:
        """Convert raw OFI value to bucket"""
        abs_ofi = abs(ofi_value) if ofi_value else 0
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
    
    def bucket_ensemble(self, ensemble_value: float) -> str:
        """Convert raw ensemble value to bucket"""
        if ensemble_value is None:
            return "unknown"
        if ensemble_value >= self.ENSEMBLE_THRESHOLDS["strong_bull"]:
            return "strong_bull"
        elif ensemble_value >= self.ENSEMBLE_THRESHOLDS["bull"]:
            return "bull"
        elif ensemble_value >= self.ENSEMBLE_THRESHOLDS["neutral"]:
            return "neutral"
        elif ensemble_value >= self.ENSEMBLE_THRESHOLDS["bear"]:
            return "bear"
        else:
            return "strong_bear"
    
    def get_session(self, timestamp: int) -> str:
        """Determine trading session from timestamp"""
        try:
            if timestamp > 1e10:
                timestamp = timestamp / 1000
            dt = datetime.fromtimestamp(timestamp)
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
        except:
            return "unknown"
    
    def load_all_data(self) -> Dict[str, Any]:
        """Stage 0: Load and validate all data files
        
        Phase 4 Migration: Uses SQLite for closed trades via DataRegistry.
        """
        print("=" * 70)
        print("STAGE 0: DATA ASSURANCE")
        print("=" * 70)
        
        data_status = {}
        
        try:
            closed_positions = DR.get_closed_trades_from_db()
            open_positions = DR.get_open_positions()
            self.positions_data = {
                "open_positions": open_positions,
                "closed_positions": closed_positions
            }
            open_count = len(open_positions)
            closed_count = len(closed_positions)
            data_status["positions_futures"] = {
                "status": "OK",
                "open_positions": open_count,
                "closed_positions": closed_count,
                "source": "SQLite"
            }
            print(f"   ✅ positions (SQLite): {open_count} open, {closed_count} closed")
        except Exception as e:
            data_status["positions_futures"] = {"status": "ERROR", "error": str(e)}
            print(f"   ❌ positions: {e}")
        
        if os.path.exists(self.enriched_file):
            try:
                with open(self.enriched_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.enriched_data.append(json.loads(line))
                data_status["enriched_decisions"] = {
                    "status": "OK",
                    "records": len(self.enriched_data)
                }
                print(f"   ✅ enriched_decisions.jsonl: {len(self.enriched_data)} records")
            except Exception as e:
                data_status["enriched_decisions"] = {"status": "ERROR", "error": str(e)}
                print(f"   ❌ enriched_decisions.jsonl: {e}")
        
        if os.path.exists(self.alpha_trades_file):
            try:
                with open(self.alpha_trades_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.alpha_trades.append(json.loads(line))
                data_status["alpha_trades"] = {
                    "status": "OK",
                    "records": len(self.alpha_trades)
                }
                print(f"   ✅ alpha_trades.jsonl: {len(self.alpha_trades)} records")
            except Exception as e:
                data_status["alpha_trades"] = {"status": "ERROR", "error": str(e)}
        
        if os.path.exists(self.beta_portfolio_file):
            try:
                with open(self.beta_portfolio_file, 'r') as f:
                    self.beta_portfolio = json.load(f)
                trade_count = len(self.beta_portfolio.get("trades", []))
                data_status["beta_portfolio"] = {
                    "status": "OK",
                    "trades": trade_count
                }
                print(f"   ✅ beta/portfolio.json: {trade_count} trades")
            except Exception as e:
                data_status["beta_portfolio"] = {"status": "ERROR", "error": str(e)}
                print(f"   ❌ beta/portfolio.json: {e}")
        else:
            data_status["beta_portfolio"] = {"status": "MISSING"}
            print(f"   ⚠️ beta/portfolio.json: MISSING")
        
        if os.path.exists(self.beta_blocked_file):
            try:
                with open(self.beta_blocked_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.beta_blocked.append(json.loads(line))
                data_status["beta_blocked"] = {
                    "status": "OK",
                    "records": len(self.beta_blocked)
                }
                print(f"   ✅ beta/blocked_signals.jsonl: {len(self.beta_blocked)} blocked")
            except Exception as e:
                data_status["beta_blocked"] = {"status": "ERROR", "error": str(e)}
        
        
        self.analysis_results["stage_0_data_assurance"] = data_status
        return data_status
    
    def analyze_execution_bugs(self) -> Dict[str, Any]:
        """Stage 1: Execution Bug Forensics"""
        print("\n" + "=" * 70)
        print("STAGE 1: EXECUTION BUG FORENSICS")
        print("=" * 70)
        
        results = {
            "immediate_closures": {"count": 0, "total": 0, "rate": 0.0, "fee_loss": 0.0},
            "duration_analysis": {"under_1min": 0, "1_5min": 0, "5_30min": 0, "30min_plus": 0, "no_timestamp": 0},
            "close_reasons": defaultdict(int),
            "risk_cap_blocks": 0,
            "execution_anomalies": [],
            "fee_impact": {"total_fees": 0.0, "avg_fee_per_trade": 0.0}
        }
        
        if not self.positions_data:
            print("   ❌ No positions data available")
            return results
        
        closed_positions = self.positions_data.get("closed_positions", [])
        results["immediate_closures"]["total"] = len(closed_positions)
        
        for pos in closed_positions:
            close_reason = pos.get("close_reason", pos.get("closeReason", "unknown"))
            results["close_reasons"][close_reason] += 1
            
            entry_time = pos.get("entry_time", pos.get("entryTime", pos.get("timestamp")))
            exit_time = pos.get("exit_time", pos.get("exitTime", pos.get("close_time")))
            
            if entry_time and exit_time:
                try:
                    if isinstance(entry_time, str):
                        entry_ts = datetime.fromisoformat(entry_time.replace('Z', '+00:00')).timestamp()
                    else:
                        entry_ts = entry_time / 1000 if entry_time > 1e10 else entry_time
                    
                    if isinstance(exit_time, str):
                        exit_ts = datetime.fromisoformat(exit_time.replace('Z', '+00:00')).timestamp()
                    else:
                        exit_ts = exit_time / 1000 if exit_time > 1e10 else exit_time
                    
                    duration_sec = exit_ts - entry_ts
                    
                    if duration_sec < 60:
                        results["duration_analysis"]["under_1min"] += 1
                        if duration_sec < 5:
                            results["immediate_closures"]["count"] += 1
                            fee = abs(float(pos.get("fee", pos.get("fees", 0))))
                            results["immediate_closures"]["fee_loss"] += fee
                    elif duration_sec < 300:
                        results["duration_analysis"]["1_5min"] += 1
                    elif duration_sec < 1800:
                        results["duration_analysis"]["5_30min"] += 1
                    else:
                        results["duration_analysis"]["30min_plus"] += 1
                except Exception as e:
                    results["duration_analysis"]["no_timestamp"] += 1
            else:
                results["duration_analysis"]["no_timestamp"] += 1
            
            fee = abs(float(pos.get("fee", pos.get("fees", 0))))
            results["fee_impact"]["total_fees"] += fee
            
            if close_reason in ["risk_cap", "risk_cap_max_positions", "risk_cap_asset_exposure"]:
                results["risk_cap_blocks"] += 1
        
        total = results["immediate_closures"]["total"]
        if total > 0:
            results["immediate_closures"]["rate"] = (results["immediate_closures"]["count"] / total) * 100
            results["fee_impact"]["avg_fee_per_trade"] = results["fee_impact"]["total_fees"] / total
        
        print(f"\n📊 DURATION ANALYSIS:")
        print(f"   - Under 1 minute: {results['duration_analysis']['under_1min']} trades")
        print(f"   - 1-5 minutes: {results['duration_analysis']['1_5min']} trades")
        print(f"   - 5-30 minutes: {results['duration_analysis']['5_30min']} trades")
        print(f"   - 30+ minutes: {results['duration_analysis']['30min_plus']} trades")
        print(f"   - No timestamp: {results['duration_analysis']['no_timestamp']} trades")
        
        print(f"\n🚨 IMMEDIATE CLOSURE ANALYSIS (<5 seconds):")
        print(f"   - Count: {results['immediate_closures']['count']} / {total}")
        print(f"   - Rate: {results['immediate_closures']['rate']:.1f}%")
        print(f"   - Fee loss from immediate closures: ${results['immediate_closures']['fee_loss']:.2f}")
        
        print(f"\n📋 CLOSE REASONS (Top 10):")
        for reason, count in sorted(results["close_reasons"].items(), key=lambda x: -x[1])[:10]:
            pct = (count / total * 100) if total > 0 else 0
            print(f"   - {reason}: {count} ({pct:.1f}%)")
        
        print(f"\n💰 FEE IMPACT:")
        print(f"   - Total fees paid: ${results['fee_impact']['total_fees']:.2f}")
        print(f"   - Average fee per trade: ${results['fee_impact']['avg_fee_per_trade']:.4f}")
        
        self.analysis_results["stage_1_execution_forensics"] = dict(results)
        results["close_reasons"] = dict(results["close_reasons"])
        return results
    
    def analyze_signal_quality(self) -> Dict[str, Any]:
        """Stage 2: Signal Quality Analysis with proper bucketing"""
        print("\n" + "=" * 70)
        print("STAGE 2: SIGNAL QUALITY ANALYSIS (Properly Bucketed)")
        print("=" * 70)
        
        results = {
            "overall": {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "total_pnl": 0.0, "avg_pnl": 0.0},
            "by_ofi_bucket": {},
            "by_ensemble_bucket": {},
            "by_session": {},
            "by_symbol": {},
            "by_direction": {"LONG": {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0}, "SHORT": {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0}},
            "by_regime": {},
            "ofi_direction_alignment": {"aligned": {"wins": 0, "losses": 0, "pnl": 0.0}, "misaligned": {"wins": 0, "losses": 0, "pnl": 0.0}},
            "signal_issues": []
        }
        
        if not self.enriched_data:
            print("   ❌ No enriched decision data available")
            return results
        
        for record in self.enriched_data:
            signal_ctx = record.get("signal_ctx", {})
            outcome = record.get("outcome", {})
            
            pnl = float(outcome.get("pnl_usd", record.get("realized_pnl", record.get("pnl", 0))))
            is_win = pnl > 0
            
            results["overall"]["total"] += 1
            results["overall"]["total_pnl"] += pnl
            if is_win:
                results["overall"]["wins"] += 1
            else:
                results["overall"]["losses"] += 1
            
            ofi_raw = signal_ctx.get("ofi", 0)
            ofi_bucket = self.bucket_ofi(ofi_raw)
            if ofi_bucket not in results["by_ofi_bucket"]:
                results["by_ofi_bucket"][ofi_bucket] = {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0, "avg_ofi": 0.0, "ofi_sum": 0.0}
            results["by_ofi_bucket"][ofi_bucket]["count"] += 1
            results["by_ofi_bucket"][ofi_bucket]["pnl"] += pnl
            results["by_ofi_bucket"][ofi_bucket]["ofi_sum"] += abs(ofi_raw) if ofi_raw else 0
            if is_win:
                results["by_ofi_bucket"][ofi_bucket]["wins"] += 1
            else:
                results["by_ofi_bucket"][ofi_bucket]["losses"] += 1
            
            ensemble_raw = signal_ctx.get("ensemble", 0)
            ensemble_bucket = self.bucket_ensemble(ensemble_raw)
            if ensemble_bucket not in results["by_ensemble_bucket"]:
                results["by_ensemble_bucket"][ensemble_bucket] = {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0}
            results["by_ensemble_bucket"][ensemble_bucket]["count"] += 1
            results["by_ensemble_bucket"][ensemble_bucket]["pnl"] += pnl
            if is_win:
                results["by_ensemble_bucket"][ensemble_bucket]["wins"] += 1
            else:
                results["by_ensemble_bucket"][ensemble_bucket]["losses"] += 1
            
            ts = record.get("ts", record.get("entry_ts", 0))
            session = self.get_session(ts)
            if session not in results["by_session"]:
                results["by_session"][session] = {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0}
            results["by_session"][session]["count"] += 1
            results["by_session"][session]["pnl"] += pnl
            if is_win:
                results["by_session"][session]["wins"] += 1
            else:
                results["by_session"][session]["losses"] += 1
            
            symbol = record.get("symbol", "unknown")
            if symbol not in results["by_symbol"]:
                results["by_symbol"][symbol] = {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0}
            results["by_symbol"][symbol]["count"] += 1
            results["by_symbol"][symbol]["pnl"] += pnl
            if is_win:
                results["by_symbol"][symbol]["wins"] += 1
            else:
                results["by_symbol"][symbol]["losses"] += 1
            
            direction = signal_ctx.get("side", record.get("direction", "unknown")).upper()
            if direction in results["by_direction"]:
                results["by_direction"][direction]["pnl"] += pnl
                results["by_direction"][direction]["count"] += 1
                if is_win:
                    results["by_direction"][direction]["wins"] += 1
                else:
                    results["by_direction"][direction]["losses"] += 1
            
            regime = signal_ctx.get("regime", "unknown")
            if regime not in results["by_regime"]:
                results["by_regime"][regime] = {"wins": 0, "losses": 0, "pnl": 0.0, "count": 0}
            results["by_regime"][regime]["count"] += 1
            results["by_regime"][regime]["pnl"] += pnl
            if is_win:
                results["by_regime"][regime]["wins"] += 1
            else:
                results["by_regime"][regime]["losses"] += 1
            
            ofi_direction = "SHORT" if ofi_raw < 0 else "LONG"
            is_aligned = ofi_direction == direction
            alignment_key = "aligned" if is_aligned else "misaligned"
            results["ofi_direction_alignment"][alignment_key]["pnl"] += pnl
            if is_win:
                results["ofi_direction_alignment"][alignment_key]["wins"] += 1
            else:
                results["ofi_direction_alignment"][alignment_key]["losses"] += 1
        
        for bucket in results["by_ofi_bucket"].values():
            if bucket["count"] > 0:
                bucket["avg_ofi"] = bucket["ofi_sum"] / bucket["count"]
        
        total = results["overall"]["total"]
        if total > 0:
            results["overall"]["win_rate"] = (results["overall"]["wins"] / total) * 100
            results["overall"]["avg_pnl"] = results["overall"]["total_pnl"] / total
        
        print(f"\n📊 OVERALL PERFORMANCE:")
        print(f"   - Total trades analyzed: {total}")
        print(f"   - Wins: {results['overall']['wins']} | Losses: {results['overall']['losses']}")
        print(f"   - Win rate: {results['overall']['win_rate']:.1f}%")
        print(f"   - Total P&L: ${results['overall']['total_pnl']:.2f}")
        print(f"   - Average P&L per trade: ${results['overall']['avg_pnl']:.2f}")
        
        print(f"\n📈 BY OFI BUCKET (properly bucketed from raw values):")
        for bucket in ["extreme", "very_strong", "strong", "moderate", "weak"]:
            if bucket in results["by_ofi_bucket"]:
                data = results["by_ofi_bucket"][bucket]
                wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
                print(f"   - {bucket}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}, avg|OFI|={data['avg_ofi']:.2f}")
        
        print(f"\n📈 BY ENSEMBLE BUCKET:")
        for bucket in ["strong_bull", "bull", "neutral", "bear", "strong_bear"]:
            if bucket in results["by_ensemble_bucket"]:
                data = results["by_ensemble_bucket"][bucket]
                wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
                print(f"   - {bucket}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n⏰ BY SESSION:")
        for session, data in sorted(results["by_session"].items(), key=lambda x: -x[1]["pnl"]):
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   - {session}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n🌊 BY REGIME:")
        for regime, data in sorted(results["by_regime"].items(), key=lambda x: -x[1]["pnl"]):
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   - {regime}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n🪙 TOP 5 SYMBOLS (Best P&L):")
        sorted_symbols = sorted(results["by_symbol"].items(), key=lambda x: -x[1]["pnl"])
        for symbol, data in sorted_symbols[:5]:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   {symbol}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        print(f"\n💀 BOTTOM 5 SYMBOLS (Worst P&L):")
        for symbol, data in sorted_symbols[-5:]:
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   {symbol}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n↕️ BY DIRECTION:")
        for direction, data in results["by_direction"].items():
            wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
            print(f"   - {direction}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        print(f"\n🎯 OFI-DIRECTION ALIGNMENT:")
        for alignment, data in results["ofi_direction_alignment"].items():
            total_align = data["wins"] + data["losses"]
            wr = (data["wins"] / total_align * 100) if total_align > 0 else 0
            print(f"   - {alignment}: n={total_align}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        self.analysis_results["stage_2_signal_analysis"] = results
        return results
    
    def analyze_alpha_beta_comparison(self) -> Dict[str, Any]:
        """Stage 3: Alpha vs Beta Bot Comparison from correct data sources"""
        print("\n" + "=" * 70)
        print("STAGE 3: ALPHA vs BETA BOT COMPARISON")
        print("=" * 70)
        
        results = {
            "alpha": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "fees": 0.0},
            "beta": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "fees": 0.0, "blocked_count": 0},
            "data_sources": {"alpha_from": "", "beta_from": ""},
            "inversion_analysis": {}
        }
        
        if self.alpha_trades:
            results["data_sources"]["alpha_from"] = "alpha_trades.jsonl"
            for trade in self.alpha_trades:
                pnl = float(trade.get("pnl", trade.get("realized_pnl", 0)))
                fee = abs(float(trade.get("fee", trade.get("fees", 0))))
                is_win = pnl > 0
                
                results["alpha"]["trades"] += 1
                results["alpha"]["pnl"] += pnl
                results["alpha"]["fees"] += fee
                if is_win:
                    results["alpha"]["wins"] += 1
                else:
                    results["alpha"]["losses"] += 1
        elif self.positions_data:
            results["data_sources"]["alpha_from"] = "positions_futures.json (alpha filtered)"
            for pos in self.positions_data.get("closed_positions", []):
                if pos.get("bot_type", "alpha") == "alpha":
                    pnl = float(pos.get("realized_pnl", pos.get("pnl", 0)))
                    fee = abs(float(pos.get("fee", pos.get("fees", 0))))
                    is_win = pnl > 0
                    
                    results["alpha"]["trades"] += 1
                    results["alpha"]["pnl"] += pnl
                    results["alpha"]["fees"] += fee
                    if is_win:
                        results["alpha"]["wins"] += 1
                    else:
                        results["alpha"]["losses"] += 1
        
        if self.beta_portfolio:
            results["data_sources"]["beta_from"] = "beta/portfolio.json"
            for trade in self.beta_portfolio.get("trades", []):
                pnl = float(trade.get("pnl", trade.get("realized_pnl", 0)))
                fee = abs(float(trade.get("fee", trade.get("fees", 0))))
                is_win = pnl > 0
                
                results["beta"]["trades"] += 1
                results["beta"]["pnl"] += pnl
                results["beta"]["fees"] += fee
                if is_win:
                    results["beta"]["wins"] += 1
                else:
                    results["beta"]["losses"] += 1
        elif self.positions_data:
            results["data_sources"]["beta_from"] = "positions_futures.json (beta filtered)"
            for pos in self.positions_data.get("closed_positions", []):
                if pos.get("bot_type") == "beta":
                    pnl = float(pos.get("realized_pnl", pos.get("pnl", 0)))
                    fee = abs(float(pos.get("fee", pos.get("fees", 0))))
                    is_win = pnl > 0
                    
                    results["beta"]["trades"] += 1
                    results["beta"]["pnl"] += pnl
                    results["beta"]["fees"] += fee
                    if is_win:
                        results["beta"]["wins"] += 1
                    else:
                        results["beta"]["losses"] += 1
        
        results["beta"]["blocked_count"] = len(self.beta_blocked)
        
        alpha_wr = (results["alpha"]["wins"] / results["alpha"]["trades"] * 100) if results["alpha"]["trades"] > 0 else 0
        beta_wr = (results["beta"]["wins"] / results["beta"]["trades"] * 100) if results["beta"]["trades"] > 0 else 0
        
        print(f"\n📋 DATA SOURCES:")
        print(f"   - Alpha: {results['data_sources']['alpha_from']}")
        print(f"   - Beta: {results['data_sources']['beta_from']}")
        
        print(f"\n🔵 ALPHA BOT (Baseline Weighted Fusion):")
        print(f"   - Trades: {results['alpha']['trades']}")
        print(f"   - Wins: {results['alpha']['wins']} | Losses: {results['alpha']['losses']}")
        print(f"   - Win Rate: {alpha_wr:.1f}%")
        print(f"   - Total P&L: ${results['alpha']['pnl']:.2f}")
        print(f"   - Total Fees: ${results['alpha']['fees']:.2f}")
        print(f"   - Net P&L: ${results['alpha']['pnl'] - results['alpha']['fees']:.2f}")
        
        print(f"\n🟣 BETA BOT (Signal Inversion):")
        print(f"   - Trades: {results['beta']['trades']}")
        print(f"   - Blocked Signals: {results['beta']['blocked_count']}")
        print(f"   - Wins: {results['beta']['wins']} | Losses: {results['beta']['losses']}")
        print(f"   - Win Rate: {beta_wr:.1f}%")
        print(f"   - Total P&L: ${results['beta']['pnl']:.2f}")
        print(f"   - Total Fees: ${results['beta']['fees']:.2f}")
        print(f"   - Net P&L: ${results['beta']['pnl'] - results['beta']['fees']:.2f}")
        
        print(f"\n📊 INVERSION EFFICACY:")
        if results["beta"]["trades"] == 0:
            print(f"   ⚠️ Beta has no executed trades - only blocking signals")
            print(f"   → Beta blocked {results['beta']['blocked_count']} signals but executed none")
            print(f"   → Cannot evaluate inversion strategy effectiveness")
        elif beta_wr > alpha_wr:
            improvement = beta_wr - alpha_wr
            print(f"   ✅ Beta outperforming Alpha by {improvement:.1f}% win rate")
            print(f"   → Signal inversion is WORKING")
        else:
            print(f"   ⚠️ Alpha outperforming Beta by {alpha_wr - beta_wr:.1f}% win rate")
            print(f"   → Original signals are better than inverted")
        
        combined_net = (results['alpha']['pnl'] - results['alpha']['fees']) + (results['beta']['pnl'] - results['beta']['fees'])
        print(f"\n💰 COMBINED PERFORMANCE:")
        print(f"   - Combined Net P&L: ${combined_net:.2f}")
        
        self.analysis_results["stage_3_alpha_beta_comparison"] = results
        return results
    
    def analyze_ladder_reversals(self) -> Dict[str, Any]:
        """Stage 4: Ladder Reversal Forensics"""
        print("\n" + "=" * 70)
        print("STAGE 4: LADDER REVERSAL FORENSICS")
        print("=" * 70)
        
        results = {
            "reversal_stats": {"total": 0, "profitable": 0, "losing": 0, "total_pnl": 0.0},
            "by_symbol": {},
            "by_direction": {"LONG_to_SHORT": {"count": 0, "pnl": 0.0}, "SHORT_to_LONG": {"count": 0, "pnl": 0.0}},
            "time_in_trade": {"under_5min": 0, "5_15min": 0, "15_60min": 0, "over_60min": 0}
        }
        
        if not self.positions_data:
            print("   ❌ No positions data available")
            return results
        
        reversal_trades = [p for p in self.positions_data.get("closed_positions", []) 
                          if p.get("close_reason", "").startswith("ladder_signal_reverse")]
        
        results["reversal_stats"]["total"] = len(reversal_trades)
        
        for pos in reversal_trades:
            pnl = float(pos.get("realized_pnl", pos.get("pnl", 0)))
            results["reversal_stats"]["total_pnl"] += pnl
            
            if pnl > 0:
                results["reversal_stats"]["profitable"] += 1
            else:
                results["reversal_stats"]["losing"] += 1
            
            symbol = pos.get("symbol", "unknown")
            if symbol not in results["by_symbol"]:
                results["by_symbol"][symbol] = {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0}
            results["by_symbol"][symbol]["count"] += 1
            results["by_symbol"][symbol]["pnl"] += pnl
            if pnl > 0:
                results["by_symbol"][symbol]["wins"] += 1
            else:
                results["by_symbol"][symbol]["losses"] += 1
        
        total_rev = results["reversal_stats"]["total"]
        win_rate = (results["reversal_stats"]["profitable"] / total_rev * 100) if total_rev > 0 else 0
        
        print(f"\n📊 LADDER REVERSAL SUMMARY:")
        print(f"   - Total reversal trades: {total_rev}")
        print(f"   - Profitable: {results['reversal_stats']['profitable']}")
        print(f"   - Losing: {results['reversal_stats']['losing']}")
        print(f"   - Win Rate: {win_rate:.1f}%")
        print(f"   - Total P&L from reversals: ${results['reversal_stats']['total_pnl']:.2f}")
        
        if total_rev > 0:
            print(f"\n🪙 REVERSAL BY SYMBOL (Top 10 by count):")
            sorted_symbols = sorted(results["by_symbol"].items(), key=lambda x: -x[1]["count"])[:10]
            for symbol, data in sorted_symbols:
                wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
                print(f"   {symbol}: n={data['count']}, WR={wr:.1f}%, P&L=${data['pnl']:.2f}")
        
        self.analysis_results["stage_4_ladder_forensics"] = results
        return results
    
    def generate_remediation_report(self) -> Dict[str, Any]:
        """Stage 5: Generate Remediation Recommendations"""
        print("\n" + "=" * 70)
        print("STAGE 5: REMEDIATION RECOMMENDATIONS")
        print("=" * 70)
        
        recommendations = []
        
        signal_results = self.analysis_results.get("stage_2_signal_analysis", {})
        overall = signal_results.get("overall", {})
        
        if overall.get("win_rate", 0) < 30:
            recommendations.append({
                "priority": 1,
                "category": "SIGNAL_QUALITY",
                "issue": f"Very low win rate ({overall.get('win_rate', 0):.1f}%)",
                "impact": f"${abs(overall.get('total_pnl', 0)):.2f} in losses",
                "root_cause": "Signal logic may be generating low-quality entries or exiting too early",
                "fix": [
                    "1) Only trade when OFI is 'strong' or 'extreme' (|OFI| > 0.5)",
                    "2) Require OFI-direction alignment before entry",
                    "3) Increase minimum confidence threshold",
                    "4) Reduce ladder reversal sensitivity"
                ],
                "status": "NEEDS_ATTENTION"
            })
        
        by_ofi = signal_results.get("by_ofi_bucket", {})
        weak_ofi = by_ofi.get("weak", {})
        strong_ofi = by_ofi.get("strong", {})
        extreme_ofi = by_ofi.get("extreme", {})
        
        weak_wr = (weak_ofi.get("wins", 0) / weak_ofi.get("count", 1) * 100) if weak_ofi.get("count", 0) > 0 else 0
        strong_wr = (strong_ofi.get("wins", 0) / strong_ofi.get("count", 1) * 100) if strong_ofi.get("count", 0) > 0 else 0
        
        if weak_ofi.get("count", 0) > 50 and weak_wr < 15:
            recommendations.append({
                "priority": 2,
                "category": "OFI_FILTER",
                "issue": f"Weak OFI trades have {weak_wr:.1f}% win rate ({weak_ofi.get('count', 0)} trades)",
                "impact": f"${abs(weak_ofi.get('pnl', 0)):.2f} loss from weak OFI signals",
                "root_cause": "Trading on weak Order Flow Imbalance signals produces random results",
                "fix": [
                    "Block all trades where |OFI| < 0.3 (weak bucket)",
                    "Add OFI strength as a hard gate in signal validation"
                ],
                "status": "NEEDS_ATTENTION"
            })
        
        ladder = self.analysis_results.get("stage_4_ladder_forensics", {})
        reversal_stats = ladder.get("reversal_stats", {})
        if reversal_stats.get("total", 0) > 100:
            rev_wr = (reversal_stats.get("profitable", 0) / reversal_stats.get("total", 1) * 100)
            if rev_wr < 30:
                recommendations.append({
                    "priority": 2,
                    "category": "LADDER_TUNING",
                    "issue": f"Ladder reversals have {rev_wr:.1f}% win rate ({reversal_stats.get('total', 0)} reversals)",
                    "impact": f"${abs(reversal_stats.get('total_pnl', 0)):.2f} P&L from frequent reversals",
                    "root_cause": "Ladder controller is flip-flopping positions too aggressively",
                    "fix": [
                        "1) Increase reversal threshold - require stronger signal before flipping",
                        "2) Add cooldown period between reversals (e.g., 5 minutes)",
                        "3) Require OFI sign change before allowing reversal"
                    ],
                    "status": "NEEDS_ATTENTION"
                })
        
        ab_results = self.analysis_results.get("stage_3_alpha_beta_comparison", {})
        beta = ab_results.get("beta", {})
        if beta.get("trades", 0) == 0 and beta.get("blocked_count", 0) > 0:
            recommendations.append({
                "priority": 3,
                "category": "BETA_STRATEGY",
                "issue": f"Beta bot blocked {beta.get('blocked_count', 0)} signals but executed 0 trades",
                "impact": "Cannot evaluate inversion strategy",
                "root_cause": "Beta's signal inversion logic may be blocking all signals instead of inverting them",
                "fix": [
                    "1) Review Beta's signal_inversion.py logic",
                    "2) Ensure Beta is inverting direction, not just blocking",
                    "3) Run parallel simulation to compare Alpha vs Beta on same signals"
                ],
                "status": "NEEDS_INVESTIGATION"
            })
        
        alignment = signal_results.get("ofi_direction_alignment", {})
        aligned = alignment.get("aligned", {})
        misaligned = alignment.get("misaligned", {})
        aligned_total = aligned.get("wins", 0) + aligned.get("losses", 0)
        misaligned_total = misaligned.get("wins", 0) + misaligned.get("losses", 0)
        aligned_wr = (aligned.get("wins", 0) / aligned_total * 100) if aligned_total > 0 else 0
        misaligned_wr = (misaligned.get("wins", 0) / misaligned_total * 100) if misaligned_total > 0 else 0
        
        if misaligned_total > 50 and misaligned_wr < aligned_wr * 0.7:
            recommendations.append({
                "priority": 2,
                "category": "ALIGNMENT_GATE",
                "issue": f"Misaligned trades ({misaligned_wr:.1f}% WR) much worse than aligned ({aligned_wr:.1f}% WR)",
                "impact": f"${abs(misaligned.get('pnl', 0)):.2f} loss from misaligned trades",
                "root_cause": "Trading against OFI direction produces poor results",
                "fix": [
                    "1) Add hard gate: Only enter if trade direction matches OFI sign",
                    "2) For SHORT: require OFI < 0",
                    "3) For LONG: require OFI > 0"
                ],
                "status": "NEEDS_ATTENTION"
            })
        
        recommendations.sort(key=lambda x: x["priority"])
        
        print(f"\n📋 PRIORITIZED RECOMMENDATIONS ({len(recommendations)} items):")
        print("-" * 60)
        
        for i, rec in enumerate(recommendations, 1):
            status_icon = "✅" if rec["status"] == "FIXED" else "🔍" if rec["status"] == "NEEDS_INVESTIGATION" else "⚠️"
            print(f"\n{i}. [{rec['category']}] {status_icon}")
            print(f"   Issue: {rec['issue']}")
            print(f"   Impact: {rec['impact']}")
            print(f"   Root Cause: {rec['root_cause']}")
            print(f"   Fix:")
            if isinstance(rec['fix'], list):
                for fix in rec['fix']:
                    print(f"      {fix}")
            else:
                print(f"      {rec['fix']}")
        
        self.analysis_results["stage_5_remediation"] = {
            "recommendations": recommendations,
            "total_issues": len(recommendations),
            "pending_issues": sum(1 for r in recommendations if r["status"] == "NEEDS_ATTENTION")
        }
        
        return self.analysis_results["stage_5_remediation"]
    
    def generate_summary(self) -> str:
        """Generate executive summary"""
        print("\n" + "=" * 70)
        print("EXECUTIVE SUMMARY")
        print("=" * 70)
        
        signal = self.analysis_results.get("stage_2_signal_analysis", {}).get("overall", {})
        exec_data = self.analysis_results.get("stage_1_execution_forensics", {})
        ab = self.analysis_results.get("stage_3_alpha_beta_comparison", {})
        
        summary = []
        
        summary.append("\n📊 ROOT CAUSE ANALYSIS:")
        
        imm_rate = exec_data.get("immediate_closures", {}).get("rate", 0)
        if imm_rate < 5:
            summary.append(f"   ✅ Execution bugs FIXED (immediate closure rate: {imm_rate:.1f}%)")
        else:
            summary.append(f"   ⚠️ Execution bugs still present (immediate closure rate: {imm_rate:.1f}%)")
        
        wr = signal.get("win_rate", 0)
        summary.append(f"\n   🎯 SIGNAL QUALITY is the PRIMARY issue:")
        summary.append(f"      - Overall win rate: {wr:.1f}% (target: >45%)")
        summary.append(f"      - Average P&L per trade: ${signal.get('avg_pnl', 0):.2f}")
        summary.append(f"      - Total P&L: ${signal.get('total_pnl', 0):.2f}")
        
        by_ofi = self.analysis_results.get("stage_2_signal_analysis", {}).get("by_ofi_bucket", {})
        if by_ofi:
            summary.append(f"\n   📈 OFI BUCKET ANALYSIS (Key Finding):")
            for bucket in ["extreme", "very_strong", "strong", "moderate", "weak"]:
                if bucket in by_ofi:
                    data = by_ofi[bucket]
                    bucket_wr = (data["wins"] / data["count"] * 100) if data["count"] > 0 else 0
                    summary.append(f"      - {bucket}: {bucket_wr:.1f}% WR, ${data['pnl']:.2f} P&L (n={data['count']})")
        
        summary.append(f"\n🎯 KEY ACTIONS TO IMPROVE:")
        summary.append("   1. Block trades where |OFI| < 0.3 (weak signals)")
        summary.append("   2. Require OFI-direction alignment (OFI sign matches trade direction)")
        summary.append("   3. Reduce ladder reversal sensitivity (add cooldown/threshold)")
        summary.append("   4. Focus on symbols with positive P&L history")
        
        summary_text = "\n".join(summary)
        print(summary_text)
        
        return summary_text
    
    def save_report(self):
        """Save full analysis report to file"""
        report_path = "logs/comprehensive_analysis_report.json"
        with open(report_path, 'w') as f:
            json.dump(self.analysis_results, f, indent=2, default=str)
        print(f"\n💾 Full report saved to: {report_path}")
    
    def run_full_analysis(self):
        """Run complete analysis pipeline"""
        print("\n" + "=" * 70)
        print("COMPREHENSIVE TRADE ANALYSIS - DEEP DIVE POSTMORTEM v2")
        print("=" * 70)
        print(f"Analysis started: {datetime.now().isoformat()}")
        
        self.load_all_data()
        self.analyze_execution_bugs()
        self.analyze_signal_quality()
        self.analyze_alpha_beta_comparison()
        self.analyze_ladder_reversals()
        self.generate_remediation_report()
        self.generate_summary()
        self.save_report()
        
        print("\n" + "=" * 70)
        print("ANALYSIS COMPLETE")
        print("=" * 70)
        
        return self.analysis_results


if __name__ == "__main__":
    analyzer = ComprehensiveTradeAnalysis()
    results = analyzer.run_full_analysis()
