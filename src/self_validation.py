"""
Self-Validation & Questioning Layer (SVQL)

Autonomous validation system that prevents bugs from reaching production by:
1. Pre-execution validation of parameters, types, and business rules
2. Post-execution verification that results match expectations
3. Drift detection for systematic policy violations
4. Self-questioning prompts to catch logic errors

This layer would have caught the position sizing bug where size_usd (USD) was
incorrectly passed as 'size' parameter (coin quantity) causing 10-100x undersized positions.
"""

import os
import json
import time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

# Import policy for validation bounds with win-rate scaling support
try:
    from config.trading_policy import TRADING_POLICY, get_scaled_position_limits
    
    MIN_POSITION_USD = TRADING_POLICY["MIN_POSITION_SIZE_USD"]
    MAX_POSITION_USD = TRADING_POLICY["MAX_POSITION_SIZE_USD"]
    
    def get_dynamic_position_limits():
        """Get current position limits based on win rate scaling if enabled."""
        if not TRADING_POLICY.get("ENABLE_WIN_RATE_SCALING", False):
            return MIN_POSITION_USD, MAX_POSITION_USD
        
        try:
            from src.data_registry import DataRegistry as DR
            closed_positions = DR.get_closed_positions(hours=24)
            
            if closed_positions:
                wins = [p for p in closed_positions if float(p.get("net_pnl", 0) or 0) > 0]
                current_wr = len(wins) / len(closed_positions) if closed_positions else 0.4
                recent_pnl = sum(float(p.get("net_pnl", 0) or 0) for p in closed_positions)
                pnl_positive = recent_pnl > 0
            else:
                current_wr = 0.40
                pnl_positive = True
            
            scaled = get_scaled_position_limits(current_wr, pnl_positive)
            return scaled["min_size"], scaled["max_size"]
        except:
            return MIN_POSITION_USD, MAX_POSITION_USD
except ImportError:
    MIN_POSITION_USD = 20
    MAX_POSITION_USD = 3000
    
    def get_dynamic_position_limits():
        return MIN_POSITION_USD, MAX_POSITION_USD

VALIDATION_LOG = "logs/self_validation.jsonl"


@dataclass
class ValidationResult:
    """Result of a validation check"""
    passed: bool
    severity: str  # OK, WARNING, CRITICAL
    validator: str
    message: str
    details: Dict = None
    
    def to_dict(self):
        return {
            "passed": self.passed,
            "severity": self.severity,
            "validator": self.validator,
            "message": self.message,
            "details": self.details or {}
        }


class SignalSchemaGuard:
    """Validates signal parameters have correct types and semantics"""
    
    def validate(self, signal: Dict, params: Dict) -> ValidationResult:
        """
        Ensure params contain margin_usd (USD value), not coin quantity.
        This catches the USD-vs-quantity bug.
        """
        issues = []
        
        # Check for margin_usd presence
        if "margin_usd" not in params:
            issues.append("Missing 'margin_usd' - execution will fail")
        
        # Check margin_usd is reasonable USD value (not coin quantity)
        margin = params.get("margin_usd", 0)
        if margin > 0 and margin < 1:
            issues.append(f"margin_usd={margin} looks like coin quantity, not USD value!")
        
        # Warn if 'size' is present and looks like USD (common mistake)
        if "size" in params and params["size"] > 100:
            issues.append(f"'size'={params['size']} looks like USD, should be coin quantity!")
        
        if issues:
            return ValidationResult(
                passed=False,
                severity="CRITICAL",
                validator="SignalSchemaGuard",
                message="Parameter type mismatch detected",
                details={"issues": issues, "params": params}
            )
        
        return ValidationResult(
            passed=True,
            severity="OK",
            validator="SignalSchemaGuard",
            message="Signal schema valid"
        )


class PolicyBoundsGuard:
    """Enforces position sizing within configured policy bounds"""
    
    def validate(self, signal: Dict, params: Dict) -> ValidationResult:
        """Check margin allocation is within $200-$3000 policy bounds"""
        margin = params.get("margin_usd", 0)
        
        if margin < MIN_POSITION_USD:
            return ValidationResult(
                passed=False,
                severity="CRITICAL",
                validator="PolicyBoundsGuard",
                message=f"Position size ${margin:.2f} below minimum ${MIN_POSITION_USD}",
                details={
                    "margin_usd": margin,
                    "policy_min": MIN_POSITION_USD,
                    "policy_max": MAX_POSITION_USD,
                    "violation_pct": ((MIN_POSITION_USD - margin) / MIN_POSITION_USD) * 100
                }
            )
        
        if margin > MAX_POSITION_USD:
            return ValidationResult(
                passed=False,
                severity="WARNING",
                validator="PolicyBoundsGuard",
                message=f"Position size ${margin:.2f} above maximum ${MAX_POSITION_USD}",
                details={
                    "margin_usd": margin,
                    "policy_min": MIN_POSITION_USD,
                    "policy_max": MAX_POSITION_USD
                }
            )
        
        return ValidationResult(
            passed=True,
            severity="OK",
            validator="PolicyBoundsGuard",
            message=f"Position size ${margin:.2f} within policy bounds"
        )


class ConversionIntentChecker:
    """Verifies USD→quantity conversion preserves value intent"""
    
    def validate(self, signal: Dict, params: Dict, execution: Dict = None) -> ValidationResult:
        """
        If execution happened, verify: quantity * price ≈ margin_usd * leverage
        This catches bugs where quantity calculation is wrong.
        """
        if not execution:
            return ValidationResult(passed=True, severity="OK", validator="ConversionIntentChecker", message="Pre-execution check passed")
        
        margin_usd = params.get("margin_usd", 0)
        leverage = params.get("leverage", 1)
        expected_notional = margin_usd * leverage
        
        actual_size = execution.get("size", 0)  # Coin quantity
        entry_price = execution.get("entry_price", 0)
        actual_notional = actual_size * entry_price
        
        if expected_notional > 0:
            deviation_pct = abs(actual_notional - expected_notional) / expected_notional
            
            if deviation_pct > 0.10:  # >10% deviation
                return ValidationResult(
                    passed=False,
                    severity="CRITICAL",
                    validator="ConversionIntentChecker",
                    message=f"USD→quantity conversion failed: {deviation_pct*100:.1f}% deviation",
                    details={
                        "expected_notional_usd": expected_notional,
                        "actual_notional_usd": actual_notional,
                        "coin_quantity": actual_size,
                        "entry_price": entry_price,
                        "deviation_pct": deviation_pct * 100
                    }
                )
        
        return ValidationResult(
            passed=True,
            severity="OK",
            validator="ConversionIntentChecker",
            message="USD→quantity conversion verified"
        )


class ExecutionOutcomeChecker:
    """Validates executed position matches requested parameters"""
    
    def validate(self, params: Dict, position: Dict) -> ValidationResult:
        """Check recorded position matches execution params"""
        issues = []
        
        # Verify margin collateral matches
        requested_margin = params.get("margin_usd", 0)
        actual_margin = position.get("margin_collateral", 0)
        
        if abs(requested_margin - actual_margin) > 1.0:  # >$1 difference
            issues.append(f"Margin mismatch: requested ${requested_margin:.2f}, got ${actual_margin:.2f}")
        
        # Verify leverage matches
        requested_leverage = params.get("leverage", 1)
        actual_leverage = position.get("leverage", 1)
        
        if requested_leverage != actual_leverage:
            issues.append(f"Leverage mismatch: requested {requested_leverage}x, got {actual_leverage}x")
        
        # Verify symbol matches
        if params.get("symbol") != position.get("symbol"):
            issues.append(f"Symbol mismatch: {params.get('symbol')} vs {position.get('symbol')}")
        
        if issues:
            return ValidationResult(
                passed=False,
                severity="CRITICAL",
                validator="ExecutionOutcomeChecker",
                message="Execution outcome doesn't match request",
                details={"issues": issues, "params": params, "position": position}
            )
        
        return ValidationResult(
            passed=True,
            severity="OK",
            validator="ExecutionOutcomeChecker",
            message="Execution outcome matches request"
        )


class FileIntegrityMonitor:
    """Ensures position_manager writes match execution params"""
    
    def validate(self, params: Dict) -> ValidationResult:
        """Load positions file and verify latest position matches params"""
        futures_file = "logs/positions_futures.json"
        
        if not os.path.exists(futures_file):
            return ValidationResult(
                passed=False,
                severity="WARNING",
                validator="FileIntegrityMonitor",
                message="Positions file not found",
                details={"file": futures_file}
            )
        
        try:
            with open(futures_file, 'r') as f:
                data = json.load(f)
            
            positions = data.get("open_positions", [])
            if not positions:
                return ValidationResult(
                    passed=False,
                    severity="WARNING",
                    validator="FileIntegrityMonitor",
                    message="No positions found in file after execution"
                )
            
            # Check latest position
            latest = positions[-1]
            margin = latest.get("margin_collateral", 0)
            
            # Verify it's within policy bounds
            if margin < MIN_POSITION_USD * 0.8:  # Allow 20% tolerance
                return ValidationResult(
                    passed=False,
                    severity="CRITICAL",
                    validator="FileIntegrityMonitor",
                    message=f"Latest position ${margin:.2f} significantly below policy minimum",
                    details={"margin": margin, "policy_min": MIN_POSITION_USD}
                )
            
            return ValidationResult(
                passed=True,
                severity="OK",
                validator="FileIntegrityMonitor",
                message=f"Position file integrity OK ({len(positions)} positions)"
            )
            
        except Exception as e:
            return ValidationResult(
                passed=False,
                severity="WARNING",
                validator="FileIntegrityMonitor",
                message=f"Failed to validate file: {str(e)}"
            )


class PolicyDeviationDetector:
    """Flags systematic deviations from policy (drift detection)"""
    
    def validate(self) -> ValidationResult:
        """Analyze recent positions for systematic undersizing"""
        futures_file = "logs/positions_futures.json"
        
        if not os.path.exists(futures_file):
            return ValidationResult(passed=True, severity="OK", validator="PolicyDeviationDetector", message="No data yet")
        
        try:
            with open(futures_file, 'r') as f:
                data = json.load(f)
            
            positions = data.get("open_positions", [])
            if len(positions) < 1:
                return ValidationResult(passed=True, severity="OK", validator="PolicyDeviationDetector", message="No open positions")
            
            # Only check CURRENT open positions, not historical
            # Use 'size' field (USD value) - this is the correct field for position sizing
            margins = []
            for p in positions:
                # Try 'size' first (correct field), then fallbacks
                size = p.get("size", p.get("size_usd", p.get("margin_usd", p.get("margin_collateral", 0))))
                if size and float(size) > 0:
                    margins.append(float(size))
            
            if not margins:
                return ValidationResult(passed=True, severity="OK", validator="PolicyDeviationDetector", message="No size data in open positions")
            
            import statistics
            median_margin = statistics.median(margins)
            
            # Check if median is significantly below policy minimum
            if median_margin < MIN_POSITION_USD * 0.5:  # <50% of minimum
                return ValidationResult(
                    passed=False,
                    severity="CRITICAL",
                    validator="PolicyDeviationDetector",
                    message=f"SYSTEMATIC UNDERSIZING: Median ${median_margin:.2f} is {((1 - median_margin/MIN_POSITION_USD)*100):.0f}% below policy",
                    details={
                        "median_margin": median_margin,
                        "policy_min": MIN_POSITION_USD,
                        "sample_size": len(positions),
                        "margins": margins,
                        "root_cause": "Likely USD-vs-quantity parameter mismatch or missing margin_usd"
                    }
                )
            elif median_margin < MIN_POSITION_USD * 0.8:  # <80% of minimum
                return ValidationResult(
                    passed=False,
                    severity="WARNING",
                    validator="PolicyDeviationDetector",
                    message=f"Drift detected: Median ${median_margin:.2f} below policy minimum",
                    details={"median_margin": median_margin, "policy_min": MIN_POSITION_USD}
                )
            
            return ValidationResult(
                passed=True,
                severity="OK",
                validator="PolicyDeviationDetector",
                message=f"No drift detected (median: ${median_margin:.2f})"
            )
            
        except Exception as e:
            return ValidationResult(
                passed=False,
                severity="WARNING",
                validator="PolicyDeviationDetector",
                message=f"Drift detection failed: {str(e)}"
            )


class QuestioningEngine:
    """Self-questioning prompts to catch logic errors"""
    
    def ask_pre_trade(self, signal: Dict, params: Dict) -> List[Tuple[str, bool, str]]:
        """
        Ask explicit questions before trade execution.
        Returns: List of (question, passed, explanation) tuples
        """
        checks = []
        
        # Q1: Does margin allocation honor policy?
        margin = params.get("margin_usd", 0)
        q1_pass = MIN_POSITION_USD <= margin <= MAX_POSITION_USD
        q1_exp = f"Margin ${margin:.2f} {'within' if q1_pass else 'OUTSIDE'} ${MIN_POSITION_USD}-${MAX_POSITION_USD} bounds"
        checks.append(("Does margin allocation honor policy?", q1_pass, q1_exp))
        
        # Q2: Are parameter types correct (USD vs quantity)?
        q2_pass = "margin_usd" in params and isinstance(params["margin_usd"], (int, float))
        q2_exp = f"margin_usd {'present' if q2_pass else 'MISSING'} with {'correct' if q2_pass else 'incorrect'} type"
        checks.append(("Are parameter types correct (USD vs quantity)?", q2_pass, q2_exp))
        
        # Q3: Will this trade be profitable after fees?
        expected_profit = params.get("expected_profit_usd", 0)
        q3_pass = expected_profit > margin * 0.002  # Profit > 0.2% of margin
        q3_exp = f"Expected profit ${expected_profit:.2f} {'exceeds' if q3_pass else 'below'} fee threshold"
        checks.append(("Will this trade be profitable after fees?", q3_pass, q3_exp))
        
        return checks
    
    def ask_post_trade(self, params: Dict, position: Dict) -> List[Tuple[str, bool, str]]:
        """
        Ask explicit questions after trade execution.
        Returns: List of (question, passed, explanation) tuples
        """
        checks = []
        
        # Q1: Does computed qty * price equal declared margin_usd?
        size = position.get("size", 0)
        price = position.get("entry_price", 0)
        leverage = position.get("leverage", 1)
        margin = position.get("margin_collateral", 0)
        
        expected_notional = margin * leverage
        actual_notional = size * price
        deviation = abs(expected_notional - actual_notional) / expected_notional if expected_notional > 0 else 0
        q1_pass = deviation < 0.10  # <10% deviation
        q1_exp = f"Notional: expected ${expected_notional:.2f}, actual ${actual_notional:.2f} ({deviation*100:.1f}% dev)"
        checks.append(("Does computed qty * price equal declared margin_usd?", q1_pass, q1_exp))
        
        # Q2: Do position files stay within $200-$3000?
        q2_pass = MIN_POSITION_USD <= margin <= MAX_POSITION_USD
        q2_exp = f"Position margin ${margin:.2f} {'within' if q2_pass else 'OUTSIDE'} policy bounds"
        checks.append(("Do position files stay within $200-$3000?", q2_pass, q2_exp))
        
        # Q3: Does execution match request?
        requested_margin = params.get("margin_usd", 0)
        q3_pass = abs(requested_margin - margin) < 1.0
        q3_exp = f"Requested ${requested_margin:.2f}, got ${margin:.2f}"
        checks.append(("Does execution match request?", q3_pass, q3_exp))
        
        return checks


class ValidationOrchestrator:
    """Main orchestrator for self-validation layer"""
    
    def __init__(self):
        self.schema_guard = SignalSchemaGuard()
        self.policy_guard = PolicyBoundsGuard()
        self.conversion_checker = ConversionIntentChecker()
        self.outcome_checker = ExecutionOutcomeChecker()
        self.file_monitor = FileIntegrityMonitor()
        self.drift_detector = PolicyDeviationDetector()
        self.questioning = QuestioningEngine()
    
    def validate_pre_execution(self, signal: Dict, params: Dict) -> Tuple[bool, List[ValidationResult]]:
        """
        Run all pre-execution validators.
        Returns: (all_passed, results)
        """
        results = [
            self.schema_guard.validate(signal, params),
            self.policy_guard.validate(signal, params)
        ]
        
        # Run questioning engine
        questions = self.questioning.ask_pre_trade(signal, params)
        for question, passed, explanation in questions:
            if not passed:
                results.append(ValidationResult(
                    passed=False,
                    severity="WARNING",
                    validator="QuestioningEngine",
                    message=f"Pre-trade check failed: {question}",
                    details={"question": question, "explanation": explanation}
                ))
        
        # Log results
        self._log_validation("pre_execution", results)
        
        # Block if any CRITICAL failures
        critical_failures = [r for r in results if not r.passed and r.severity == "CRITICAL"]
        all_passed = len(critical_failures) == 0
        
        return all_passed, results
    
    def validate_post_execution(self, params: Dict, position: Dict) -> Tuple[bool, List[ValidationResult]]:
        """
        Run all post-execution validators.
        Returns: (all_passed, results)
        """
        results = [
            self.conversion_checker.validate({}, params, position),
            self.outcome_checker.validate(params, position),
            self.file_monitor.validate(params),
            self.drift_detector.validate()
        ]
        
        # Run questioning engine
        questions = self.questioning.ask_post_trade(params, position)
        for question, passed, explanation in questions:
            if not passed:
                results.append(ValidationResult(
                    passed=False,
                    severity="WARNING",
                    validator="QuestioningEngine",
                    message=f"Post-trade check failed: {question}",
                    details={"question": question, "explanation": explanation}
                ))
        
        # Log results
        self._log_validation("post_execution", results)
        
        # Don't block on post-execution (already executed), but flag issues
        critical_failures = [r for r in results if not r.passed and r.severity == "CRITICAL"]
        all_passed = len(critical_failures) == 0
        
        return all_passed, results
    
    def _log_validation(self, phase: str, results: List[ValidationResult]):
        """Log validation results to file"""
        os.makedirs(os.path.dirname(VALIDATION_LOG), exist_ok=True)
        
        event = {
            "timestamp": time.time(),
            "phase": phase,
            "results": [r.to_dict() for r in results],
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r.passed),
                "failed": sum(1 for r in results if not r.passed),
                "critical": sum(1 for r in results if not r.passed and r.severity == "CRITICAL")
            }
        }
        
        with open(VALIDATION_LOG, 'a') as f:
            f.write(json.dumps(event) + "\n")
    
    def get_health_status(self) -> Dict:
        """Get current validation health status for Health Pulse integration"""
        # Run drift detection
        drift_result = self.drift_detector.validate()
        
        return {
            "healthy": drift_result.passed,
            "severity": drift_result.severity,
            "message": drift_result.message,
            "details": drift_result.details
        }


# Global singleton
_orchestrator = None

def get_validation_orchestrator() -> ValidationOrchestrator:
    """Get or create validation orchestrator singleton"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ValidationOrchestrator()
    return _orchestrator


def validate_pre_trade(signal: Dict, params: Dict) -> Tuple[bool, List[ValidationResult]]:
    """Convenience function for pre-execution validation"""
    orchestrator = get_validation_orchestrator()
    return orchestrator.validate_pre_execution(signal, params)


def validate_post_trade(params: Dict, position: Dict) -> Tuple[bool, List[ValidationResult]]:
    """Convenience function for post-execution validation"""
    orchestrator = get_validation_orchestrator()
    return orchestrator.validate_post_execution(params, position)
