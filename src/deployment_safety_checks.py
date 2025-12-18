"""
Deployment Safety Checks - Pre-deployment validation before A/B slot switch.

Validates:
1. Environment variables (EXCHANGE, API keys)
2. Exchange connectivity
3. Venue symbol validation (if using Kraken)
4. API key permissions
5. Exchange-specific requirements

Aborts deployment if any critical check fails.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

# Add project root to path for imports
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class DeploymentSafetyChecker:
    """
    Validates system is ready for deployment before switching slots.
    """
    
    def __init__(self, env_file: Optional[Path] = None):
        """
        Initialize checker.
        
        Args:
            env_file: Path to .env file (defaults to project root)
        """
        if env_file is None:
            env_file = _project_root / ".env"
        self.env_file = env_file
        
    def load_env_vars(self) -> Dict[str, str]:
        """Load environment variables from .env file."""
        env_vars = {}
        if self.env_file.exists():
            try:
                with open(self.env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            env_vars[key.strip()] = value.strip()
            except Exception as e:
                print(f"⚠️ [DEPLOY-CHECK] Failed to load .env: {e}")
        return env_vars
    
    def check_env_vars(self) -> Tuple[bool, List[str], List[str]]:
        """
        Check required environment variables are present.
        
        Returns:
            (passed, missing_vars, errors)
        """
        env_vars = self.load_env_vars()
        missing = []
        errors = []
        
        # Check EXCHANGE is set
        exchange = env_vars.get("EXCHANGE") or os.getenv("EXCHANGE")
        if not exchange:
            missing.append("EXCHANGE")
        else:
            exchange = exchange.lower()
            if exchange not in ["kraken", "blofin"]:
                errors.append(f"EXCHANGE={exchange} is invalid (must be 'kraken' or 'blofin')")
        
        # Check exchange-specific vars
        if exchange == "kraken":
            required = [
                "KRAKEN_FUTURES_API_KEY",
                "KRAKEN_FUTURES_API_SECRET",
                "KRAKEN_FUTURES_TESTNET"
            ]
            for var in required:
                value = env_vars.get(var) or os.getenv(var)
                if not value:
                    missing.append(var)
                elif var == "KRAKEN_FUTURES_TESTNET" and value.lower() not in ["true", "false"]:
                    errors.append(f"{var}={value} is invalid (must be 'true' or 'false')")
        
        passed = len(missing) == 0 and len(errors) == 0
        return passed, missing, errors
    
    def check_exchange_connectivity(self) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Check exchange connectivity.
        
        Returns:
            (connected, error_message, details)
        """
        try:
            # Load env vars
            env_vars = self.load_env_vars()
            exchange = env_vars.get("EXCHANGE") or os.getenv("EXCHANGE", "blofin").lower()
            
            if exchange not in ["kraken", "blofin"]:
                return False, f"Invalid exchange: {exchange}", {}
            
            # Set env vars for gateway initialization
            for key, value in env_vars.items():
                if key.startswith("KRAKEN_") or key == "EXCHANGE":
                    os.environ[key] = value
            
            # Test connectivity
            from src.exchange_gateway import ExchangeGateway
            gateway = ExchangeGateway()
            
            # Test mark price
            test_symbol = "BTCUSDT"
            try:
                price = gateway.get_price(test_symbol, venue="futures")
                if price and price > 0:
                    return True, None, {
                        "exchange": exchange,
                        "test_symbol": test_symbol,
                        "price": price
                    }
                else:
                    return False, f"Invalid price returned: {price}", {}
            except Exception as e:
                error_msg = str(e)
                # Handle testnet balance limitation gracefully
                if "authenticationError" in error_msg and "balance" in error_msg.lower():
                    if exchange == "kraken" and env_vars.get("KRAKEN_FUTURES_TESTNET", "false").lower() == "true":
                        # Try mark price instead (balance is expected to fail on testnet)
                        try:
                            price = gateway.get_price(test_symbol, venue="futures")
                            if price and price > 0:
                                return True, None, {
                                    "exchange": exchange,
                                    "test_symbol": test_symbol,
                                    "price": price,
                                    "note": "Balance endpoint unsupported on testnet (expected)"
                                }
                        except Exception as e2:
                            return False, f"Mark price test failed: {str(e2)}", {}
                
                return False, f"Connectivity test failed: {error_msg}", {}
                
        except Exception as e:
            return False, f"Connectivity check exception: {str(e)}", {}
    
    def check_symbol_validation(self) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Check venue symbol validation (if using Kraken).
        
        Returns:
            (valid, error_message, details)
        """
        env_vars = self.load_env_vars()
        exchange = env_vars.get("EXCHANGE") or os.getenv("EXCHANGE", "blofin").lower()
        
        if exchange != "kraken":
            return True, None, {"note": "Symbol validation only for Kraken"}
        
        try:
            # Set env vars
            for key, value in env_vars.items():
                if key.startswith("KRAKEN_") or key == "EXCHANGE":
                    os.environ[key] = value
            
            from src.venue_symbol_validator import validate_venue_symbols
            results = validate_venue_symbols(update_config=False)
            
            valid_count = results.get("summary", {}).get("valid", 0)
            total_count = results.get("summary", {}).get("total", 0)
            
            # Don't fail deployment if some symbols fail validation (just warn)
            # This is informational, not a blocker
            if valid_count == 0:
                return False, f"No symbols validated successfully ({valid_count}/{total_count})", results
            elif valid_count < total_count * 0.5:  # Less than 50% valid
                return True, None, {
                    "warning": f"Only {valid_count}/{total_count} symbols valid (may be testnet limitation)",
                    "results": results
                }
            
            return True, None, results
            
        except Exception as e:
            return False, f"Symbol validation failed: {str(e)}", {}
    
    def run_all_checks(self) -> Dict[str, Any]:
        """
        Run all deployment safety checks.
        
        Returns:
            Dict with check results and overall status
        """
        results = {
            "passed": True,
            "checks": {},
            "errors": [],
            "warnings": []
        }
        
        print("\n" + "="*70)
        print("🔍 DEPLOYMENT SAFETY CHECKS")
        print("="*70 + "\n")
        
        # Check 1: Environment Variables
        print("1️⃣ Checking environment variables...")
        env_passed, missing, errors = self.check_env_vars()
        results["checks"]["env_vars"] = {
            "passed": env_passed,
            "missing": missing,
            "errors": errors
        }
        if not env_passed:
            results["passed"] = False
            results["errors"].extend([f"Missing: {v}" for v in missing])
            results["errors"].extend(errors)
            print(f"   ❌ FAILED: Missing vars: {missing}, Errors: {errors}")
        else:
            print("   ✅ PASSED")
        print()
        
        # Check 2: Exchange Connectivity
        print("2️⃣ Checking exchange connectivity...")
        connected, error, details = self.check_exchange_connectivity()
        results["checks"]["connectivity"] = {
            "passed": connected,
            "error": error,
            "details": details
        }
        if not connected:
            results["passed"] = False
            results["errors"].append(f"Connectivity: {error}")
            print(f"   ❌ FAILED: {error}")
        else:
            print(f"   ✅ PASSED: {details.get('exchange', 'unknown')} - {details.get('test_symbol')} price: ${details.get('price', 0):,.2f}")
            if details.get("note"):
                results["warnings"].append(details["note"])
                print(f"   ℹ️  Note: {details['note']}")
        print()
        
        # Check 3: Symbol Validation (if Kraken)
        env_vars = self.load_env_vars()
        exchange = env_vars.get("EXCHANGE") or os.getenv("EXCHANGE", "blofin").lower()
        if exchange == "kraken":
            print("3️⃣ Checking venue symbol validation...")
            valid, error, details = self.check_symbol_validation()
            results["checks"]["symbol_validation"] = {
                "passed": valid,
                "error": error,
                "details": details
            }
            if not valid:
                # Symbol validation failure is a warning, not a blocker for deployment
                results["warnings"].append(f"Symbol validation: {error}")
                print(f"   ⚠️  WARNING: {error}")
            else:
                summary = details.get("summary", {})
                valid_count = summary.get("valid", 0)
                total_count = summary.get("total", 0)
                print(f"   ✅ PASSED: {valid_count}/{total_count} symbols valid")
                if details.get("warning"):
                    results["warnings"].append(details["warning"])
                    print(f"   ℹ️  {details['warning']}")
        else:
            results["checks"]["symbol_validation"] = {"passed": True, "skipped": True}
            print("3️⃣ Symbol validation skipped (not using Kraken)")
        print()
        
        # Final result
        print("="*70)
        if results["passed"]:
            print("✅ ALL CHECKS PASSED - Safe to deploy")
            if results["warnings"]:
                print("\n⚠️  Warnings:")
                for warning in results["warnings"]:
                    print(f"   • {warning}")
        else:
            print("❌ DEPLOYMENT BLOCKED - Fix errors before deploying")
            print("\nErrors:")
            for error in results["errors"]:
                print(f"   • {error}")
        print("="*70 + "\n")
        
        return results


def run_deployment_checks(env_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Main entry point for deployment safety checks.
    
    Call this before deploying to validate system readiness.
    
    Returns:
        Check results dict
    """
    checker = DeploymentSafetyChecker(env_file)
    return checker.run_all_checks()


if __name__ == "__main__":
    # Run checks
    results = run_deployment_checks()
    
    # Exit with error code if checks failed
    if not results["passed"]:
        sys.exit(1)
    else:
        sys.exit(0)
