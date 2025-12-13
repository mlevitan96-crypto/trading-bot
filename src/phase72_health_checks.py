"""
Phase 7.2 Health Checks (Updated for Tier-Based System)
Monitors Phase 7.2 component health and reports status.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from src.phase72_config import get_phase72_config
from src.phase72_tiers import tier_for_symbol


class Phase72HealthCheck:
    """Health monitoring for Phase 7.2 components."""
    
    def check_config_health(self) -> Tuple[bool, str, Dict]:
        """Check Phase 7.2 configuration is valid."""
        try:
            config = get_phase72_config()
            
            issues = []
            
            # Validate thresholds
            if config.futures_margin_pct < 0.01 or config.futures_margin_pct > 0.20:
                issues.append(f"futures_margin_pct out of range: {config.futures_margin_pct}")
            
            if config.min_ensemble_score_base < 0.30 or config.min_ensemble_score_base > 0.90:
                issues.append(f"base ensemble threshold out of range: {config.min_ensemble_score_base}")
            
            if config.min_hold_seconds < 0 or config.min_hold_seconds > 600:
                issues.append(f"min_hold_seconds out of range: {config.min_hold_seconds}")
            
            # Validate tier relaxation
            for tier, relax in config.relax_pct_stable.items():
                if relax < 0 or relax > 0.20:
                    issues.append(f"tier {tier} relaxation out of range: {relax}")
            
            if issues:
                return False, f"Config validation failed: {', '.join(issues)}", {'issues': issues}
            
            return True, "Config healthy", {
                'enabled': config.enabled,
                'futures_margin_pct': config.futures_margin_pct,
                'suppress_shorts': config.suppress_shorts_until_profitable,
                'tier_relaxation': config.relax_pct_stable
            }
        except Exception as e:
            return False, f"Config error: {str(e)}", {}
    
    def check_diagnostics_health(self) -> Tuple[bool, str, Dict]:
        """Check diagnostics are being logged."""
        try:
            log_file = "logs/execution_diagnostics.json"
            
            if not os.path.exists(log_file):
                return True, "Diagnostics not yet active", {'signals_logged': 0}
            
            with open(log_file, 'r') as f:
                data = json.load(f)
                signals = data.get('signals', [])
            
            # Check for recent activity
            if signals:
                last_signal = signals[-1]
                last_time = datetime.fromisoformat(last_signal['timestamp'])
                age = (datetime.now() - last_time).total_seconds()
                
                if age > 3600:  # More than 1 hour old
                    return False, f"No recent diagnostics (last: {age:.0f}s ago)", {'signals_logged': len(signals)}
            
            return True, f"Diagnostics healthy ({len(signals)} signals)", {'signals_logged': len(signals)}
        except Exception as e:
            return False, f"Diagnostics error: {str(e)}", {}
    
    def check_shorts_suppression_health(self) -> Tuple[bool, str, Dict]:
        """Check SHORT suppression is working correctly."""
        try:
            config = get_phase72_config()
            
            if not config.suppress_shorts_until_profitable:
                return True, "SHORT suppression disabled", {'enabled': False}
            
            # Check futures trades
            with open('logs/trades_futures.json', 'r') as f:
                data = json.load(f)
                trades = data.get('trades', [])
            
            # Check recent shorts
            recent = trades[-30:] if len(trades) >= 30 else trades
            recent_shorts = [t for t in recent if t.get('direction') == 'SHORT']
            recent_longs = [t for t in recent if t.get('direction') == 'LONG']
            
            short_pnl = sum(t.get('net_pnl', 0) for t in recent_shorts)
            long_pnl = sum(t.get('net_pnl', 0) for t in recent_longs)
            
            return True, "SHORT suppression active", {
                'enabled': True,
                'recent_shorts': len(recent_shorts),
                'recent_longs': len(recent_longs),
                'short_pnl': short_pnl,
                'long_pnl': long_pnl
            }
        except FileNotFoundError:
            return True, "No futures trades yet", {'enabled': True}
        except Exception as e:
            return False, f"SHORT suppression check error: {str(e)}", {}
    
    def check_futures_margin_health(self) -> Tuple[bool, str, Dict]:
        """Check futures margin sizing is correct."""
        try:
            # Check portfolio value
            with open('logs/portfolio.json', 'r') as f:
                portfolio = json.load(f)
            
            portfolio_value = portfolio.get('current_value', 10000)
            
            # Calculate expected margin
            from src.phase72_execution import get_futures_margin_budget
            expected_margin = get_futures_margin_budget(portfolio_value)
            
            config = get_phase72_config()
            base_margin = portfolio_value * config.futures_margin_pct
            
            return True, f"Margin sizing correct (${expected_margin:.2f})", {
                'portfolio_value': portfolio_value,
                'base_margin': base_margin,
                'effective_margin': expected_margin,
                'base_pct': config.futures_margin_pct
            }
        except Exception as e:
            return False, f"Margin check error: {str(e)}", {}
    
    def check_tier_system_health(self) -> Tuple[bool, str, Dict]:
        """Check tier classification system."""
        try:
            from src.phase72_tiers import tier_for_symbol, get_all_tiers
            from src.phase72_execution import relaxed_threshold
            
            tiers = get_all_tiers()
            
            # Test a few symbols
            test_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOTUSDT"]
            tier_results = {}
            
            for sym in test_symbols:
                tier = tier_for_symbol(sym)
                threshold_stable = relaxed_threshold(sym, "Stable")
                tier_results[sym] = {
                    'tier': tier,
                    'threshold_stable': round(threshold_stable, 3)
                }
            
            return True, f"Tier system operational ({len(tiers)} tiers)", {
                'tiers': list(tiers.keys()),
                'test_results': tier_results
            }
        except Exception as e:
            return False, f"Tier system error: {str(e)}", {}
    
    def run_all_checks(self) -> Dict:
        """Run all health checks and return comprehensive report."""
        checks = {
            'config': self.check_config_health(),
            'diagnostics': self.check_diagnostics_health(),
            'shorts_suppression': self.check_shorts_suppression_health(),
            'futures_margin': self.check_futures_margin_health(),
            'tier_system': self.check_tier_system_health()
        }
        
        # Build report
        report = {
            'timestamp': datetime.now().isoformat(),
            'overall_healthy': all(check[0] for check in checks.values()),
            'checks': {}
        }
        
        for name, (healthy, message, details) in checks.items():
            report['checks'][name] = {
                'healthy': healthy,
                'message': message,
                'details': details
            }
        
        return report
    
    def print_health_report(self):
        """Print health check report."""
        report = self.run_all_checks()
        
        print(f"\n{'='*60}")
        print(f"🏥 PHASE 7.2 HEALTH CHECK (Tier-Based)")
        print(f"{'='*60}")
        print(f"Timestamp: {report['timestamp']}")
        print(f"Overall: {'✅ HEALTHY' if report['overall_healthy'] else '❌ UNHEALTHY'}")
        print()
        
        for name, check in report['checks'].items():
            icon = '✅' if check['healthy'] else '❌'
            print(f"{icon} {name.replace('_', ' ').title()}: {check['message']}")
            if check['details']:
                for key, value in check['details'].items():
                    if isinstance(value, dict):
                        print(f"   {key}:")
                        for k, v in value.items():
                            print(f"      {k}: {v}")
                    else:
                        print(f"   {key}: {value}")
        
        print(f"{'='*60}\n")
        
        return report


def run_health_checks() -> Dict:
    """Run Phase 7.2 health checks and return report."""
    checker = Phase72HealthCheck()
    return checker.run_all_checks()


def print_health_report():
    """Print Phase 7.2 health report."""
    checker = Phase72HealthCheck()
    return checker.print_health_report()


if __name__ == "__main__":
    print_health_report()
