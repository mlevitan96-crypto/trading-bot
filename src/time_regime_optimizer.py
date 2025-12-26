#!/usr/bin/env python3
"""
Time-Regime Optimizer - FINAL ALPHA
====================================
Uses 24/7 shadow trading data to auto-tune the "Golden Hour" window.

Analyzes shadow_trade_outcomes.jsonl for trades outside 09:00-16:00 UTC.
If any 2-hour window shows Profit Factor > 1.5 over 14 days, automatically
unblocks that window, making "Golden Hour" a dynamic, learned state.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta, timezone
from collections import defaultdict

try:
    import numpy as np
except ImportError:
    # Fallback if numpy not available
    np = None

from src.infrastructure.path_registry import PathRegistry


class TimeRegimeOptimizer:
    """
    Analyzes shadow trades to dynamically optimize trading windows.
    """
    
    def __init__(self):
        self.shadow_log_path = Path(PathRegistry.get_path("logs", "shadow_trade_outcomes.jsonl"))
        self.golden_hour_config_path = Path(PathRegistry.get_path("feature_store", "golden_hour_config.json"))
        self.golden_hour_config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Default golden hour: 09:00-16:00 UTC (7 hours)
        self.base_golden_hour_start = 9
        self.base_golden_hour_end = 16
        
        # Minimum requirements for unblocking a window
        self.min_profit_factor = 1.5
        self.min_lookback_days = 14
        self.min_trades_per_window = 5
    
    def analyze_shadow_trades_by_time_window(self, days: int = 14) -> Dict[str, Dict[str, Any]]:
        """
        Analyze shadow trades grouped by 2-hour time windows.
        
        Args:
            days: Lookback period in days
            
        Returns:
            Dict mapping window (e.g., "01:00-03:00") to metrics
        """
        if not self.shadow_log_path.exists():
            print(f"⚠️ [TIME-REGIME] Shadow trade outcomes log not found: {self.shadow_log_path}")
            return {}
        
        cutoff_ts = time.time() - (days * 24 * 3600)
        window_trades = defaultdict(list)
        
        # Read shadow trade outcomes
        try:
            with open(self.shadow_log_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        entry_ts = entry.get("ts") or entry.get("timestamp")
                        
                        if isinstance(entry_ts, str):
                            # Parse ISO timestamp
                            ts_clean = entry_ts.replace('Z', '+00:00')
                            dt = datetime.fromisoformat(ts_clean)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            entry_ts = dt.timestamp()
                        
                        if entry_ts and entry_ts >= cutoff_ts:
                            # Get entry hour (UTC)
                            entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
                            entry_hour = entry_dt.hour
                            
                            # Only analyze trades outside base golden hour (09:00-16:00)
                            if not (self.base_golden_hour_start <= entry_hour < self.base_golden_hour_end):
                                # Group into 2-hour windows
                                window_start = (entry_hour // 2) * 2
                                window_end = window_start + 2
                                window_key = f"{window_start:02d}:00-{window_end:02d}:00"
                                
                                # Extract P&L (hypothetical P&L from shadow trade)
                                pnl = entry.get("hypothetical_pnl", entry.get("pnl", entry.get("pnl_usd", 0))) or 0
                                
                                window_trades[window_key].append({
                                    "timestamp": entry_ts,
                                    "pnl": float(pnl) if pnl else 0.0,
                                    "symbol": entry.get("symbol", ""),
                                    "direction": entry.get("direction", "")
                                })
                    except Exception as e:
                        continue
        except Exception as e:
            print(f"⚠️ [TIME-REGIME] Error reading shadow trade outcomes: {e}")
            return {}
        
        # Calculate metrics for each window
        window_metrics = {}
        for window_key, trades in window_trades.items():
            if len(trades) < self.min_trades_per_window:
                continue
            
            pnls = [t["pnl"] for t in trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p < 0]
            
            gross_profit = sum(wins) if wins else 0.0
            gross_loss = abs(sum(losses)) if losses else 0.0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
            win_rate = len(wins) / len(trades) if trades else 0.0
            total_pnl = sum(pnls)
            avg_pnl = total_pnl / len(trades) if trades else 0.0
            
            # [FINAL ALPHA PHASE 7] Calculate Sharpe Ratio for risk-adjusted performance
            sharpe_ratio = 0.0
            if len(trades) >= 10 and np is not None:  # Need at least 10 trades for meaningful Sharpe calculation
                try:
                    # Extract returns from P&L (normalize by starting capital)
                    returns = [t["pnl"] / 10000.0 for t in trades]  # Normalize by $10k starting capital
                    
                    if len(returns) > 1:
                        mean_return = np.mean(returns)
                        std_return = np.std(returns)
                        
                        # Sharpe Ratio = (mean return - risk_free_rate) / std_return
                        # Risk-free rate = 0 (crypto trading)
                        if std_return > 1e-9:
                            sharpe_ratio = mean_return / std_return
                        else:
                            sharpe_ratio = 0.0
                except Exception as e:
                    print(f"⚠️ [TIME-REGIME] Error calculating Sharpe for {window_key}: {e}")
                    sharpe_ratio = 0.0
            elif len(trades) >= 10 and np is None:
                # Fallback calculation without numpy
                try:
                    returns = [t["pnl"] / 10000.0 for t in trades]
                    if len(returns) > 1:
                        mean_return = sum(returns) / len(returns)
                        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
                        std_return = variance ** 0.5
                        sharpe_ratio = mean_return / std_return if std_return > 1e-9 else 0.0
                except Exception as e:
                    print(f"⚠️ [TIME-REGIME] Error calculating Sharpe (fallback) for {window_key}: {e}")
                    sharpe_ratio = 0.0
            
            # [FINAL ALPHA PHASE 7] Require Sharpe Ratio > 1.5 AND Profit Factor > 1.5 for qualification
            min_sharpe_ratio = 1.5
            qualifies_pf = profit_factor >= self.min_profit_factor
            qualifies_sharpe = sharpe_ratio >= min_sharpe_ratio
            qualifies = qualifies_pf and qualifies_sharpe
            
            window_metrics[window_key] = {
                "window": window_key,
                "trades": len(trades),
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "sharpe_ratio": sharpe_ratio,
                "total_pnl": total_pnl,
                "avg_pnl": avg_pnl,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "qualifies": qualifies,
                "qualifies_pf": qualifies_pf,
                "qualifies_sharpe": qualifies_sharpe
            }
        
        return window_metrics
    
    def optimize_golden_hours(self) -> Dict[str, Any]:
        """
        Analyze shadow trades and update golden hour configuration.
        
        Returns:
            Dict with optimization results and actions taken
        """
        print(f"🔄 [TIME-REGIME] Starting golden hour optimization...")
        
        # Analyze shadow trades
        window_metrics = self.analyze_shadow_trades_by_time_window(days=self.min_lookback_days)
        
        if not window_metrics:
            return {
                "success": False,
                "reason": "No shadow trade data available",
                "qualified_windows": []
            }
        
        # [FINAL ALPHA PHASE 7] Find windows that qualify (PF > 1.5 AND Sharpe > 1.5)
        qualified_windows = [
            window_key for window_key, metrics in window_metrics.items()
            if metrics.get("qualifies", False)
        ]
        
        # Log qualification details
        for window_key, metrics in window_metrics.items():
            pf = metrics.get("profit_factor", 0.0)
            sharpe = metrics.get("sharpe_ratio", 0.0)
            qualifies = metrics.get("qualifies", False)
            status = "✅ QUALIFIED" if qualifies else "❌ REJECTED"
            print(f"   {status} {window_key}: PF={pf:.2f}, Sharpe={sharpe:.2f} (requires PF>={self.min_profit_factor}, Sharpe>=1.5)")
        
        # Load current golden hour config
        current_config = self._load_golden_hour_config()
        
        # Get currently allowed windows
        allowed_windows = current_config.get("allowed_windows", [])
        
        # Add qualified windows to allowed list
        new_windows = [w for w in qualified_windows if w not in allowed_windows]
        
        if new_windows:
            # Update config with new windows
            allowed_windows.extend(new_windows)
            current_config["allowed_windows"] = sorted(set(allowed_windows))
            current_config["last_optimization"] = datetime.utcnow().isoformat() + "Z"
            current_config["optimization_history"] = current_config.get("optimization_history", [])
            current_config["optimization_history"].append({
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "new_windows": new_windows,
                "total_allowed": len(allowed_windows)
            })
            
            # Keep only last 10 optimization records
            if len(current_config["optimization_history"]) > 10:
                current_config["optimization_history"] = current_config["optimization_history"][-10:]
            
            # Save updated config
            self._save_golden_hour_config(current_config)
            
            print(f"✅ [TIME-REGIME] Added {len(new_windows)} new trading windows: {new_windows}")
            print(f"   Total allowed windows: {len(allowed_windows)}")
            
            return {
                "success": True,
                "new_windows": new_windows,
                "qualified_windows": qualified_windows,
                "all_allowed_windows": allowed_windows,
                "window_metrics": window_metrics
            }
        else:
            print(f"ℹ️  [TIME-REGIME] No new windows qualified (PF > {self.min_profit_factor})")
            return {
                "success": True,
                "new_windows": [],
                "qualified_windows": qualified_windows,
                "all_allowed_windows": allowed_windows,
                "window_metrics": window_metrics
            }
    
    def _load_golden_hour_config(self) -> Dict[str, Any]:
        """Load golden hour configuration"""
        default_config = {
            "restrict_to_golden_hour": True,
            "allowed_windows": [],  # Will be populated by optimizer
            "base_window": f"{self.base_golden_hour_start:02d}:00-{self.base_golden_hour_end:02d}:00",
            "last_optimization": None,
            "optimization_history": []
        }
        
        try:
            if self.golden_hour_config_path.exists():
                with open(self.golden_hour_config_path, 'r') as f:
                    config = json.load(f)
                    # Ensure all required keys exist
                    if "allowed_windows" not in config:
                        config["allowed_windows"] = []
                    if "base_window" not in config:
                        config["base_window"] = default_config["base_window"]
                    if "optimization_history" not in config:
                        config["optimization_history"] = []
                    return config
        except Exception as e:
            print(f"⚠️ [TIME-REGIME] Error loading config: {e}")
        
        # Default config
        return default_config
    
    def _save_golden_hour_config(self, config: Dict[str, Any]):
        """Save golden hour configuration"""
        try:
            # Preserve existing fields we don't want to overwrite
            if self.golden_hour_config_path.exists():
                with open(self.golden_hour_config_path, 'r') as f:
                    existing = json.load(f)
                    # Merge with existing (preserve restrict_to_golden_hour if set)
                    config["restrict_to_golden_hour"] = existing.get("restrict_to_golden_hour", config.get("restrict_to_golden_hour", True))
            
            with open(self.golden_hour_config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"⚠️ [TIME-REGIME] Error saving config: {e}")
    
    def get_allowed_windows(self) -> List[str]:
        """Get list of all allowed trading windows"""
        config = self._load_golden_hour_config()
        base_window = config.get("base_window", f"{self.base_golden_hour_start:02d}:00-{self.base_golden_hour_end:02d}:00")
        allowed = config.get("allowed_windows", [])
        
        # Always include base window
        all_windows = [base_window]
        all_windows.extend(allowed)
        return sorted(set(all_windows))


# Singleton instance
_time_regime_optimizer_instance = None


def get_time_regime_optimizer() -> TimeRegimeOptimizer:
    """Get singleton instance"""
    global _time_regime_optimizer_instance
    if _time_regime_optimizer_instance is None:
        _time_regime_optimizer_instance = TimeRegimeOptimizer()
    return _time_regime_optimizer_instance

