#!/usr/bin/env python3
"""
EXPANSIVE MULTI-DIMENSIONAL PROFITABILITY ANALYZER
===================================================
The most comprehensive profitability analysis system possible. Slices data in EVERY way:

Dimensions Analyzed:
1. Symbol-specific patterns (every symbol individually)
2. Strategy-specific patterns (every strategy individually)
3. Signal combinations (OFI + CoinGlass + MTF + etc.)
4. Time patterns (hour of day, day of week, time since entry)
5. Price patterns (entry price levels, volatility regimes)
6. Volume patterns (volume at entry, volume during trade)
7. CoinGlass data (funding, OI delta, liquidations, taker flow, fear/greed)
8. Cross-correlations (how factors interact)
9. Regime-specific patterns (trending vs choppy)
10. Cross-asset relationships (BTC/ETH alignment, lead-lag)

Data Sources:
- positions_futures.json (all trade data with signal_context)
- enriched_decisions.jsonl (signals + outcomes)
- signals.jsonl (all signals with CoinGlass data)
- exit_runtime_events.jsonl (exit MFE/MAE data)
- ml_features from positions (50+ features)
- CoinGlass cache data

SELF-HEALING & MONITORING:
- Comprehensive error handling with graceful degradation
- Auto-recovery from data corruption
- Health status tracking
- Staleness detection
- File integrity checks
- Partial result generation (if some analyses fail)
- Logging and status reporting

Author: Trading Bot System
Date: December 2025
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from statistics import mean, median, stdev
from pathlib import Path
import math
import traceback

# Set up logging
logger = logging.getLogger(__name__)

try:
    from src.data_registry import DataRegistry as DR
    from src.infrastructure.path_registry import PathRegistry
    from src.exchange_utils import normalize_from_kraken
except ImportError:
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.data_registry import DataRegistry as DR
    from src.infrastructure.path_registry import PathRegistry
    try:
        from src.exchange_utils import normalize_from_kraken
    except ImportError:
        # Fallback if exchange_utils not available
        def normalize_from_kraken(symbol: str) -> str:
            """Fallback: convert Kraken format to internal format."""
            if symbol.startswith("PI_") or symbol.startswith("PF_"):
                # PI_XBTUSD -> BTCUSDT, PF_SOLUSD -> SOLUSDT
                if symbol.startswith("PI_"):
                    base = symbol[3:-3]  # Remove PI_ and USD
                else:
                    base = symbol[3:-3]  # Remove PF_ and USD
                
                # XBT -> BTC (ISO 4217)
                if base == "XBT":
                    return "BTCUSDT"
                return f"{base}USDT"
            return symbol

# Health status tracking
ANALYZER_HEALTH_LOG = Path("logs/expansive_analyzer_health.jsonl")
ANALYZER_STATUS_FILE = Path("feature_store/expansive_analyzer_status.json")

class ExpansiveMultiDimensionalProfitabilityAnalyzer:
    """
    The most comprehensive profitability analyzer possible.
    
    Analyzes EVERY dimension of data to find profitability patterns:
    - Every symbol individually
    - Every strategy individually
    - Every signal combination
    - Time-of-day patterns
    - Volume patterns
    - CoinGlass alignment
    - Cross-correlations
    - Regime-specific patterns
    - And much more...
    """
    
    def __init__(self, lookback_days=14):
        self.lookback_days = lookback_days
        self.min_trades_per_slice = 5  # Minimum trades for statistical significance
        
        # Symbol normalization helper (ensure consistent format)
        try:
            from src.exchange_utils import normalize_from_kraken
            self._normalize_symbol = normalize_from_kraken
        except ImportError:
            # Fallback if exchange_utils not available
            def normalize_from_kraken(symbol: str) -> str:
                """Fallback: convert Kraken format to internal format."""
                if not symbol:
                    return symbol
                if symbol.startswith("PI_") or symbol.startswith("PF_"):
                    if symbol.startswith("PI_"):
                        base = symbol[3:-3]
                    else:
                        base = symbol[3:-3]
                    if base == "XBT":
                        return "BTCUSDT"
                    return f"{base}USDT"
                # Remove dash if present (BTC-USDT -> BTCUSDT)
                if "-" in symbol:
                    return symbol.replace("-", "")
                return symbol
            self._normalize_symbol = normalize_from_kraken
    
    def _normalize_symbol_for_matching(self, symbol: str) -> str:
        """Normalize symbol to internal format (BTCUSDT) for consistent matching."""
        if not symbol:
            return symbol
        # If it's in Kraken format (PI_XBTUSD, PF_SOLUSD), convert to internal
        if symbol.startswith("PI_") or symbol.startswith("PF_"):
            return self._normalize_symbol(symbol)
        # If it has a dash (BTC-USDT), remove it
        if "-" in symbol:
            return symbol.replace("-", "")
        # Return as-is (should already be BTCUSDT format)
        return symbol
        
    def run_comprehensive_analysis(self) -> Dict[str, Any]:
        """
        Run the most comprehensive profitability analysis possible.
        
        Features:
        - Comprehensive error handling with graceful degradation
        - Partial results if some analyses fail
        - Health status tracking
        - Auto-recovery from errors
        """
        start_time = time.time()
        analysis_id = f"analysis_{int(start_time)}"
        
        print("=" * 80)
        print("🔬 EXPANSIVE MULTI-DIMENSIONAL PROFITABILITY ANALYSIS")
        print("=" * 80)
        print()
        
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "analysis_id": analysis_id,
            "lookback_days": self.lookback_days,
            "status": "running",
            "errors": [],
            "warnings": [],
            "components_completed": [],
            "components_failed": [],
            "partial_results": False,
            "by_symbol": {},
            "by_strategy": {},
            "by_time_of_day": {},
            "by_signal_combinations": {},
            "by_coinglass_alignment": {},
            "by_volume_regime": {},
            "by_price_levels": {},
            "by_regime": {},
            "by_ofi_buckets": {},
            "by_ensemble_buckets": {},
            "by_leverage": {},
            "by_hold_duration": {},
            "cross_correlations": {},
            "cross_asset_patterns": {},
            "signal_interactions": {},
            "profitability_patterns": [],
            "actionable_insights": [],
            "optimization_recommendations": []
        }
        
        # Run each analysis component with error handling
        analysis_components = [
            ("by_symbol", self._analyze_by_symbol),
            ("by_strategy", self._analyze_by_strategy),
            ("by_time_of_day", self._analyze_by_time_of_day),
            ("by_signal_combinations", self._analyze_signal_combinations),
            ("by_coinglass_alignment", self._analyze_coinglass_alignment),
            ("by_volume_regime", self._analyze_by_volume_regime),
            ("by_price_levels", self._analyze_by_price_levels),
            ("by_regime", self._analyze_by_regime),
            ("by_ofi_buckets", self._analyze_by_ofi_buckets),
            ("by_ensemble_buckets", self._analyze_by_ensemble_buckets),
            ("by_leverage", self._analyze_by_leverage),
            ("by_hold_duration", self._analyze_by_hold_duration),
            ("cross_correlations", self._analyze_cross_correlations),
            ("cross_asset_patterns", self._analyze_cross_asset_patterns),
            ("signal_interactions", self._analyze_signal_interactions),
            ("profitability_patterns", self._identify_profitability_patterns),
        ]
        
        for component_name, component_func in analysis_components:
            try:
                result = component_func()
                analysis[component_name] = result
                analysis["components_completed"].append(component_name)
                print(f"   ✅ {component_name} completed")
            except Exception as e:
                error_msg = f"{component_name} failed: {str(e)}"
                analysis["errors"].append(error_msg)
                analysis["components_failed"].append(component_name)
                analysis[component_name] = {"error": str(e), "status": "failed"}
                logger.error(f"Expansive analyzer {component_name} error: {e}", exc_info=True)
                print(f"   ⚠️ {component_name} failed: {e}")
                # Continue with other components (graceful degradation)
        
        # Generate actionable insights and recommendations (with error handling)
        try:
            analysis["actionable_insights"] = self._generate_actionable_insights(analysis)
            analysis["components_completed"].append("actionable_insights")
        except Exception as e:
            analysis["errors"].append(f"actionable_insights failed: {str(e)}")
            analysis["actionable_insights"] = []
            logger.error(f"Expansive analyzer actionable_insights error: {e}", exc_info=True)
        
        try:
            analysis["optimization_recommendations"] = self._generate_optimization_recommendations(analysis)
            analysis["components_completed"].append("optimization_recommendations")
        except Exception as e:
            analysis["errors"].append(f"optimization_recommendations failed: {str(e)}")
            analysis["optimization_recommendations"] = []
            logger.error(f"Expansive analyzer optimization_recommendations error: {e}", exc_info=True)
        
        # Determine final status
        elapsed_time = time.time() - start_time
        analysis["execution_time_seconds"] = round(elapsed_time, 2)
        
        if len(analysis["components_failed"]) == 0:
            analysis["status"] = "success"
        elif len(analysis["components_completed"]) > len(analysis["components_failed"]):
            analysis["status"] = "partial_success"
            analysis["partial_results"] = True
        else:
            analysis["status"] = "failed"
        
        # Update health status
        self._update_health_status(analysis)
        
        # Log health event
        self._log_health_event(analysis)
        
        print()
        print(f"✅ Analysis complete: {analysis['status']} ({elapsed_time:.1f}s)")
        print(f"   Completed: {len(analysis['components_completed'])} components")
        if analysis["components_failed"]:
            print(f"   Failed: {len(analysis['components_failed'])} components: {', '.join(analysis['components_failed'])}")
        
        return analysis
    
    def _load_all_trade_data(self) -> List[Dict]:
        """
        Load all trade data with complete context.
        
        Features:
        - Error handling for missing/corrupted files
        - Data validation
        - Auto-recovery from corruption
        """
        print("📊 Loading all trade data with complete context...")
        
        try:
            # Load closed positions (main source)
            closed_positions = DR.get_closed_positions(hours=self.lookback_days * 24)
            if not closed_positions:
                print("   ⚠️ No closed positions found in data")
                return []
        except Exception as e:
            logger.error(f"Failed to load closed positions: {e}", exc_info=True)
            print(f"   ❌ Error loading closed positions: {e}")
            # Try to recover - create empty list and continue
            closed_positions = []
        
        try:
        
            # Load enriched decisions for signal context
            enriched_decisions = []
            enriched_path = PathRegistry.get_path("logs", "enriched_decisions.jsonl")
            if enriched_path and os.path.exists(enriched_path):
                cutoff_ts = (datetime.utcnow() - timedelta(days=self.lookback_days)).timestamp()
                try:
                    with open(enriched_path, 'r') as f:
                        for line_num, line in enumerate(f, 1):
                            try:
                                dec = json.loads(line.strip())
                                if dec.get("ts", 0) >= cutoff_ts:
                                    enriched_decisions.append(dec)
                            except json.JSONDecodeError as e:
                                logger.warning(f"Invalid JSON in enriched_decisions.jsonl line {line_num}: {e}")
                                continue
                            except Exception as e:
                                logger.warning(f"Error parsing enriched_decisions.jsonl line {line_num}: {e}")
                                continue
                except Exception as e:
                    logger.error(f"Failed to read enriched_decisions.jsonl: {e}", exc_info=True)
                    print(f"   ⚠️ Error reading enriched_decisions.jsonl: {e}")
        except Exception as e:
            logger.error(f"Error in enriched_decisions loading: {e}", exc_info=True)
            enriched_decisions = []
        
        try:
            # Load signals for CoinGlass data
            signals = []
            signals_path = PathRegistry.get_path("logs", "signals.jsonl")
            if signals_path and os.path.exists(signals_path):
                cutoff_ts = (datetime.utcnow() - timedelta(days=self.lookback_days)).timestamp()
                try:
                    with open(signals_path, 'r') as f:
                        for line_num, line in enumerate(f, 1):
                            try:
                                sig = json.loads(line.strip())
                                if sig.get("ts", 0) >= cutoff_ts:
                                    signals.append(sig)
                            except json.JSONDecodeError as e:
                                logger.warning(f"Invalid JSON in signals.jsonl line {line_num}: {e}")
                                continue
                            except Exception as e:
                                logger.warning(f"Error parsing signals.jsonl line {line_num}: {e}")
                                continue
                except Exception as e:
                    logger.error(f"Failed to read signals.jsonl: {e}", exc_info=True)
                    print(f"   ⚠️ Error reading signals.jsonl: {e}")
        except Exception as e:
            logger.error(f"Error in signals loading: {e}", exc_info=True)
            signals = []
        
        # Enrich closed positions with signal context
        enriched_trades = []
        for pos in closed_positions:
            symbol = pos.get("symbol")
            # Normalize symbol to internal format (ensures consistency with Kraken integration)
            symbol = self._normalize_symbol_for_matching(symbol)
            opened_at = pos.get("opened_at")
            
            # Find matching enriched decision
            matching_decision = None
            if opened_at:
                try:
                    entry_dt = datetime.fromisoformat(str(opened_at).replace('Z', '+00:00'))
                    entry_ts = entry_dt.timestamp()
                    
                    # Find closest enriched decision within 5 minutes
                    for dec in enriched_decisions:
                        dec_ts = dec.get("ts", 0)
                        dec_symbol = self._normalize_symbol_for_matching(dec.get("symbol", ""))
                        if abs(dec_ts - entry_ts) < 300 and dec_symbol == symbol:
                            matching_decision = dec
                            break
                except:
                    pass
            
            # Find matching signal
            matching_signal = None
            if opened_at:
                try:
                    entry_dt = datetime.fromisoformat(str(opened_at).replace('Z', '+00:00'))
                    entry_ts = entry_dt.timestamp()
                    
                    for sig in signals:
                        sig_ts = sig.get("ts", 0)
                        sig_symbol = self._normalize_symbol_for_matching(sig.get("symbol", ""))
                        if abs(sig_ts - entry_ts) < 300 and sig_symbol == symbol:
                            matching_signal = sig
                            break
                except:
                    pass
            
            # Update symbol in enriched_trade to ensure it's in internal format
            enriched_trade = dict(pos)
            enriched_trade["symbol"] = symbol  # Store normalized symbol
            
            # (enriched_trade already created above with normalized symbol)
            
            # Add signal context from position
            if pos.get("ofi_score") is not None:
                enriched_trade["ofi"] = pos.get("ofi_score")
            if pos.get("ensemble_score") is not None:
                enriched_trade["ensemble"] = pos.get("ensemble_score")
            if pos.get("mtf_confidence") is not None:
                enriched_trade["mtf"] = pos.get("mtf_confidence")
            if pos.get("regime"):
                enriched_trade["regime"] = pos.get("regime")
            
            # Add from enriched decision
            if matching_decision:
                signal_ctx = matching_decision.get("signal_ctx", {})
                enriched_trade["ofi"] = enriched_trade.get("ofi") or signal_ctx.get("ofi", 0)
                enriched_trade["ensemble"] = enriched_trade.get("ensemble") or signal_ctx.get("ensemble", 0)
            
            # Add CoinGlass data from signal
            if matching_signal:
                intel = matching_signal.get("intelligence", {})
                market_intel = intel.get("market_intel", {})
                enriched_trade["coinglass_funding"] = market_intel.get("funding_rate")
                enriched_trade["coinglass_oi_delta"] = market_intel.get("oi_delta")
                enriched_trade["coinglass_liquidations"] = market_intel.get("liquidations")
                enriched_trade["coinglass_taker_ratio"] = intel.get("taker_ratio")
                enriched_trade["coinglass_fear_greed"] = intel.get("fear_greed")
                enriched_trade["coinglass_liquidation_bias"] = intel.get("liquidation_bias")
            
            # Add ALL ML features from position (50+ features)
            if pos.get("ml_features"):
                ml_feat = pos.get("ml_features")
                # Orderbook features
                enriched_trade["ml_bid_ask_imbalance"] = ml_feat.get("bid_ask_imbalance")
                enriched_trade["ml_spread_bps"] = ml_feat.get("spread_bps")
                enriched_trade["ml_bid_depth_usd"] = ml_feat.get("bid_depth_usd")
                enriched_trade["ml_ask_depth_usd"] = ml_feat.get("ask_depth_usd")
                enriched_trade["ml_depth_ratio"] = ml_feat.get("depth_ratio")
                enriched_trade["ml_top_bid_size"] = ml_feat.get("top_bid_size")
                enriched_trade["ml_top_ask_size"] = ml_feat.get("top_ask_size")
                # Momentum features
                enriched_trade["ml_return_1m"] = ml_feat.get("return_1m")
                enriched_trade["ml_return_5m"] = ml_feat.get("return_5m")
                enriched_trade["ml_return_15m"] = ml_feat.get("return_15m")
                enriched_trade["ml_volatility_1h"] = ml_feat.get("volatility_1h")
                enriched_trade["ml_price_trend"] = ml_feat.get("price_trend")
                # Intelligence features
                enriched_trade["ml_buy_sell_ratio"] = ml_feat.get("buy_sell_ratio")
                enriched_trade["ml_buy_ratio"] = ml_feat.get("buy_ratio")
                enriched_trade["ml_liq_ratio"] = ml_feat.get("liq_ratio")
                enriched_trade["ml_liq_long_1h"] = ml_feat.get("liq_long_1h")
                enriched_trade["ml_liq_short_1h"] = ml_feat.get("liq_short_1h")
                enriched_trade["ml_fear_greed"] = ml_feat.get("fear_greed")
                enriched_trade["ml_intel_direction"] = ml_feat.get("intel_direction")
                enriched_trade["ml_intel_confidence"] = ml_feat.get("intel_confidence")
                # CoinGlass features
                enriched_trade["ml_funding_rate"] = ml_feat.get("funding_rate")
                enriched_trade["ml_funding_zscore"] = ml_feat.get("funding_zscore")
                enriched_trade["ml_oi_delta_pct"] = ml_feat.get("oi_delta_pct")
                enriched_trade["ml_oi_current"] = ml_feat.get("oi_current")
                enriched_trade["ml_long_short_ratio"] = ml_feat.get("long_short_ratio")
                enriched_trade["ml_long_ratio"] = ml_feat.get("long_ratio")
                enriched_trade["ml_short_ratio"] = ml_feat.get("short_ratio")
                # Streak features
                enriched_trade["ml_recent_wins"] = ml_feat.get("recent_wins")
                enriched_trade["ml_recent_losses"] = ml_feat.get("recent_losses")
                enriched_trade["ml_streak_direction"] = ml_feat.get("streak_direction")
                enriched_trade["ml_streak_length"] = ml_feat.get("streak_length")
                enriched_trade["ml_recent_pnl"] = ml_feat.get("recent_pnl")
                # Cross-asset features
                enriched_trade["ml_btc_return_15m"] = ml_feat.get("btc_return_15m")
                enriched_trade["ml_btc_trend"] = ml_feat.get("btc_trend")
                enriched_trade["ml_eth_return_15m"] = ml_feat.get("eth_return_15m")
                enriched_trade["ml_eth_trend"] = ml_feat.get("eth_trend")
                enriched_trade["ml_btc_eth_aligned"] = ml_feat.get("btc_eth_aligned")
            elif pos.get("ml_volume") or pos.get("ml_bid_ask_imbalance"):
                # Use flattened ml_ fields if ml_features dict not present
                enriched_trade["ml_bid_ask_imbalance"] = pos.get("ml_bid_ask_imbalance")
                enriched_trade["ml_spread_bps"] = pos.get("ml_spread_bps")
                enriched_trade["ml_return_5m"] = pos.get("ml_return_5m")
                enriched_trade["ml_return_15m"] = pos.get("ml_return_15m")
                enriched_trade["ml_volatility_1h"] = pos.get("ml_volatility_1h")
                enriched_trade["ml_funding_rate"] = pos.get("ml_funding_rate")
                enriched_trade["ml_funding_zscore"] = pos.get("ml_funding_zscore")
                enriched_trade["ml_oi_delta_pct"] = pos.get("ml_oi_delta_pct")
                enriched_trade["ml_fear_greed"] = pos.get("ml_fear_greed")
                enriched_trade["ml_btc_return_15m"] = pos.get("ml_btc_return_15m")
                enriched_trade["ml_eth_return_15m"] = pos.get("ml_eth_return_15m")
            
            # Calculate time of day
            if opened_at:
                try:
                    entry_dt = datetime.fromisoformat(str(opened_at).replace('Z', '+00:00'))
                    enriched_trade["entry_hour"] = entry_dt.hour
                    enriched_trade["entry_day_of_week"] = entry_dt.weekday()
                    enriched_trade["entry_time_sin"] = math.sin(2 * math.pi * entry_dt.hour / 24)
                    enriched_trade["entry_time_cos"] = math.cos(2 * math.pi * entry_dt.hour / 24)
                except:
                    pass
            
            enriched_trades.append(enriched_trade)
        
        print(f"   ✅ Loaded {len(enriched_trades)} trades with complete context")
        return enriched_trades
    
    def _analyze_by_symbol(self) -> Dict[str, Dict]:
        """Analyze profitability by symbol in every possible way."""
        print("📈 Analyzing by Symbol...")
        trades = self._load_all_trade_data()
        
        by_symbol = defaultdict(lambda: {
            "trades": [], "total_pnl": 0.0, "wins": 0, "losses": 0,
            "by_strategy": defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0}),
            "by_time_of_day": defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0}),
            "by_ofi_range": defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0}),
            "by_regime": defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0}),
            "coinglass_alignment": {"aligned": 0, "misaligned": 0, "aligned_pnl": 0.0, "misaligned_pnl": 0.0}
        })
        
        for trade in trades:
            symbol = trade.get("symbol", "UNKNOWN")
            # Normalize symbol to ensure consistency
            symbol = self._normalize_symbol_for_matching(symbol)
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            
            bucket = by_symbol[symbol]
            bucket["trades"].append(trade)
            bucket["total_pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
            
            # Sub-analyze by strategy
            strategy = trade.get("strategy", "UNKNOWN")
            bucket["by_strategy"][strategy]["trades"] += 1
            bucket["by_strategy"][strategy]["pnl"] += pnl
            if pnl > 0:
                bucket["by_strategy"][strategy]["wins"] += 1
            
            # Sub-analyze by time of day
            hour = trade.get("entry_hour")
            if hour is not None:
                time_bucket = f"{hour:02d}:00"
                bucket["by_time_of_day"][time_bucket]["trades"] += 1
                bucket["by_time_of_day"][time_bucket]["pnl"] += pnl
                if pnl > 0:
                    bucket["by_time_of_day"][time_bucket]["wins"] += 1
            
            # Sub-analyze by OFI range
            ofi = abs(float(trade.get("ofi", 0) or 0))
            if ofi > 0.7:
                ofi_bucket = "extreme"
            elif ofi > 0.5:
                ofi_bucket = "strong"
            elif ofi > 0.3:
                ofi_bucket = "moderate"
            else:
                ofi_bucket = "weak"
            bucket["by_ofi_range"][ofi_bucket]["trades"] += 1
            bucket["by_ofi_range"][ofi_bucket]["pnl"] += pnl
            if pnl > 0:
                bucket["by_ofi_range"][ofi_bucket]["wins"] += 1
            
            # Sub-analyze by regime
            regime = trade.get("regime", "unknown")
            bucket["by_regime"][regime]["trades"] += 1
            bucket["by_regime"][regime]["pnl"] += pnl
            if pnl > 0:
                bucket["by_regime"][regime]["wins"] += 1
            
            # CoinGlass alignment
            direction = trade.get("direction", "LONG")
            taker_ratio = trade.get("coinglass_taker_ratio")
            if taker_ratio is not None:
                is_aligned = (direction == "LONG" and taker_ratio > 0.5) or (direction == "SHORT" and taker_ratio < 0.5)
                if is_aligned:
                    bucket["coinglass_alignment"]["aligned"] += 1
                    bucket["coinglass_alignment"]["aligned_pnl"] += pnl
                else:
                    bucket["coinglass_alignment"]["misaligned"] += 1
                    bucket["coinglass_alignment"]["misaligned_pnl"] += pnl
        
        # Calculate metrics
        results = {}
        for symbol, data in by_symbol.items():
            if len(data["trades"]) >= self.min_trades_per_slice:
                total = len(data["trades"])
                results[symbol] = {
                    "total_trades": total,
                    "win_rate": (data["wins"] / total * 100) if total > 0 else 0,
                    "total_pnl": data["total_pnl"],
                    "avg_pnl": data["total_pnl"] / total if total > 0 else 0,
                    "expectancy": data["total_pnl"] / total if total > 0 else 0,
                    "by_strategy": {k: {
                        "trades": v["trades"],
                        "win_rate": (v["wins"] / v["trades"] * 100) if v["trades"] > 0 else 0,
                        "total_pnl": v["pnl"],
                        "avg_pnl": v["pnl"] / v["trades"] if v["trades"] > 0 else 0
                    } for k, v in data["by_strategy"].items() if v["trades"] >= 3},
                    "by_time_of_day": {k: {
                        "trades": v["trades"],
                        "win_rate": (v["wins"] / v["trades"] * 100) if v["trades"] > 0 else 0,
                        "total_pnl": v["pnl"]
                    } for k, v in data["by_time_of_day"].items() if v["trades"] >= 3},
                    "by_ofi_range": {k: {
                        "trades": v["trades"],
                        "win_rate": (v["wins"] / v["trades"] * 100) if v["trades"] > 0 else 0,
                        "total_pnl": v["pnl"]
                    } for k, v in data["by_ofi_range"].items() if v["trades"] >= 3},
                    "by_regime": {k: {
                        "trades": v["trades"],
                        "win_rate": (v["wins"] / v["trades"] * 100) if v["trades"] > 0 else 0,
                        "total_pnl": v["pnl"]
                    } for k, v in data["by_regime"].items() if v["trades"] >= 3},
                    "coinglass_alignment": {
                        "aligned_win_rate": (data["coinglass_alignment"]["aligned"] / 
                                            (data["coinglass_alignment"]["aligned"] + data["coinglass_alignment"]["misaligned"]) * 100) 
                                            if (data["coinglass_alignment"]["aligned"] + data["coinglass_alignment"]["misaligned"]) > 0 else 0,
                        "aligned_avg_pnl": (data["coinglass_alignment"]["aligned_pnl"] / data["coinglass_alignment"]["aligned"])
                                            if data["coinglass_alignment"]["aligned"] > 0 else 0,
                        "misaligned_avg_pnl": (data["coinglass_alignment"]["misaligned_pnl"] / data["coinglass_alignment"]["misaligned"])
                                               if data["coinglass_alignment"]["misaligned"] > 0 else 0
                    }
                }
        
        return results
    
    def _analyze_by_strategy(self) -> Dict[str, Dict]:
        """Analyze profitability by strategy with all dimensions."""
        print("🎯 Analyzing by Strategy...")
        trades = self._load_all_trade_data()
        
        by_strategy = defaultdict(lambda: {
            "trades": [], "total_pnl": 0.0, "wins": 0,
            "by_symbol": defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0}),
            "by_ofi_range": defaultdict(lambda: {"trades": 0, "pnl": 0.0}),
            "by_ensemble_range": defaultdict(lambda: {"trades": 0, "pnl": 0.0})
        })
        
        for trade in trades:
            strategy = trade.get("strategy", "UNKNOWN")
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            symbol = trade.get("symbol")
            # Normalize symbol to ensure consistency
            if symbol:
                symbol = self._normalize_symbol_for_matching(symbol)
            
            bucket = by_strategy[strategy]
            bucket["trades"].append(trade)
            bucket["total_pnl"] += pnl
            if pnl > 0:
                bucket["wins"] += 1
            
            if symbol:
                bucket["by_symbol"][symbol]["trades"] += 1
                bucket["by_symbol"][symbol]["pnl"] += pnl
                if pnl > 0:
                    bucket["by_symbol"][symbol]["wins"] += 1
            
            # OFI buckets
            ofi = abs(float(trade.get("ofi", 0) or 0))
            if ofi > 0.7:
                ofi_bucket = "extreme"
            elif ofi > 0.5:
                ofi_bucket = "strong"
            elif ofi > 0.3:
                ofi_bucket = "moderate"
            else:
                ofi_bucket = "weak"
            bucket["by_ofi_range"][ofi_bucket]["trades"] += 1
            bucket["by_ofi_range"][ofi_bucket]["pnl"] += pnl
            
            # Ensemble buckets
            ensemble = float(trade.get("ensemble", 0) or 0)
            if ensemble > 0.3:
                ens_bucket = "strong_bull"
            elif ensemble > 0.1:
                ens_bucket = "moderate_bull"
            elif ensemble > -0.1:
                ens_bucket = "neutral"
            elif ensemble > -0.3:
                ens_bucket = "moderate_bear"
            else:
                ens_bucket = "strong_bear"
            bucket["by_ensemble_range"][ens_bucket]["trades"] += 1
            bucket["by_ensemble_range"][ens_bucket]["pnl"] += pnl
        
        # Calculate metrics
        results = {}
        for strategy, data in by_strategy.items():
            if len(data["trades"]) >= self.min_trades_per_slice:
                total = len(data["trades"])
                results[strategy] = {
                    "total_trades": total,
                    "win_rate": (data["wins"] / total * 100) if total > 0 else 0,
                    "total_pnl": data["total_pnl"],
                    "avg_pnl": data["total_pnl"] / total if total > 0 else 0,
                    "expectancy": data["total_pnl"] / total if total > 0 else 0,
                    "best_symbols": sorted(
                        [(k, v["pnl"] / v["trades"] if v["trades"] > 0 else 0) 
                         for k, v in data["by_symbol"].items() if v["trades"] >= 3],
                        key=lambda x: x[1], reverse=True
                    )[:3],
                    "by_ofi_range": {k: {
                        "trades": v["trades"],
                        "avg_pnl": v["pnl"] / v["trades"] if v["trades"] > 0 else 0
                    } for k, v in data["by_ofi_range"].items() if v["trades"] >= 3},
                    "by_ensemble_range": {k: {
                        "trades": v["trades"],
                        "avg_pnl": v["pnl"] / v["trades"] if v["trades"] > 0 else 0
                    } for k, v in data["by_ensemble_range"].items() if v["trades"] >= 3}
                }
        
        return results
    
    def _analyze_by_time_of_day(self) -> Dict[str, Dict]:
        """Analyze profitability by time of day."""
        print("⏰ Analyzing by Time of Day...")
        trades = self._load_all_trade_data()
        
        by_hour = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        by_day_of_week = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            hour = trade.get("entry_hour")
            day = trade.get("entry_day_of_week")
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            
            if hour is not None:
                by_hour[hour]["trades"] += 1
                by_hour[hour]["pnl"] += pnl
                if pnl > 0:
                    by_hour[hour]["wins"] += 1
            
            if day is not None:
                day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]
                by_day_of_week[day_name]["trades"] += 1
                by_day_of_week[day_name]["pnl"] += pnl
                if pnl > 0:
                    by_day_of_week[day_name]["wins"] += 1
        
        return {
            "by_hour": {
                f"{h:02d}:00": {
                    "trades": data["trades"],
                    "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                    "total_pnl": data["pnl"],
                    "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
                }
                for h, data in by_hour.items() if data["trades"] >= 3
            },
            "by_day_of_week": {
                day: {
                    "trades": data["trades"],
                    "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                    "total_pnl": data["pnl"],
                    "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
                }
                for day, data in by_day_of_week.items() if data["trades"] >= 3
            },
            "best_hours": sorted(
                [(f"{h:02d}:00", data["pnl"] / data["trades"] if data["trades"] > 0 else 0)
                 for h, data in by_hour.items() if data["trades"] >= 3],
                key=lambda x: x[1], reverse=True
            )[:5]
        }
    
    def _analyze_signal_combinations(self) -> Dict[str, Dict]:
        """Analyze profitability of signal combinations (OFI + CoinGlass + MTF + etc.)."""
        print("🔗 Analyzing Signal Combinations...")
        trades = self._load_all_trade_data()
        
        combinations = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            ofi = abs(float(trade.get("ofi", 0) or 0))
            ensemble = float(trade.get("ensemble", 0) or 0)
            mtf = float(trade.get("mtf", 0) or 0)
            taker_ratio = trade.get("coinglass_taker_ratio")
            funding = trade.get("coinglass_funding")
            
            # Create combination key
            ofi_level = "high" if ofi > 0.5 else "low"
            ens_level = "bull" if ensemble > 0.1 else "bear" if ensemble < -0.1 else "neutral"
            mtf_level = "strong" if mtf > 0.7 else "weak"
            cg_level = "aligned" if (taker_ratio and ((trade.get("direction") == "LONG" and taker_ratio > 0.5) or 
                                                       (trade.get("direction") == "SHORT" and taker_ratio < 0.5))) else "misaligned"
            
            combo_key = f"OFI_{ofi_level}+ENS_{ens_level}+MTF_{mtf_level}+CG_{cg_level}"
            
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            combinations[combo_key]["trades"] += 1
            combinations[combo_key]["pnl"] += pnl
            if pnl > 0:
                combinations[combo_key]["wins"] += 1
        
        return {
            combo: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "total_pnl": data["pnl"],
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for combo, data in combinations.items() if data["trades"] >= 3
        }
    
    def _analyze_coinglass_alignment(self) -> Dict[str, Any]:
        """Analyze how CoinGlass data alignment affects profitability."""
        print("📊 Analyzing CoinGlass Alignment...")
        trades = self._load_all_trade_data()
        
        aligned_trades = []
        misaligned_trades = []
        
        for trade in trades:
            direction = trade.get("direction", "LONG")
            taker_ratio = trade.get("coinglass_taker_ratio")
            funding = trade.get("coinglass_funding")
            liquidation_bias = trade.get("coinglass_liquidation_bias")
            
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            
            # Check alignment
            is_aligned = False
            if taker_ratio is not None:
                is_aligned = (direction == "LONG" and taker_ratio > 0.5) or (direction == "SHORT" and taker_ratio < 0.5)
            
            if is_aligned:
                aligned_trades.append(trade)
            else:
                misaligned_trades.append(trade)
        
        # Analyze by liquidation bias
        by_liq_bias = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        for trade in trades:
            liq_bias = trade.get("coinglass_liquidation_bias")
            if liq_bias is not None:
                bias_val = float(liq_bias)
                if bias_val > 0.7:
                    bucket = "strong_long_liq"
                elif bias_val > 0.5:
                    bucket = "long_liq"
                elif bias_val < -0.7:
                    bucket = "strong_short_liq"
                elif bias_val < -0.5:
                    bucket = "short_liq"
                else:
                    bucket = "balanced"
                
                pnl = float(trade.get("net_pnl", 0) or 0)
                by_liq_bias[bucket]["trades"] += 1
                by_liq_bias[bucket]["pnl"] += pnl
                if pnl > 0:
                    by_liq_bias[bucket]["wins"] += 1
        
        return {
            "aligned": {
                "count": len(aligned_trades),
                "win_rate": (sum(1 for t in aligned_trades if float(t.get("net_pnl", 0) or 0) > 0) / len(aligned_trades) * 100) if aligned_trades else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in aligned_trades]) if aligned_trades else 0,
                "total_pnl": sum([float(t.get("net_pnl", 0) or 0) for t in aligned_trades])
            },
            "misaligned": {
                "count": len(misaligned_trades),
                "win_rate": (sum(1 for t in misaligned_trades if float(t.get("net_pnl", 0) or 0) > 0) / len(misaligned_trades) * 100) if misaligned_trades else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in misaligned_trades]) if misaligned_trades else 0,
                "total_pnl": sum([float(t.get("net_pnl", 0) or 0) for t in misaligned_trades])
            },
            "by_funding_rate": self._analyze_by_funding_rate(trades),
            "by_oi_delta": self._analyze_by_oi_delta(trades),
            "by_liquidation_bias": {
                bucket: {
                    "trades": data["trades"],
                    "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                    "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
                }
                for bucket, data in by_liq_bias.items() if data["trades"] >= 3
            }
        }
    
    def _analyze_by_volume_regime(self) -> Dict[str, Dict]:
        """Analyze profitability by volume regime and orderbook depth."""
        print("📊 Analyzing by Volume & Orderbook Regime...")
        trades = self._load_all_trade_data()
        
        # Volume analysis
        volumes = []
        for t in trades:
            vol = t.get("ml_volume") or t.get("ml_oi_current") or 0
            if vol and vol > 0:
                volumes.append(float(vol))
        
        volume_analysis = {}
        if volumes:
            median_vol = median(volumes)
            high_vol = [t for t in trades if float(t.get("ml_volume") or t.get("ml_oi_current") or 0) > median_vol]
            low_vol = [t for t in trades if float(t.get("ml_volume") or t.get("ml_oi_current") or 0) <= median_vol]
            
            volume_analysis = {
                "high_volume": {
                    "count": len(high_vol),
                    "win_rate": (sum(1 for t in high_vol if float(t.get("net_pnl", 0) or 0) > 0) / len(high_vol) * 100) if high_vol else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in high_vol]) if high_vol else 0
                },
                "low_volume": {
                    "count": len(low_vol),
                    "win_rate": (sum(1 for t in low_vol if float(t.get("net_pnl", 0) or 0) > 0) / len(low_vol) * 100) if low_vol else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in low_vol]) if low_vol else 0
                }
            }
        
        # Orderbook depth analysis
        depth_ratios = [float(t.get("ml_depth_ratio", 1.0) or 1.0) for t in trades if t.get("ml_depth_ratio")]
        depth_analysis = {}
        if depth_ratios:
            median_depth = median(depth_ratios)
            high_depth = [t for t in trades if float(t.get("ml_depth_ratio", 1.0) or 1.0) > median_depth]
            low_depth = [t for t in trades if float(t.get("ml_depth_ratio", 1.0) or 1.0) <= median_depth]
            
            depth_analysis = {
                "high_depth": {
                    "count": len(high_depth),
                    "win_rate": (sum(1 for t in high_depth if float(t.get("net_pnl", 0) or 0) > 0) / len(high_depth) * 100) if high_depth else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in high_depth]) if high_depth else 0
                },
                "low_depth": {
                    "count": len(low_depth),
                    "win_rate": (sum(1 for t in low_depth if float(t.get("net_pnl", 0) or 0) > 0) / len(low_depth) * 100) if low_depth else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in low_depth]) if low_depth else 0
                }
            }
        
        # Spread analysis
        spreads = [float(t.get("ml_spread_bps", 0) or 0) for t in trades if t.get("ml_spread_bps")]
        spread_analysis = {}
        if spreads:
            median_spread = median(spreads)
            tight_spread = [t for t in trades if float(t.get("ml_spread_bps", 0) or 0) < median_spread]
            wide_spread = [t for t in trades if float(t.get("ml_spread_bps", 0) or 0) >= median_spread]
            
            spread_analysis = {
                "tight_spread": {
                    "count": len(tight_spread),
                    "win_rate": (sum(1 for t in tight_spread if float(t.get("net_pnl", 0) or 0) > 0) / len(tight_spread) * 100) if tight_spread else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in tight_spread]) if tight_spread else 0
                },
                "wide_spread": {
                    "count": len(wide_spread),
                    "win_rate": (sum(1 for t in wide_spread if float(t.get("net_pnl", 0) or 0) > 0) / len(wide_spread) * 100) if wide_spread else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in wide_spread]) if wide_spread else 0
                }
            }
        
        if not volume_analysis and not depth_analysis and not spread_analysis:
            return {"status": "no_volume_or_orderbook_data"}
        
        return {
            "volume_regime": volume_analysis,
            "orderbook_depth": depth_analysis,
            "spread_regime": spread_analysis
        }
    
    def _analyze_by_price_levels(self) -> Dict[str, Dict]:
        """Analyze profitability by volatility and momentum at entry."""
        print("💰 Analyzing by Price Momentum & Volatility...")
        trades = self._load_all_trade_data()
        
        # Analyze by volatility regime
        volatilities = [float(t.get("ml_volatility_1h", 0) or 0) for t in trades if t.get("ml_volatility_1h")]
        volatility_analysis = {}
        if volatilities:
            median_vol = median(volatilities)
            high_vol = [t for t in trades if float(t.get("ml_volatility_1h", 0) or 0) > median_vol]
            low_vol = [t for t in trades if float(t.get("ml_volatility_1h", 0) or 0) <= median_vol]
            
            volatility_analysis = {
                "high_volatility": {
                    "count": len(high_vol),
                    "win_rate": (sum(1 for t in high_vol if float(t.get("net_pnl", 0) or 0) > 0) / len(high_vol) * 100) if high_vol else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in high_vol]) if high_vol else 0
                },
                "low_volatility": {
                    "count": len(low_vol),
                    "win_rate": (sum(1 for t in low_vol if float(t.get("net_pnl", 0) or 0) > 0) / len(low_vol) * 100) if low_vol else 0,
                    "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in low_vol]) if low_vol else 0
                }
            }
        
        # Analyze by momentum at entry (return_5m, return_15m)
        by_momentum = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        for trade in trades:
            return_5m = float(trade.get("ml_return_5m", 0) or 0)
            return_15m = float(trade.get("ml_return_15m", 0) or 0)
            
            if return_5m > 0.5:
                momentum_bucket = "strong_uptrend_5m"
            elif return_5m > 0.1:
                momentum_bucket = "uptrend_5m"
            elif return_5m > -0.1:
                momentum_bucket = "neutral_5m"
            elif return_5m > -0.5:
                momentum_bucket = "downtrend_5m"
            else:
                momentum_bucket = "strong_downtrend_5m"
            
            pnl = float(trade.get("net_pnl", 0) or 0)
            by_momentum[momentum_bucket]["trades"] += 1
            by_momentum[momentum_bucket]["pnl"] += pnl
            if pnl > 0:
                by_momentum[momentum_bucket]["wins"] += 1
        
        momentum_analysis = {
            bucket: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for bucket, data in by_momentum.items() if data["trades"] >= 3
        }
        
        return {
            "by_volatility": volatility_analysis,
            "by_momentum_5m": momentum_analysis
        }
    
    def _analyze_by_regime(self) -> Dict[str, Dict]:
        """Analyze profitability by market regime."""
        print("🌊 Analyzing by Regime...")
        trades = self._load_all_trade_data()
        
        by_regime = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            regime = trade.get("regime", "unknown")
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            
            by_regime[regime]["trades"] += 1
            by_regime[regime]["pnl"] += pnl
            if pnl > 0:
                by_regime[regime]["wins"] += 1
        
        return {
            regime: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "total_pnl": data["pnl"],
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for regime, data in by_regime.items() if data["trades"] >= 3
        }
    
    def _analyze_by_ofi_buckets(self) -> Dict[str, Dict]:
        """Analyze profitability by OFI strength buckets."""
        print("📈 Analyzing by OFI Buckets...")
        trades = self._load_all_trade_data()
        
        buckets = {
            "extreme": [], "very_strong": [], "strong": [], "moderate": [], "weak": []
        }
        
        for trade in trades:
            ofi = abs(float(trade.get("ofi", 0) or 0))
            if ofi > 0.8:
                buckets["extreme"].append(trade)
            elif ofi > 0.7:
                buckets["very_strong"].append(trade)
            elif ofi > 0.5:
                buckets["strong"].append(trade)
            elif ofi > 0.3:
                buckets["moderate"].append(trade)
            else:
                buckets["weak"].append(trade)
        
        return {
            bucket: {
                "count": len(trades_list),
                "win_rate": (sum(1 for t in trades_list if float(t.get("net_pnl", 0) or 0) > 0) / len(trades_list) * 100) if trades_list else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in trades_list]) if trades_list else 0,
                "total_pnl": sum([float(t.get("net_pnl", 0) or 0) for t in trades_list])
            }
            for bucket, trades_list in buckets.items() if len(trades_list) >= 3
        }
    
    def _analyze_by_ensemble_buckets(self) -> Dict[str, Dict]:
        """Analyze profitability by ensemble score buckets."""
        print("🎯 Analyzing by Ensemble Buckets...")
        trades = self._load_all_trade_data()
        
        buckets = {
            "strong_bull": [], "moderate_bull": [], "neutral": [], "moderate_bear": [], "strong_bear": []
        }
        
        for trade in trades:
            ensemble = float(trade.get("ensemble", 0) or 0)
            if ensemble > 0.3:
                buckets["strong_bull"].append(trade)
            elif ensemble > 0.1:
                buckets["moderate_bull"].append(trade)
            elif ensemble > -0.1:
                buckets["neutral"].append(trade)
            elif ensemble > -0.3:
                buckets["moderate_bear"].append(trade)
            else:
                buckets["strong_bear"].append(trade)
        
        return {
            bucket: {
                "count": len(trades_list),
                "win_rate": (sum(1 for t in trades_list if float(t.get("net_pnl", 0) or 0) > 0) / len(trades_list) * 100) if trades_list else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in trades_list]) if trades_list else 0
            }
            for bucket, trades_list in buckets.items() if len(trades_list) >= 3
        }
    
    def _analyze_by_leverage(self) -> Dict[str, Dict]:
        """Analyze profitability by leverage level."""
        print("⚡ Analyzing by Leverage...")
        trades = self._load_all_trade_data()
        
        by_leverage = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            leverage = int(float(trade.get("leverage", 1) or 1))
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            
            by_leverage[leverage]["trades"] += 1
            by_leverage[leverage]["pnl"] += pnl
            if pnl > 0:
                by_leverage[leverage]["wins"] += 1
        
        return {
            f"{lev}x": {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for lev, data in by_leverage.items() if data["trades"] >= 3
        }
    
    def _analyze_by_hold_duration(self) -> Dict[str, Dict]:
        """Analyze profitability by hold duration."""
        print("⏱️ Analyzing by Hold Duration...")
        trades = self._load_all_trade_data()
        
        buckets = {
            "flash": [], "quick": [], "short": [], "medium": [], "extended": [], "long": []
        }
        
        for trade in trades:
            opened_at = trade.get("opened_at")
            closed_at = trade.get("closed_at")
            
            if opened_at and closed_at:
                try:
                    entry_dt = datetime.fromisoformat(str(opened_at).replace('Z', '+00:00'))
                    exit_dt = datetime.fromisoformat(str(closed_at).replace('Z', '+00:00'))
                    duration_seconds = (exit_dt - entry_dt).total_seconds()
                    
                    if duration_seconds < 60:
                        buckets["flash"].append(trade)
                    elif duration_seconds < 300:
                        buckets["quick"].append(trade)
                    elif duration_seconds < 900:
                        buckets["short"].append(trade)
                    elif duration_seconds < 3600:
                        buckets["medium"].append(trade)
                    elif duration_seconds < 14400:
                        buckets["extended"].append(trade)
                    else:
                        buckets["long"].append(trade)
                except:
                    pass
        
        return {
            bucket: {
                "count": len(trades_list),
                "win_rate": (sum(1 for t in trades_list if float(t.get("net_pnl", 0) or 0) > 0) / len(trades_list) * 100) if trades_list else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in trades_list]) if trades_list else 0
            }
            for bucket, trades_list in buckets.items() if len(trades_list) >= 3
        }
    
    def _analyze_cross_correlations(self) -> Dict[str, Any]:
        """Analyze cross-correlations between factors and profitability."""
        print("🔗 Analyzing Cross-Correlations...")
        trades = self._load_all_trade_data()
        
        # Analyze correlations between signals and profitability
        correlations = {}
        
        # OFI vs Profitability
        ofi_values = [abs(float(t.get("ofi", 0) or 0)) for t in trades if t.get("ofi") is not None]
        pnl_values = [float(t.get("net_pnl", 0) or 0) for t in trades if t.get("ofi") is not None]
        if len(ofi_values) >= 10:
            correlations["ofi_vs_pnl"] = self._calculate_correlation(ofi_values, pnl_values)
        
        # Ensemble vs Profitability
        ensemble_values = [float(t.get("ensemble", 0) or 0) for t in trades if t.get("ensemble") is not None]
        pnl_ens = [float(t.get("net_pnl", 0) or 0) for t in trades if t.get("ensemble") is not None]
        if len(ensemble_values) >= 10:
            correlations["ensemble_vs_pnl"] = self._calculate_correlation(ensemble_values, pnl_ens)
        
        # Volume vs Profitability
        volume_values = [float(t.get("ml_volume", 0) or 0) for t in trades if t.get("ml_volume")]
        pnl_vol = [float(t.get("net_pnl", 0) or 0) for t in trades if t.get("ml_volume")]
        if len(volume_values) >= 10:
            correlations["volume_vs_pnl"] = self._calculate_correlation(volume_values, pnl_vol)
        
        return correlations
    
    def _analyze_cross_asset_patterns(self) -> Dict[str, Any]:
        """Analyze cross-asset patterns (BTC/ETH alignment, lead-lag)."""
        print("🌐 Analyzing Cross-Asset Patterns...")
        trades = self._load_all_trade_data()
        
        # BTC/ETH alignment analysis
        btc_aligned = [t for t in trades 
                      if t.get("ml_btc_eth_aligned") == 1 
                      and (t.get("direction") == "LONG" and float(t.get("ml_btc_return_15m", 0) or 0) > 0 or
                           t.get("direction") == "SHORT" and float(t.get("ml_btc_return_15m", 0) or 0) < 0)]
        
        btc_misaligned = [t for t in trades if t.get("ml_btc_eth_aligned") == 0]
        
        return {
            "btc_aligned": {
                "count": len(btc_aligned),
                "win_rate": (sum(1 for t in btc_aligned if float(t.get("net_pnl", 0) or 0) > 0) / len(btc_aligned) * 100) if btc_aligned else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in btc_aligned]) if btc_aligned else 0
            },
            "btc_misaligned": {
                "count": len(btc_misaligned),
                "win_rate": (sum(1 for t in btc_misaligned if float(t.get("net_pnl", 0) or 0) > 0) / len(btc_misaligned) * 100) if btc_misaligned else 0,
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in btc_misaligned]) if btc_misaligned else 0
            },
            "by_btc_trend": self._analyze_by_btc_trend(trades),
            "by_eth_trend": self._analyze_by_eth_trend(trades)
        }
    
    def _analyze_by_btc_trend(self, trades: List[Dict]) -> Dict[str, Dict]:
        """Analyze profitability based on BTC trend at entry."""
        by_trend = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            btc_trend = trade.get("ml_btc_trend")
            btc_return = float(trade.get("ml_btc_return_15m", 0) or 0)
            
            if btc_trend == 1 or btc_return > 0.2:
                trend_bucket = "btc_strong_up"
            elif btc_trend == 1 or btc_return > 0:
                trend_bucket = "btc_up"
            elif btc_trend == -1 or btc_return < -0.2:
                trend_bucket = "btc_strong_down"
            elif btc_trend == -1 or btc_return < 0:
                trend_bucket = "btc_down"
            else:
                trend_bucket = "btc_neutral"
            
            pnl = float(trade.get("net_pnl", 0) or 0)
            by_trend[trend_bucket]["trades"] += 1
            by_trend[trend_bucket]["pnl"] += pnl
            if pnl > 0:
                by_trend[trend_bucket]["wins"] += 1
        
        return {
            bucket: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for bucket, data in by_trend.items() if data["trades"] >= 3
        }
    
    def _analyze_by_eth_trend(self, trades: List[Dict]) -> Dict[str, Dict]:
        """Analyze profitability based on ETH trend at entry."""
        by_trend = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            eth_trend = trade.get("ml_eth_trend")
            eth_return = float(trade.get("ml_eth_return_15m", 0) or 0)
            
            if eth_trend == 1 or eth_return > 0.2:
                trend_bucket = "eth_strong_up"
            elif eth_trend == 1 or eth_return > 0:
                trend_bucket = "eth_up"
            elif eth_trend == -1 or eth_return < -0.2:
                trend_bucket = "eth_strong_down"
            elif eth_trend == -1 or eth_return < 0:
                trend_bucket = "eth_down"
            else:
                trend_bucket = "eth_neutral"
            
            pnl = float(trade.get("net_pnl", 0) or 0)
            by_trend[trend_bucket]["trades"] += 1
            by_trend[trend_bucket]["pnl"] += pnl
            if pnl > 0:
                by_trend[trend_bucket]["wins"] += 1
        
        return {
            bucket: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for bucket, data in by_trend.items() if data["trades"] >= 3
        }
    
    def _analyze_signal_interactions(self) -> Dict[str, Any]:
        """Analyze how signals interact (e.g., OFI + CoinGlass, MTF + Volume)."""
        print("🔀 Analyzing Signal Interactions...")
        trades = self._load_all_trade_data()
        
        interactions = {}
        
        # OFI + CoinGlass alignment
        ofi_high_cg_aligned = [t for t in trades 
                               if abs(float(t.get("ofi", 0) or 0)) > 0.5 
                               and t.get("coinglass_taker_ratio") 
                               and ((t.get("direction") == "LONG" and t.get("coinglass_taker_ratio") > 0.5) or
                                    (t.get("direction") == "SHORT" and t.get("coinglass_taker_ratio") < 0.5))]
        
        if len(ofi_high_cg_aligned) >= 3:
            interactions["ofi_high_coinglass_aligned"] = {
                "count": len(ofi_high_cg_aligned),
                "win_rate": (sum(1 for t in ofi_high_cg_aligned if float(t.get("net_pnl", 0) or 0) > 0) / len(ofi_high_cg_aligned) * 100),
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in ofi_high_cg_aligned])
            }
        
        # MTF + OFI
        mtf_strong_ofi_high = [t for t in trades
                               if float(t.get("mtf", 0) or 0) > 0.7
                               and abs(float(t.get("ofi", 0) or 0)) > 0.5]
        
        if len(mtf_strong_ofi_high) >= 3:
            interactions["mtf_strong_ofi_high"] = {
                "count": len(mtf_strong_ofi_high),
                "win_rate": (sum(1 for t in mtf_strong_ofi_high if float(t.get("net_pnl", 0) or 0) > 0) / len(mtf_strong_ofi_high) * 100),
                "avg_pnl": mean([float(t.get("net_pnl", 0) or 0) for t in mtf_strong_ofi_high])
            }
        
        return interactions
    
    def _identify_profitability_patterns(self) -> List[Dict]:
        """Identify the most profitable patterns across all dimensions."""
        print("💎 Identifying Profitability Patterns...")
        trades = self._load_all_trade_data()
        
        patterns = []
        
        # Find symbol+strategy+signal combinations with >70% win rate
        combo_perf = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        
        for trade in trades:
            symbol = trade.get("symbol")
            # Normalize symbol to ensure consistency
            if symbol:
                symbol = self._normalize_symbol_for_matching(symbol)
            strategy = trade.get("strategy")
            ofi_level = "high" if abs(float(trade.get("ofi", 0) or 0)) > 0.5 else "low"
            hour = trade.get("entry_hour")
            
            combo_key = f"{symbol}|{strategy}|OFI_{ofi_level}|H{hour:02d}"
            pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
            
            combo_perf[combo_key]["trades"] += 1
            combo_perf[combo_key]["pnl"] += pnl
            if pnl > 0:
                combo_perf[combo_key]["wins"] += 1
        
        for combo, data in combo_perf.items():
            if data["trades"] >= 5:
                win_rate = (data["wins"] / data["trades"]) * 100
                avg_pnl = data["pnl"] / data["trades"]
                
                if win_rate >= 70 or avg_pnl > 20:
                    # Extract symbol from combo and normalize it
                    pattern_parts = combo.split("|")
                    if len(pattern_parts) > 0:
                        pattern_symbol = self._normalize_symbol_for_matching(pattern_parts[0])
                        # Reconstruct combo with normalized symbol
                        pattern_parts[0] = pattern_symbol
                        normalized_combo = "|".join(pattern_parts)
                    else:
                        normalized_combo = combo
                    
                    patterns.append({
                        "pattern": normalized_combo,
                        "trades": data["trades"],
                        "win_rate": round(win_rate, 1),
                        "avg_pnl": round(avg_pnl, 2),
                        "total_pnl": round(data["pnl"], 2)
                    })
        
        return sorted(patterns, key=lambda x: x["avg_pnl"], reverse=True)[:20]
    
    def _analyze_by_funding_rate(self, trades: List[Dict]) -> Dict[str, Dict]:
        """Analyze profitability by CoinGlass funding rate."""
        by_funding = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            funding = trade.get("coinglass_funding")
            if funding is not None:
                funding_pct = float(funding) * 100
                if funding_pct > 0.01:
                    bucket = "high_positive"
                elif funding_pct > 0:
                    bucket = "low_positive"
                elif funding_pct > -0.01:
                    bucket = "low_negative"
                else:
                    bucket = "high_negative"
                
                pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
                by_funding[bucket]["trades"] += 1
                by_funding[bucket]["pnl"] += pnl
                if pnl > 0:
                    by_funding[bucket]["wins"] += 1
        
        return {
            bucket: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for bucket, data in by_funding.items() if data["trades"] >= 3
        }
    
    def _analyze_by_oi_delta(self, trades: List[Dict]) -> Dict[str, Dict]:
        """Analyze profitability by CoinGlass OI delta."""
        by_oi = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        
        for trade in trades:
            oi_delta = trade.get("coinglass_oi_delta")
            if oi_delta is not None:
                delta_pct = float(oi_delta)
                if delta_pct > 5:
                    bucket = "very_positive"
                elif delta_pct > 1:
                    bucket = "positive"
                elif delta_pct > -1:
                    bucket = "neutral"
                elif delta_pct > -5:
                    bucket = "negative"
                else:
                    bucket = "very_negative"
                
                pnl = float(trade.get("net_pnl", trade.get("pnl", 0)) or 0)
                by_oi[bucket]["trades"] += 1
                by_oi[bucket]["pnl"] += pnl
                if pnl > 0:
                    by_oi[bucket]["wins"] += 1
        
        return {
            bucket: {
                "trades": data["trades"],
                "win_rate": (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0,
                "avg_pnl": data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            }
            for bucket, data in by_oi.items() if data["trades"] >= 3
        }
    
    def _calculate_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(xi * xi for xi in x)
        sum_y2 = sum(yi * yi for yi in y)
        
        numerator = n * sum_xy - sum_x * sum_y
        denominator = math.sqrt((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y))
        
        if denominator == 0:
            return 0.0
        
        return numerator / denominator
    
    def _generate_actionable_insights(self, analysis: Dict) -> List[str]:
        """Generate actionable insights from all dimensions."""
        insights = []
        
        # Symbol insights
        if analysis.get("by_symbol"):
            best_symbol = max(analysis["by_symbol"].items(), 
                            key=lambda x: x[1].get("expectancy", 0), 
                            default=None)
            worst_symbol = min(analysis["by_symbol"].items(),
                             key=lambda x: x[1].get("expectancy", 0),
                             default=None)
            
            if best_symbol and best_symbol[1].get("expectancy", 0) > 10:
                insights.append(f"💰 {best_symbol[0]} is highly profitable (${best_symbol[1]['expectancy']:.2f}/trade) - consider increasing allocation")
            
            if worst_symbol and worst_symbol[1].get("expectancy", 0) < -5:
                insights.append(f"⚠️ {worst_symbol[0]} is losing money (${worst_symbol[1]['expectancy']:.2f}/trade) - reduce or eliminate")
        
        # Time-of-day insights
        if analysis.get("by_time_of_day") and analysis["by_time_of_day"].get("best_hours"):
            best_hours = analysis["by_time_of_day"]["best_hours"][:3]
            if best_hours:
                hours_str = ", ".join([h[0] for h in best_hours])
                insights.append(f"⏰ Best trading hours: {hours_str} - consider focusing activity during these times")
        
        # Signal combination insights
        if analysis.get("signal_interactions"):
            best_combo = max(analysis["signal_interactions"].items(),
                           key=lambda x: x[1].get("avg_pnl", 0),
                           default=None)
            if best_combo and best_combo[1].get("avg_pnl", 0) > 15:
                insights.append(f"🔗 Best signal combo: {best_combo[0]} (${best_combo[1]['avg_pnl']:.2f}/trade, {best_combo[1]['win_rate']:.1f}% WR)")
        
        # CoinGlass alignment insights
        if analysis.get("by_coinglass_alignment"):
            cg = analysis["by_coinglass_alignment"]
            if cg.get("aligned", {}).get("win_rate", 0) > cg.get("misaligned", {}).get("win_rate", 0) + 10:
                insights.append(f"📊 CoinGlass alignment matters: {cg['aligned']['win_rate']:.1f}% WR aligned vs {cg['misaligned']['win_rate']:.1f}% misaligned")
        
        return insights
    
    def _generate_optimization_recommendations(self, analysis: Dict) -> List[Dict]:
        """Generate optimization recommendations from all dimensions."""
        recommendations = []
        
        # Symbol-specific recommendations
        if analysis.get("by_symbol"):
            for symbol, data in analysis["by_symbol"].items():
                if data.get("expectancy", 0) > 15:
                    recommendations.append({
                        "priority": "HIGH",
                        "category": "symbol_allocation",
                        "symbol": symbol,
                        "recommendation": f"Increase {symbol} allocation - expectancy ${data['expectancy']:.2f}/trade",
                        "expected_impact": f"+${data['expectancy'] * 10:.2f}/day if we double allocation"
                    })
                elif data.get("expectancy", 0) < -10:
                    recommendations.append({
                        "priority": "HIGH",
                        "category": "symbol_allocation",
                        "symbol": symbol,
                        "recommendation": f"Reduce or eliminate {symbol} - losing ${abs(data['expectancy']):.2f}/trade",
                        "expected_impact": f"Save ${abs(data['expectancy']) * data['total_trades']:.2f} if we stop trading it"
                    })
        
        # Time-based recommendations
        if analysis.get("by_time_of_day") and analysis["by_time_of_day"].get("best_hours"):
            best_hour = analysis["by_time_of_day"]["best_hours"][0]
            if best_hour and best_hour[1] > 20:
                recommendations.append({
                    "priority": "MEDIUM",
                    "category": "timing",
                    "recommendation": f"Focus trading activity around {best_hour[0]} UTC - avg ${best_hour[1]:.2f}/trade",
                    "expected_impact": "Increase profitability by timing entries better"
                })
        
        # Signal combination recommendations
        if analysis.get("signal_interactions"):
            for combo, data in analysis["signal_interactions"].items():
                if data.get("avg_pnl", 0) > 20 and data.get("count", 0) >= 5:
                    recommendations.append({
                        "priority": "HIGH",
                        "category": "signal_filters",
                        "recommendation": f"Prioritize {combo} combinations - ${data['avg_pnl']:.2f}/trade, {data['win_rate']:.1f}% WR",
                        "expected_impact": "Increase win rate and average profit per trade"
                    })
        
        return recommendations


    def _update_health_status(self, analysis: Dict[str, Any]):
        """Update health status file for monitoring."""
        try:
            status = {
                "last_run": analysis.get("timestamp"),
                "status": analysis.get("status"),
                "components_completed": len(analysis.get("components_completed", [])),
                "components_failed": len(analysis.get("components_failed", [])),
                "error_count": len(analysis.get("errors", [])),
                "execution_time_seconds": analysis.get("execution_time_seconds", 0),
                "lookback_days": self.lookback_days
            }
            
            ANALYZER_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ANALYZER_STATUS_FILE, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to update health status: {e}", exc_info=True)
    
    def _log_health_event(self, analysis: Dict[str, Any]):
        """Log health event to health log."""
        try:
            event = {
                "timestamp": analysis.get("timestamp"),
                "status": analysis.get("status"),
                "components_completed": len(analysis.get("components_completed", [])),
                "components_failed": len(analysis.get("components_failed", [])),
                "error_count": len(analysis.get("errors", [])),
                "execution_time_seconds": analysis.get("execution_time_seconds", 0),
                "errors": analysis.get("errors", [])[:5]  # Log first 5 errors
            }
            
            ANALYZER_HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(ANALYZER_HEALTH_LOG, 'a') as f:
                f.write(json.dumps(event) + '\n')
            
            # Keep only last 1000 events (prevent log bloat)
            try:
                with open(ANALYZER_HEALTH_LOG, 'r') as f:
                    lines = f.readlines()
                if len(lines) > 1000:
                    with open(ANALYZER_HEALTH_LOG, 'w') as f:
                        f.writelines(lines[-1000:])
            except:
                pass
        except Exception as e:
            logger.error(f"Failed to log health event: {e}", exc_info=True)
    
    @staticmethod
    def get_health_status() -> Dict[str, Any]:
        """Get current health status of the analyzer."""
        try:
            if ANALYZER_STATUS_FILE.exists():
                with open(ANALYZER_STATUS_FILE, 'r') as f:
                    status = json.load(f)
                    
                # Check if status is stale (> 48 hours old)
                if status.get("last_run"):
                    try:
                        last_run = datetime.fromisoformat(status["last_run"].replace('Z', '+00:00'))
                        age_hours = (datetime.utcnow().replace(tzinfo=last_run.tzinfo) - last_run).total_seconds() / 3600
                        status["age_hours"] = round(age_hours, 1)
                        status["is_stale"] = age_hours > 48
                    except:
                        status["is_stale"] = True
                else:
                    status["is_stale"] = True
                
                return {
                    "status": "healthy" if status.get("status") == "success" else "degraded" if status.get("status") == "partial_success" else "unhealthy",
                    "details": status
                }
            else:
                return {
                    "status": "unknown",
                    "details": {"error": "Status file not found"}
                }
        except Exception as e:
            logger.error(f"Failed to get health status: {e}", exc_info=True)
            return {
                "status": "error",
                "details": {"error": str(e)}
            }
    
    @staticmethod
    def check_health() -> Dict[str, Any]:
        """
        Health check for monitoring systems.
        
        Returns health status compatible with healing operator.
        """
        health = ExpansiveMultiDimensionalProfitabilityAnalyzer.get_health_status()
        
        # Convert to healing operator format
        if health["status"] == "healthy":
            return {
                "status": "green",
                "message": "Expansive analyzer is healthy",
                "last_run": health["details"].get("last_run"),
                "components_completed": health["details"].get("components_completed", 0),
                "execution_time": health["details"].get("execution_time_seconds", 0)
            }
        elif health["status"] == "degraded":
            return {
                "status": "yellow",
                "message": f"Expansive analyzer has {health['details'].get('components_failed', 0)} failed components",
                "last_run": health["details"].get("last_run"),
                "components_completed": health["details"].get("components_completed", 0),
                "components_failed": health["details"].get("components_failed", 0),
                "errors": health["details"].get("error_count", 0)
            }
        elif health.get("details", {}).get("is_stale"):
            return {
                "status": "yellow",
                "message": f"Expansive analyzer status is stale ({health['details'].get('age_hours', 0):.1f}h old)",
                "last_run": health["details"].get("last_run"),
                "age_hours": health["details"].get("age_hours", 0)
            }
        else:
            return {
                "status": "red",
                "message": "Expansive analyzer is unhealthy or status unknown",
                "details": health["details"]
            }


def run_expansive_analysis() -> Dict[str, Any]:
    """
    Main entry point for expansive multi-dimensional analysis.
    
    Features:
    - Comprehensive error handling
    - Graceful degradation
    - Health tracking
    """
    try:
        analyzer = ExpansiveMultiDimensionalProfitabilityAnalyzer()
        return analyzer.run_comprehensive_analysis()
    except Exception as e:
        logger.error(f"Critical error in run_expansive_analysis: {e}", exc_info=True)
        # Return minimal error response
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "status": "failed",
            "error": str(e),
            "errors": [f"Critical failure: {str(e)}"],
            "components_completed": [],
            "components_failed": []
        }


if __name__ == "__main__":
    analysis = run_expansive_analysis()
    
    print("\n" + "=" * 80)
    print("KEY INSIGHTS")
    print("=" * 80)
    for insight in analysis.get("actionable_insights", []):
        print(f"💡 {insight}")
    
    print("\n" + "=" * 80)
    print("TOP PROFITABILITY PATTERNS")
    print("=" * 80)
    for pattern in analysis.get("profitability_patterns", [])[:10]:
        print(f"   {pattern['pattern']}: {pattern['win_rate']:.1f}% WR, ${pattern['avg_pnl']:.2f}/trade ({pattern['trades']} trades)")
    
    # Save full analysis
    output_path = PathRegistry.get_path("reports", "expansive_profitability_analysis.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"\n✅ Full analysis saved to: {output_path}")
