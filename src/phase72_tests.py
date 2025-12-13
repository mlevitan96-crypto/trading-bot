"""
Phase 7.2 End-to-End Tests
Tests all Phase 7.2 components and integration.
"""
import json
import os
from datetime import datetime
from typing import Dict, List


class Phase72Tests:
    """End-to-end tests for Phase 7.2 components."""
    
    def __init__(self):
        self.results = []
    
    def test_config_load_save(self) -> bool:
        """Test configuration loading and saving."""
        try:
            from src.phase72_config import Phase72Config, get_phase72_config
            
            # Load config
            config = get_phase72_config()
            original_enabled = config.enabled
            
            # Modify and save
            config.enabled = not original_enabled
            config.save()
            
            # Reload and verify
            from importlib import reload
            import src.phase72_config as cfg_module
            reload(cfg_module)
            
            new_config = cfg_module.get_phase72_config()
            success = new_config.enabled == (not original_enabled)
            
            # Restore
            config.enabled = original_enabled
            config.save()
            
            self.results.append(('config_load_save', success, 'Config persistence works'))
            return success
        except Exception as e:
            self.results.append(('config_load_save', False, f'Error: {str(e)}'))
            return False
    
    def test_short_suppression(self) -> bool:
        """Test SHORT suppression logic."""
        try:
            from src.phase72_execution import should_suppress_short
            
            # Test with LONG direction (should not suppress)
            suppress, reason = should_suppress_short("BTCUSDT", "LONG")
            success = not suppress
            
            # Test with SHORT direction
            suppress_short, reason = should_suppress_short("BTCUSDT", "SHORT")
            # Should suppress or not based on actual data
            
            self.results.append(('short_suppression', success, f'LONG not suppressed: {not suppress}'))
            return success
        except Exception as e:
            self.results.append(('short_suppression', False, f'Error: {str(e)}'))
            return False
    
    def test_futures_margin_calculation(self) -> bool:
        """Test futures margin budget calculation."""
        try:
            from src.phase72_execution import get_futures_margin_budget
            
            # Test with known portfolio value
            portfolio_value = 10000.0
            margin = get_futures_margin_budget(portfolio_value)
            
            # Should be between 6-10% of portfolio
            min_expected = portfolio_value * 0.06
            max_expected = portfolio_value * 0.10
            
            success = min_expected <= margin <= max_expected
            
            self.results.append(('futures_margin_calc', success, f'Margin ${margin:.2f} in range [${min_expected:.2f}, ${max_expected:.2f}]'))
            return success
        except Exception as e:
            self.results.append(('futures_margin_calc', False, f'Error: {str(e)}'))
            return False
    
    def test_ensemble_threshold_relaxation(self) -> bool:
        """Test ensemble threshold relaxation."""
        try:
            from src.phase72_execution import get_adjusted_ensemble_threshold
            from src.phase72_config import get_phase72_config
            
            config = get_phase72_config()
            
            # Test stable regime
            stable_threshold = get_adjusted_ensemble_threshold("Stable")
            expected_stable = config.base_ensemble_threshold - config.stable_regime_relax
            
            # Test trending regime
            trending_threshold = get_adjusted_ensemble_threshold("Trending")
            expected_trending = config.base_ensemble_threshold - config.trending_regime_relax
            
            success = (stable_threshold == expected_stable and trending_threshold == expected_trending)
            
            self.results.append(('ensemble_relaxation', success, f'Stable: {stable_threshold:.3f}, Trending: {trending_threshold:.3f}'))
            return success
        except Exception as e:
            self.results.append(('ensemble_relaxation', False, f'Error: {str(e)}'))
            return False
    
    def test_min_hold_check(self) -> bool:
        """Test minimum hold time enforcement."""
        try:
            from src.phase72_execution import check_min_hold_time
            
            # Create mock position with recent entry
            recent_position = {
                'entry_time': datetime.now().isoformat(),
                'symbol': 'BTCUSDT'
            }
            
            can_exit, reason = check_min_hold_time(recent_position, allow_protective_exit=False)
            
            # Should not allow exit (too recent)
            success = not can_exit
            
            self.results.append(('min_hold_check', success, f'Recent position exit blocked: {not can_exit}'))
            return success
        except Exception as e:
            self.results.append(('min_hold_check', False, f'Error: {str(e)}'))
            return False
    
    def test_diagnostics_logging(self) -> bool:
        """Test diagnostics can log signals."""
        try:
            from src.phase72_execution_diagnostics import log_signal_evaluation, get_diagnostics
            
            # Log a test signal
            log_signal_evaluation(
                symbol="TEST",
                strategy="TestStrategy",
                regime="Stable",
                side="LONG",
                ensemble_score=0.60,
                ensemble_threshold=0.55,
                portfolio_value=10000.0,
                strategy_budget=2000.0,
                available_budget=1500.0,
                position_size_requested=500.0,
                correlation_cap=0.30,
                correlation_exposure=0.25,
                open_positions_count=2,
                total_exposure=3000.0,
                executed=True,
                rejection_reasons=[]
            )
            
            # Verify logged
            diagnostics = get_diagnostics()
            success = len(diagnostics.diagnostics) > 0
            
            self.results.append(('diagnostics_logging', success, f'{len(diagnostics.diagnostics)} signals logged'))
            return success
        except Exception as e:
            self.results.append(('diagnostics_logging', False, f'Error: {str(e)}'))
            return False
    
    def test_strategy_demotion_check(self) -> bool:
        """Test strategy demotion logic."""
        try:
            from src.phase72_execution import check_strategy_for_demotion
            
            # Test with known strategy
            should_demote, stats = check_strategy_for_demotion("Sentiment-Fusion", "Stable")
            
            # Should return valid stats
            success = isinstance(stats, dict)
            
            self.results.append(('strategy_demotion', success, f'Demotion check returned stats: {bool(stats)}'))
            return success
        except Exception as e:
            self.results.append(('strategy_demotion', False, f'Error: {str(e)}'))
            return False
    
    def test_health_checks(self) -> bool:
        """Test health check system."""
        try:
            from src.phase72_health_checks import run_health_checks
            
            report = run_health_checks()
            
            # Verify report structure
            success = (
                'timestamp' in report and
                'overall_healthy' in report and
                'checks' in report
            )
            
            self.results.append(('health_checks', success, f'Health report generated: {len(report["checks"])} checks'))
            return success
        except Exception as e:
            self.results.append(('health_checks', False, f'Error: {str(e)}'))
            return False
    
    def run_all_tests(self) -> Dict:
        """Run all tests and return results."""
        print(f"\n{'='*60}")
        print("🧪 PHASE 7.2 END-TO-END TESTS")
        print(f"{'='*60}\n")
        
        tests = [
            self.test_config_load_save,
            self.test_short_suppression,
            self.test_futures_margin_calculation,
            self.test_ensemble_threshold_relaxation,
            self.test_min_hold_check,
            self.test_diagnostics_logging,
            self.test_strategy_demotion_check,
            self.test_health_checks
        ]
        
        passed = 0
        failed = 0
        
        for test in tests:
            test_name = test.__name__.replace('test_', '').replace('_', ' ').title()
            print(f"Running: {test_name}...", end=' ')
            
            try:
                result = test()
                if result:
                    print("✅ PASS")
                    passed += 1
                else:
                    print("❌ FAIL")
                    failed += 1
            except Exception as e:
                print(f"❌ ERROR: {str(e)}")
                failed += 1
        
        print(f"\n{'='*60}")
        print(f"Results: {passed} passed, {failed} failed")
        print(f"{'='*60}\n")
        
        return {
            'timestamp': datetime.now().isoformat(),
            'total': passed + failed,
            'passed': passed,
            'failed': failed,
            'success_rate': passed / (passed + failed) if (passed + failed) > 0 else 0,
            'results': self.results
        }


def run_tests() -> Dict:
    """Run all Phase 7.2 tests."""
    tester = Phase72Tests()
    return tester.run_all_tests()


if __name__ == "__main__":
    results = run_tests()
    print(f"\nTest Summary: {results['passed']}/{results['total']} passed ({results['success_rate']*100:.1f}%)")
