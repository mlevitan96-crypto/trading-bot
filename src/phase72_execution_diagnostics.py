"""
Phase 7.2 - Execution Diagnostics
Traces signal path to understand rejection reasons and unblock execution.
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

DIAGNOSTICS_LOG = "logs/execution_diagnostics.json"


@dataclass
class SignalDiagnostic:
    """Captures complete signal evaluation path."""
    timestamp: str
    symbol: str
    strategy: str
    regime: str
    side: str
    
    # Signal strength
    ensemble_score: float
    ensemble_threshold: float
    ensemble_passed: bool
    
    # Budget checks
    portfolio_value: float
    strategy_budget: float
    available_budget: float
    position_size_requested: float
    budget_passed: bool
    
    # Correlation checks
    correlation_cap: Optional[float]
    correlation_exposure: Optional[float]
    correlation_passed: bool
    
    # Final decision
    executed: bool
    rejection_reasons: List[str]
    
    # Context
    open_positions_count: int
    total_exposure: float


class ExecutionDiagnostics:
    """Tracks and analyzes signal execution patterns."""
    
    def __init__(self):
        self.diagnostics: List[Dict] = []
        self.load()
    
    def load(self):
        """Load existing diagnostics."""
        if os.path.exists(DIAGNOSTICS_LOG):
            try:
                with open(DIAGNOSTICS_LOG, 'r') as f:
                    data = json.load(f)
                    self.diagnostics = data.get('signals', [])
            except:
                self.diagnostics = []
    
    def save(self):
        """Save diagnostics to file."""
        os.makedirs(os.path.dirname(DIAGNOSTICS_LOG), exist_ok=True)
        with open(DIAGNOSTICS_LOG, 'w') as f:
            json.dump({
                'signals': self.diagnostics[-1000:],  # Keep last 1000
                'last_updated': datetime.now().isoformat()
            }, f, indent=2)
    
    def log_signal(self, diagnostic: SignalDiagnostic):
        """Log a signal evaluation."""
        self.diagnostics.append(asdict(diagnostic))
        self.save()
    
    def get_rejection_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Analyze rejection patterns over last N hours."""
        from datetime import timedelta
        
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = [
            d for d in self.diagnostics
            if datetime.fromisoformat(d['timestamp']) > cutoff
        ]
        
        if not recent:
            return {
                'total_signals': 0,
                'executed': 0,
                'execution_rate': 0.0,
                'rejection_reasons': {}
            }
        
        executed = [d for d in recent if d['executed']]
        rejected = [d for d in recent if not d['executed']]
        
        # Count rejection reasons
        reason_counts = {}
        for d in rejected:
            for reason in d.get('rejection_reasons', []):
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        
        # Strategy breakdown
        strategy_stats = {}
        for d in recent:
            strat = d['strategy']
            if strat not in strategy_stats:
                strategy_stats[strat] = {'total': 0, 'executed': 0}
            strategy_stats[strat]['total'] += 1
            if d['executed']:
                strategy_stats[strat]['executed'] += 1
        
        return {
            'period_hours': hours,
            'total_signals': len(recent),
            'executed': len(executed),
            'rejected': len(rejected),
            'execution_rate': len(executed) / len(recent) if recent else 0.0,
            'rejection_reasons': reason_counts,
            'by_strategy': strategy_stats,
            'avg_ensemble_score': sum(d['ensemble_score'] for d in recent) / len(recent),
            'avg_ensemble_threshold': sum(d['ensemble_threshold'] for d in recent) / len(recent)
        }
    
    def print_analysis(self, hours: int = 24):
        """Print diagnostic analysis."""
        summary = self.get_rejection_summary(hours)
        
        print(f"\n{'='*60}")
        print(f"📊 EXECUTION DIAGNOSTICS ({hours}h)")
        print(f"{'='*60}")
        print(f"Total Signals: {summary['total_signals']}")
        print(f"Executed: {summary['executed']} ({summary['execution_rate']*100:.1f}%)")
        print(f"Rejected: {summary['rejected']} ({(1-summary['execution_rate'])*100:.1f}%)")
        print()
        
        if summary['rejection_reasons']:
            print("Top Rejection Reasons:")
            for reason, count in sorted(summary['rejection_reasons'].items(), key=lambda x: x[1], reverse=True):
                pct = count / summary['rejected'] * 100 if summary['rejected'] > 0 else 0
                print(f"  {reason}: {count} ({pct:.1f}%)")
            print()
        
        if summary['by_strategy']:
            print("By Strategy:")
            for strat, stats in sorted(summary['by_strategy'].items()):
                rate = stats['executed'] / stats['total'] * 100 if stats['total'] > 0 else 0
                print(f"  {strat}: {stats['executed']}/{stats['total']} ({rate:.1f}%)")
            print()
        
        print(f"Avg Ensemble Score: {summary['avg_ensemble_score']:.3f}")
        print(f"Avg Threshold: {summary['avg_ensemble_threshold']:.3f}")
        print(f"{'='*60}\n")


# Global instance
_diagnostics = None

def get_diagnostics() -> ExecutionDiagnostics:
    """Get or create global diagnostics instance."""
    global _diagnostics
    if _diagnostics is None:
        _diagnostics = ExecutionDiagnostics()
    return _diagnostics


def log_signal_evaluation(
    symbol: str,
    strategy: str,
    regime: str,
    side: str,
    ensemble_score: float,
    ensemble_threshold: float,
    portfolio_value: float,
    strategy_budget: float,
    available_budget: float,
    position_size_requested: float,
    correlation_cap: Optional[float],
    correlation_exposure: Optional[float],
    open_positions_count: int,
    total_exposure: float,
    executed: bool,
    rejection_reasons: List[str]
):
    """Log a signal evaluation with full context."""
    diagnostic = SignalDiagnostic(
        timestamp=datetime.now().isoformat(),
        symbol=symbol,
        strategy=strategy,
        regime=regime,
        side=side,
        ensemble_score=ensemble_score,
        ensemble_threshold=ensemble_threshold,
        ensemble_passed=ensemble_score >= ensemble_threshold,
        portfolio_value=portfolio_value,
        strategy_budget=strategy_budget,
        available_budget=available_budget,
        position_size_requested=position_size_requested,
        budget_passed=position_size_requested <= available_budget,
        correlation_cap=correlation_cap,
        correlation_exposure=correlation_exposure,
        correlation_passed=(correlation_exposure <= correlation_cap) if (correlation_cap is not None and correlation_exposure is not None) else True,
        executed=executed,
        rejection_reasons=rejection_reasons,
        open_positions_count=open_positions_count,
        total_exposure=total_exposure
    )
    
    get_diagnostics().log_signal(diagnostic)


def print_diagnostics_summary(hours: int = 24):
    """Print execution diagnostics summary."""
    get_diagnostics().print_analysis(hours)
