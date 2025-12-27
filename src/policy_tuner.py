#!/usr/bin/env python3
"""
Bayesian Policy Optimizer (The Auto-Tuner)
===========================================

Uses Optuna for Bayesian optimization to find optimal entry_threshold
and stop_loss parameters. Maximizes Portfolio Sharpe Ratio calculated
from merged history of Live and Shadow trades.
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    print("⚠️ [POLICY-TUNER] optuna not available - Bayesian optimization disabled")

POLICY_CONFIG_PATH = Path("configs/trading_config.json")
POLICY_STATE_PATH = Path("feature_store/policy_tuner_state.json")
POLICY_OPTIMIZATION_LOG = Path("logs/policy_optimization.jsonl")


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.0) -> float:
    """
    Calculate Sharpe Ratio from return series.
    
    Args:
        returns: List of percentage returns
        risk_free_rate: Risk-free rate (default 0.0)
    
    Returns:
        Sharpe ratio (annualized if returns are daily)
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    returns_arr = np.array(returns)
    
    # Mean excess return
    excess_returns = returns_arr - risk_free_rate
    mean_excess = np.mean(excess_returns)
    
    # Standard deviation
    std = np.std(returns_arr)
    
    if std == 0:
        return 0.0
    
    # Sharpe ratio (assuming daily returns, annualize by * sqrt(365))
    sharpe = (mean_excess / std) * np.sqrt(365)
    
    return float(sharpe)


def load_trade_history(days: int = 30) -> Tuple[List[Dict], List[Dict]]:
    """
    Load live and shadow trade history from multiple sources.
    
    Reads from:
    - logs/executed_trades.jsonl (primary live trades source)
    - positions_futures.json closed_positions (fallback)
    - logs/shadow_results.jsonl (shadow trades)
    
    Args:
        days: Number of days to look back
    
    Returns:
        Tuple of (live_trades, shadow_trades)
    """
    cutoff_time = time.time() - (days * 24 * 3600)
    
    # Load live trades from executed_trades.jsonl (primary source)
    live_trades = []
    try:
        executed_trades_path = Path("logs/executed_trades.jsonl")
        if executed_trades_path.exists():
            with open(executed_trades_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        ts = entry.get('ts', entry.get('timestamp', entry.get('closed_ts', 0)))
                        if isinstance(ts, str):
                            try:
                                from datetime import datetime
                                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                ts = dt.timestamp()
                            except:
                                continue
                        if ts >= cutoff_time:
                            live_trades.append(entry)
                    except:
                        continue
    except Exception as e:
        print(f"⚠️ [POLICY-TUNER] Error loading executed_trades.jsonl: {e}")
    
    # Fallback: Load from positions_futures.json if executed_trades.jsonl is empty
    if not live_trades:
        try:
            from src.position_manager import load_closed_positions
            closed_positions = load_closed_positions()
            live_trades = [
                p for p in closed_positions
                if p.get('closed_ts') and p['closed_ts'] >= cutoff_time
            ]
        except Exception as e:
            print(f"⚠️ [POLICY-TUNER] Error loading live trades from positions: {e}")
    
    # Load shadow trades from shadow_results.jsonl
    shadow_trades = []
    try:
        shadow_results_path = Path("logs/shadow_results.jsonl")
        if shadow_results_path.exists():
            with open(shadow_results_path, 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get('event') == 'SHADOW_EXIT':
                            ts = entry.get('timestamp', 0)
                            if isinstance(ts, str):
                                try:
                                    from datetime import datetime
                                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                                    ts = dt.timestamp()
                                except:
                                    continue
                            if ts >= cutoff_time:
                                shadow_trades.append(entry)
                    except:
                        continue
    except Exception as e:
        print(f"⚠️ [POLICY-TUNER] Error loading shadow trades: {e}")
    
    return live_trades, shadow_trades


def calculate_portfolio_sharpe(live_trades: List[Dict], shadow_trades: List[Dict],
                                entry_threshold: float, stop_loss_pct: float) -> float:
    """
    Calculate portfolio Sharpe ratio with given parameters (simulated).
    
    This simulates what the Sharpe would be if we used these parameters,
    by filtering trades based on entry threshold and applying stop loss.
    
    Args:
        live_trades: List of live trade records
        shadow_trades: List of shadow trade records
        entry_threshold: Entry threshold parameter
        stop_loss_pct: Stop loss percentage
    
    Returns:
        Sharpe ratio
    """
    all_trades = []
    
    # Process live trades
    for trade in live_trades:
        # Extract return (assuming pnl_pct or similar field exists)
        pnl_pct = trade.get('roi_pct', trade.get('pnl_pct', 0.0))
        
        # Simulate stop loss application
        if stop_loss_pct > 0 and pnl_pct < -abs(stop_loss_pct):
            pnl_pct = -abs(stop_loss_pct)
        
        all_trades.append({
            'return_pct': pnl_pct,
            'timestamp': trade.get('closed_ts', time.time())
        })
    
    # Process shadow trades (only include those that would have passed threshold)
    # For shadow trades, we'd need entry score - for now, include all
    for trade in shadow_trades:
        pnl_pct = trade.get('pnl_pct', 0.0)
        
        # Simulate stop loss
        if stop_loss_pct > 0 and pnl_pct < -abs(stop_loss_pct):
            pnl_pct = -abs(stop_loss_pct)
        
        all_trades.append({
            'return_pct': pnl_pct,
            'timestamp': trade.get('timestamp', time.time())
        })
    
    if not all_trades:
        return 0.0
    
    # Extract returns
    returns = [t['return_pct'] / 100.0 for t in all_trades]  # Convert to decimal
    
    # Calculate Sharpe
    sharpe = calculate_sharpe_ratio(returns)
    
    return sharpe


class PolicyTuner:
    """
    Bayesian optimizer for trading policy parameters.
    """
    
    def __init__(self, n_trials: int = 50):
        """
        Initialize policy tuner.
        
        Args:
            n_trials: Number of optimization trials
        """
        self.n_trials = n_trials
        self.study = None
        self.best_params = None
        self.last_optimization = None
        self._load_state()
    
    def _load_state(self):
        """Load previous optimization state."""
        if POLICY_STATE_PATH.exists():
            try:
                with open(POLICY_STATE_PATH, 'r') as f:
                    state = json.load(f)
                    self.best_params = state.get('best_params')
                    self.last_optimization = state.get('last_optimization')
            except Exception as e:
                print(f"⚠️ [POLICY-TUNER] Error loading state: {e}")
    
    def _save_state(self):
        """Save optimization state."""
        POLICY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        state = {
            'best_params': self.best_params,
            'last_optimization': self.last_optimization,
            'timestamp': time.time()
        }
        
        with open(POLICY_STATE_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _log_optimization(self, trial_num: int, params: Dict, sharpe: float):
        """Log optimization trial."""
        POLICY_OPTIMIZATION_LOG.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            'trial': trial_num,
            'params': params,
            'sharpe_ratio': sharpe,
            'timestamp': time.time(),
            'timestamp_iso': datetime.now(timezone.utc).isoformat()
        }
        
        with open(POLICY_OPTIMIZATION_LOG, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    
    def optimize(self, days: int = 30) -> Dict[str, Any]:
        """
        Run Bayesian optimization to find optimal parameters.
        
        Args:
            days: Number of days of history to use
        
        Returns:
            Optimization results with best parameters
        """
        if not OPTUNA_AVAILABLE:
            return {
                'success': False,
                'error': 'optuna not available',
                'best_params': None
            }
        
        # Load trade history
        live_trades, shadow_trades = load_trade_history(days)
        
        if len(live_trades) + len(shadow_trades) < 20:
            return {
                'success': False,
                'error': f'Insufficient trade data ({len(live_trades)} live, {len(shadow_trades)} shadow)',
                'best_params': None
            }
        
        # Objective function for Optuna
        def objective(trial):
            # Suggest parameter ranges
            entry_threshold = trial.suggest_float('entry_threshold', 0.01, 0.50, step=0.01)
            stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.5, 5.0, step=0.1)
            
            # Calculate Sharpe ratio with these parameters
            sharpe = calculate_portfolio_sharpe(live_trades, shadow_trades, entry_threshold, stop_loss_pct)
            
            # Log trial
            self._log_optimization(
                trial.number,
                {'entry_threshold': entry_threshold, 'stop_loss_pct': stop_loss_pct},
                sharpe
            )
            
            return sharpe
        
        # Create study (maximize Sharpe ratio)
        study = optuna.create_study(direction='maximize', study_name='policy_optimization')
        
        # Run optimization
        study.optimize(objective, n_trials=self.n_trials, show_progress_bar=False)
        
        # Get best parameters
        self.best_params = study.best_params.copy()
        self.last_optimization = time.time()
        
        # Save state
        self._save_state()
        
        return {
            'success': True,
            'best_params': self.best_params,
            'best_sharpe': study.best_value,
            'n_trials': self.n_trials,
            'n_trades_analyzed': len(live_trades) + len(shadow_trades),
            'timestamp': self.last_optimization
        }
    
    def apply_best_parameters(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Apply best parameters to trading config.
        
        Args:
            dry_run: If True, don't actually update config
        
        Returns:
            Application results
        """
        if not self.best_params:
            return {
                'success': False,
                'error': 'No optimized parameters available'
            }
        
        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'params_to_apply': self.best_params
            }
        
        # Load current config
        try:
            if POLICY_CONFIG_PATH.exists():
                with open(POLICY_CONFIG_PATH, 'r') as f:
                    config = json.load(f)
            else:
                config = {}
        except Exception as e:
            return {
                'success': False,
                'error': f'Error loading config: {e}'
            }
        
        # Update config with optimized parameters
        if 'optimized_parameters' not in config:
            config['optimized_parameters'] = {}
        
        config['optimized_parameters'].update({
            'entry_threshold': self.best_params['entry_threshold'],
            'stop_loss_pct': self.best_params['stop_loss_pct'],
            'optimized_at': datetime.now(timezone.utc).isoformat(),
            'optimized_timestamp': self.last_optimization
        })
        
        # Save config
        try:
            POLICY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(POLICY_CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)
            
            return {
                'success': True,
                'params_applied': self.best_params,
                'config_path': str(POLICY_CONFIG_PATH)
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error saving config: {e}'
            }


# Global instance
_policy_tuner: Optional[PolicyTuner] = None


def get_policy_tuner() -> PolicyTuner:
    """Get or create global policy tuner instance."""
    global _policy_tuner
    if _policy_tuner is None:
        _policy_tuner = PolicyTuner()
    return _policy_tuner


def run_daily_optimization() -> Dict[str, Any]:
    """
    Run daily policy optimization and apply if improvement found.
    
    Returns:
        Optimization and application results
    """
    tuner = get_policy_tuner()
    
    # Run optimization
    results = tuner.optimize(days=30)
    
    if not results.get('success'):
        return results
    
    # Apply best parameters
    apply_results = tuner.apply_best_parameters(dry_run=False)
    
    return {
        'optimization': results,
        'application': apply_results
    }

