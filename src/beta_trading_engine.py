#!/usr/bin/env python3
"""
BETA TRADING ENGINE - Signal Inversion Strategy (EXPANDED)
============================================================
Parallel trading bot that inverts ALL tier signals based on comprehensive
analysis of 630 enriched decisions showing systematic signal misprediction.

KEY FINDING: Signals are systematically inverted
- BUY signals: 16.1% actual WR -> 83.9% if inverted
- SELL signals: 21.6% actual WR -> 78.4% if inverted

Strategy Logic (UPDATED):
- ALL tiers (A, B, C, D, F): INVERT direction based on promoted intelligence rules
- Moderate OFI (0.3-0.5): BOOST sizing (25.5% WR - best bucket)
- Very strong OFI (>0.7): REDUCE sizing (17.9% WR - worse than expected)
- Bullish ensemble (>0.05): ALWAYS invert (12.9% WR - worst)

This runs alongside Alpha bot, sharing market data but with isolated:
- Portfolio tracking
- Position management
- P&L and performance metrics
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.bot_registry import BotRegistry
from src.intelligence_inversion import apply_intelligence_inversion, get_inversion_stats

# Singleton instance for main trading loop integration
_BETA_ENGINE = None

def get_beta_engine():
    """Get singleton Beta engine instance for main trading loop integration."""
    global _BETA_ENGINE
    if _BETA_ENGINE is None:
        _BETA_ENGINE = BetaTradingEngine()
    return _BETA_ENGINE


class BetaTradingEngine:
    """
    Beta bot trading engine with signal inversion strategy.
    """
    
    def __init__(self):
        self.registry = BotRegistry("beta")
        self.config = self._load_config()
        self.state = self.registry.get_state()
        
        self.invert_tiers = self.config.get('invert_tiers', ['F'])
        self.block_tiers = self.config.get('block_tiers', [])
        self.sizing_multipliers = self.config.get('sizing_multipliers', {
            "A": 1.5, "B": 1.2, "C": 1.0, "D": 0.8, "F": 0.5
        })
        self.min_ofi_threshold = self.config.get('min_ofi_threshold', 0.5)
        self.enabled = self.config.get('enabled', True)
        self.paper_trading = self.config.get('paper_trading', True)
    
    def _load_config(self) -> Dict:
        """Load Beta bot configuration."""
        config = self.registry.read_json("configs/beta_config.json")
        return config or {
            "bot_id": "beta",
            "strategy": "signal_inversion",
            "invert_tiers": ["F"],
            "block_tiers": [],
            "sizing_multipliers": {"A": 1.5, "B": 1.2, "C": 1.0, "D": 0.8, "F": 0.5},
            "min_ofi_threshold": 0.5,
            "enabled": True,
            "paper_trading": True
        }
    
    def _log(self, msg: str, level: str = "INFO"):
        """Log with Beta prefix."""
        ts = datetime.utcnow().isoformat() + "Z"
        print(f"[{ts}] [BETA] [{level}] {msg}")
    
    def get_confidence_tier(self, signal: Dict) -> str:
        """
        Compute confidence tier for a signal using multi-factor scoring.
        Uses same logic as confidence_tier_backtest.py.
        """
        ofi = signal.get('ofi', 0.5)
        ensemble = abs(signal.get('ensemble', 0))
        direction = signal.get('direction', 'LONG')
        symbol = signal.get('symbol', '')
        symbol_base = symbol.replace('USDT', '')
        
        score = 50
        
        if ofi >= 0.8:
            score += 15
        elif ofi >= 0.7:
            score += 10
        elif ofi >= 0.6:
            score += 5
        elif ofi < 0.4:
            score -= 10
        
        if ensemble >= 0.3:
            score += 10
        elif ensemble >= 0.2:
            score += 5
        elif ensemble < 0.1:
            score -= 5
        
        direction_biases = self._get_direction_biases()
        if symbol_base in direction_biases:
            if direction_biases[symbol_base] == direction:
                score += 15
            else:
                score -= 15
        
        known_good = {"SOL": "LONG", "DOT": "SHORT", "BNB": "SHORT", "ETH": "SHORT"}
        if symbol_base in known_good:
            if known_good[symbol_base] == direction:
                score += 10
            else:
                score -= 10
        
        if score >= 75:
            return "A"
        elif score >= 60:
            return "B"
        elif score >= 45:
            return "C"
        elif score >= 30:
            return "D"
        else:
            return "F"
    
    def _get_direction_biases(self) -> Dict[str, str]:
        """Get learned direction biases from deep intelligence."""
        biases = {}
        
        try:
            analysis = self.registry.read_json("feature_store/deep_intelligence_analysis.json")
            if analysis:
                for rec in analysis.get('recommendations', []):
                    if rec.get('type') == 'direction_bias':
                        symbol = rec.get('symbol', '').replace('USDT', '')
                        direction = rec.get('preferred_direction')
                        if symbol and direction:
                            biases[symbol] = direction
        except Exception as e:
            self._log(f"Error loading direction biases: {e}", "WARN")
        
        if not biases:
            biases = {"DOT": "SHORT", "BNB": "SHORT"}
        
        return biases
    
    def _log_blocked_signal(self, signal: Dict, block_reason: str, block_gate: str):
        """Log blocked signal for learning system counterfactual analysis."""
        try:
            from src.beta_learning_system import BetaLearningSystem
            learner = BetaLearningSystem()
            learner.log_blocked_signal(signal, block_reason, block_gate)
        except Exception as e:
            self._log(f"Failed to log blocked signal: {e}", "WARN")
    
    def process_signal(self, signal: Dict) -> Optional[Dict]:
        """
        Process a signal through Beta's inversion strategy.
        
        UPDATED: Now uses intelligence_inversion module based on 630 enriched decisions
        showing systematic signal misprediction (16-22% WR -> 78-84% if inverted).
        
        Returns modified signal or None if blocked.
        """
        if not self.enabled:
            return None
        
        symbol = signal.get('symbol', 'UNKNOWN')
        direction = signal.get('direction', 'LONG')
        ofi = abs(signal.get('ofi', 0.5))
        ensemble = signal.get('ensemble', 0)
        
        tier = self.get_confidence_tier(signal)
        
        original_signal = signal.copy()
        original_signal['tier'] = tier
        
        if ofi < self.min_ofi_threshold:
            self._log(f"Blocked {symbol}: OFI {ofi:.2f} < {self.min_ofi_threshold}", "BLOCK")
            self._log_blocked_signal(original_signal, f"OFI {ofi:.3f} below threshold {self.min_ofi_threshold}", "ofi_filter")
            return None
        
        if tier in self.block_tiers:
            self._log(f"Blocked {symbol}: Tier {tier} in block list", "BLOCK")
            self._log_blocked_signal(original_signal, f"Tier {tier} in block list", "tier_block")
            return None
        
        intel_signal = apply_intelligence_inversion({
            "symbol": symbol,
            "direction": direction,
            "ofi": ofi,
            "ensemble": ensemble
        }, bot_id="beta")
        
        modified_signal = signal.copy()
        modified_signal['original_direction'] = direction
        modified_signal['original_tier'] = tier
        modified_signal['bot_id'] = 'beta'
        modified_signal['direction'] = intel_signal['direction']
        modified_signal['inverted'] = intel_signal.get('inverted', False)
        modified_signal['inversion_reason'] = intel_signal.get('inversion_reason')
        modified_signal['ofi_action'] = intel_signal.get('ofi_action')
        
        if intel_signal.get('inverted'):
            self._log(f"INVERTED {symbol}: {direction} -> {intel_signal['direction']} | {intel_signal.get('inversion_reason')}", "INVERT")
        
        base_size = signal.get('base_notional_usd', signal.get('size_usd', 200))
        tier_multiplier = self.sizing_multipliers.get(tier, 1.0)
        intel_size_modifier = intel_signal.get('size_modifier', 1.0)
        modified_signal['size_usd'] = base_size * tier_multiplier * intel_size_modifier
        modified_signal['tier_multiplier'] = tier_multiplier
        modified_signal['intel_size_modifier'] = intel_size_modifier
        modified_signal['tier'] = tier
        
        return modified_signal
    
    def simulate_trade(self, signal: Dict, outcome: Dict) -> Dict:
        """
        Simulate a trade based on signal and outcome data.
        Used for paper trading and backtesting.
        """
        pnl = outcome.get('pnl', 0)
        
        if signal.get('inverted', False):
            pnl = -pnl
        
        pnl = pnl * signal.get('tier_multiplier', 1.0)
        
        trade = {
            "bot_id": "beta",
            "symbol": signal.get('symbol'),
            "direction": signal.get('direction'),
            "original_direction": signal.get('original_direction'),
            "inverted": signal.get('inverted', False),
            "tier": signal.get('original_tier'),
            "size_usd": signal.get('size_usd'),
            "ofi": signal.get('ofi'),
            "ensemble": signal.get('ensemble'),
            "pnl": pnl,
            "pnl_pct": outcome.get('pnl_pct', 0),
            "entry_price": outcome.get('entry_price'),
            "exit_price": outcome.get('exit_price'),
            "duration_seconds": outcome.get('duration_seconds', 0),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        return trade
    
    def _normalize_decision(self, decision: Dict) -> Dict:
        """Normalize enriched decision to standard signal format."""
        signal_ctx = decision.get('signal_ctx', {})
        outcome = decision.get('outcome', {})
        
        direction = signal_ctx.get('side', decision.get('direction', 'LONG'))
        if direction == 'SELL':
            direction = 'SHORT'
        elif direction == 'BUY':
            direction = 'LONG'
        
        return {
            'symbol': decision.get('symbol', 'UNKNOWN'),
            'direction': direction,
            'ofi': abs(signal_ctx.get('ofi', 0.5)),
            'ensemble': signal_ctx.get('ensemble', 0),
            'regime': signal_ctx.get('regime', 'Unknown'),
            'pnl': outcome.get('pnl_usd', 0),
            'pnl_pct': outcome.get('pnl_pct', 0),
            'entry_price': outcome.get('entry_price', 0),
            'exit_price': outcome.get('exit_price', 0),
            'ts': decision.get('ts', 0)
        }
    
    def run_backtest(self, decisions: List[Dict]) -> Dict:
        """
        Run backtest on historical enriched decisions.
        """
        self._log(f"Starting backtest on {len(decisions)} decisions")
        
        results = {
            "total_decisions": len(decisions),
            "processed": 0,
            "blocked": 0,
            "inverted": 0,
            "trades": [],
            "tier_distribution": {},
            "total_pnl": 0,
            "wins": 0,
            "losses": 0
        }
        
        for decision in decisions:
            normalized = self._normalize_decision(decision)
            signal = self.process_signal(normalized)
            
            if signal is None:
                results["blocked"] += 1
                continue
            
            results["processed"] += 1
            tier = signal.get('original_tier', 'F')
            results["tier_distribution"][tier] = results["tier_distribution"].get(tier, 0) + 1
            
            if signal.get('inverted', False):
                results["inverted"] += 1
            
            original_pnl = normalized.get('pnl', 0)
            if signal.get('inverted', False):
                pnl = -original_pnl
            else:
                pnl = original_pnl
            pnl = pnl * signal.get('tier_multiplier', 1.0)
            
            results["total_pnl"] += pnl
            if pnl > 0:
                results["wins"] += 1
            else:
                results["losses"] += 1
            
            results["trades"].append({
                "symbol": signal.get('symbol'),
                "direction": signal.get('direction'),
                "original_direction": signal.get('original_direction'),
                "inverted": signal.get('inverted'),
                "tier": tier,
                "original_pnl": original_pnl,
                "adjusted_pnl": pnl
            })
        
        total = results["wins"] + results["losses"]
        results["win_rate"] = (results["wins"] / total * 100) if total > 0 else 0
        results["avg_pnl"] = results["total_pnl"] / total if total > 0 else 0
        
        self._log(f"Backtest complete: {results['processed']} trades, "
                  f"{results['win_rate']:.1f}% WR, ${results['total_pnl']:.2f} P&L")
        
        return results
    
    def get_status(self) -> Dict:
        """Get Beta bot status."""
        portfolio = self.registry.get_portfolio()
        perf = self.registry.get_performance_summary()
        
        return {
            "bot_id": "beta",
            "strategy": "signal_inversion",
            "enabled": self.enabled,
            "paper_trading": self.paper_trading,
            "invert_tiers": self.invert_tiers,
            "block_tiers": self.block_tiers,
            "min_ofi_threshold": self.min_ofi_threshold,
            "portfolio_value": portfolio.get('current_value', 10000),
            "realized_pnl": portfolio.get('realized_pnl', 0),
            "performance": perf,
            "last_updated": datetime.utcnow().isoformat() + "Z"
        }


def run_historical_backtest():
    """Run backtest on historical enriched decisions."""
    print("=" * 60)
    print("BETA BOT - HISTORICAL BACKTEST")
    print("=" * 60)
    
    engine = BetaTradingEngine()
    
    enriched_path = "logs/enriched_decisions.jsonl"
    if not os.path.exists(enriched_path):
        print(f"No enriched decisions found at {enriched_path}")
        return
    
    decisions = []
    with open(enriched_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    decisions.append(json.loads(line))
                except:
                    continue
    
    print(f"Loaded {len(decisions)} decisions")
    
    results = engine.run_backtest(decisions)
    
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"Total Decisions:  {results['total_decisions']}")
    print(f"Processed:        {results['processed']}")
    print(f"Blocked:          {results['blocked']}")
    print(f"Inverted:         {results['inverted']}")
    print(f"Win Rate:         {results['win_rate']:.1f}%")
    print(f"Total P&L:        ${results['total_pnl']:.2f}")
    print(f"Avg P&L/Trade:    ${results['avg_pnl']:.2f}")
    print(f"\nTier Distribution: {results['tier_distribution']}")
    
    engine.registry.write_json("logs/beta/backtest_results.json", results)
    print(f"\nResults saved to logs/beta/backtest_results.json")
    
    return results


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        run_historical_backtest()
    else:
        engine = BetaTradingEngine()
        status = engine.get_status()
        print(json.dumps(status, indent=2))
