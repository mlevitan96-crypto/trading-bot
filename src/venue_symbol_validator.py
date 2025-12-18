"""
Venue Symbol Validator - Validates symbols exist on exchange and have acceptable liquidity.

For each symbol in asset_universe.json:
- Verifies it exists on Kraken Futures (testnet)
- Validates Kraken symbol mapping exists
- Checks orderbook depth (non-empty, sufficient liquidity)
- Validates OHLCV data availability
- Calculates spread and depth metrics
- Auto-suppresses symbols that fail validation

State stored in: feature_store/venue_symbol_status.json
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict

from src.exchange_utils import normalize_to_kraken, KRAKEN_SYMBOL_MAP
from src.infrastructure.path_registry import PathRegistry


# Validation thresholds
# Note: Testnet may have very sparse orderbooks, so we use relaxed thresholds
import os
IS_TESTNET = os.getenv("KRAKEN_FUTURES_TESTNET", "false").lower() == "true"

if IS_TESTNET:
    MIN_ORDERBOOK_DEPTH_USD = 100.0  # Lower threshold for testnet
    MAX_SPREAD_PCT = 10.0  # Much higher spread tolerance for testnet (10% vs 0.5%)
    MIN_OHLCV_CANDLES = 5  # Fewer candles needed for testnet
else:
    MIN_ORDERBOOK_DEPTH_USD = 1000.0  # Minimum $1000 orderbook depth (production)
    MAX_SPREAD_PCT = 0.5  # Maximum 0.5% bid-ask spread (production)
    MIN_OHLCV_CANDLES = 10  # Minimum candles required for OHLCV validation (production)

# State file paths
STATUS_FILE = PathRegistry.FEATURE_STORE_DIR / "venue_symbol_status.json"
ASSET_UNIVERSE_FILE = PathRegistry.CONFIG_DIR / "asset_universe.json"


class VenueSymbolValidator:
    """
    Validates symbols exist on exchange and meet liquidity requirements.
    """
    
    def __init__(self, exchange_gateway=None):
        """
        Initialize validator.
        
        Args:
            exchange_gateway: ExchangeGateway instance (will create if None)
        """
        if exchange_gateway is None:
            from src.exchange_gateway import ExchangeGateway
            self.gateway = ExchangeGateway()
        else:
            self.gateway = exchange_gateway
        
        self.exchange = os.getenv("EXCHANGE", "blofin").lower()
        self.status_file = STATUS_FILE
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
    def load_asset_universe(self) -> List[Dict[str, Any]]:
        """Load asset universe from config."""
        try:
            with open(ASSET_UNIVERSE_FILE, 'r') as f:
                config = json.load(f)
            return config.get("asset_universe", [])
        except Exception as e:
            print(f"⚠️ [VALIDATOR] Failed to load asset_universe.json: {e}")
            return []
    
    def load_validation_status(self) -> Dict[str, Any]:
        """Load current validation status."""
        if self.status_file.exists():
            try:
                with open(self.status_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ [VALIDATOR] Failed to load status file: {e}")
                return {}
        return {
            "venue": self.exchange,
            "last_validation": None,
            "symbols": {}
        }
    
    def save_validation_status(self, status: Dict[str, Any]):
        """Save validation status to file."""
        status["last_validation"] = datetime.utcnow().isoformat() + "Z"
        try:
            with open(self.status_file, 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            print(f"❌ [VALIDATOR] Failed to save status file: {e}")
    
    def validate_symbol_mapping(self, symbol: str) -> tuple[bool, Optional[str]]:
        """
        Validate symbol has a Kraken mapping.
        
        Returns:
            (is_valid, error_message)
        """
        if symbol not in KRAKEN_SYMBOL_MAP:
            return False, f"Symbol {symbol} not in KRAKEN_SYMBOL_MAP"
        
        kraken_symbol = normalize_to_kraken(symbol)
        if not kraken_symbol:
            return False, f"Failed to normalize {symbol} to Kraken format"
        
        return True, None
    
    def validate_mark_price(self, symbol: str) -> tuple[bool, Optional[str], Optional[float]]:
        """
        Validate symbol exists by fetching mark price.
        
        Returns:
            (is_valid, error_message, price)
        """
        try:
            price = self.gateway.get_price(symbol, venue="futures")
            if price and price > 0:
                return True, None, price
            return False, f"Invalid price returned: {price}", None
        except Exception as e:
            return False, f"Mark price fetch failed: {str(e)}", None
    
    def validate_orderbook(self, symbol: str) -> tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Validate orderbook has sufficient depth and acceptable spread.
        
        Returns:
            (is_valid, error_message, metrics_dict)
        """
        try:
            orderbook = self.gateway.get_orderbook(symbol, venue="futures", depth=10)
            
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            if not bids or not asks:
                return False, "Empty orderbook (no bids/asks)", {}
            
            # Get best bid/ask
            best_bid = float(bids[0][0]) if bids else 0
            best_ask = float(asks[0][0]) if asks else 0
            
            if best_bid <= 0 or best_ask <= 0:
                return False, f"Invalid bid/ask prices: bid={best_bid}, ask={best_ask}", {}
            
            if best_ask <= best_bid:
                return False, f"Invalid spread: ask {best_ask} <= bid {best_bid}", {}
            
            # Calculate spread
            mid_price = (best_bid + best_ask) / 2
            spread_pct = ((best_ask - best_bid) / mid_price) * 100
            
            # Calculate depth (sum of top 5 levels)
            # For Kraken perpetual futures, orderbook quantities are in contracts
            # Each contract is worth $1 (contract_size = 1.0), so depth = price * qty
            bid_depth = sum(float(bid[0]) * float(bid[1]) for bid in bids[:5])
            ask_depth = sum(float(ask[0]) * float(ask[1]) for ask in asks[:5])
            total_depth_usd = (bid_depth + ask_depth) / 2  # Average of bid/ask depth
            
            # Debug: Log actual values for testnet debugging
            if IS_TESTNET and spread_pct > 50:  # Very high spread - log for debugging
                print(f"   ⚠️ [DEBUG] {symbol}: bid={best_bid:.2f}, ask={best_ask:.2f}, spread={spread_pct:.1f}%")
                print(f"   ⚠️ [DEBUG] Sample bids: {bids[:2]}, Sample asks: {asks[:2]}")
            
            metrics = {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid_price": mid_price,
                "spread_pct": spread_pct,
                "bid_depth_usd": bid_depth,
                "ask_depth_usd": ask_depth,
                "total_depth_usd": total_depth_usd,
                "num_bid_levels": len(bids),
                "num_ask_levels": len(asks)
            }
            
            # Check thresholds
            errors = []
            if spread_pct > MAX_SPREAD_PCT:
                errors.append(f"Spread {spread_pct:.3f}% exceeds max {MAX_SPREAD_PCT}%")
            
            if total_depth_usd < MIN_ORDERBOOK_DEPTH_USD:
                errors.append(f"Depth ${total_depth_usd:.0f} below minimum ${MIN_ORDERBOOK_DEPTH_USD}")
            
            if errors:
                return False, "; ".join(errors), metrics
            
            return True, None, metrics
            
        except Exception as e:
            return False, f"Orderbook validation failed: {str(e)}", {}
    
    def validate_ohlcv(self, symbol: str) -> tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Validate OHLCV data is available and valid.
        
        Returns:
            (is_valid, error_message, metrics_dict)
        """
        try:
            df = self.gateway.fetch_ohlcv(symbol, timeframe="1m", limit=MIN_OHLCV_CANDLES, venue="futures")
            
            if df is None or df.empty:
                return False, "OHLCV data is empty", {}
            
            if len(df) < MIN_OHLCV_CANDLES:
                return False, f"Only {len(df)} candles, need at least {MIN_OHLCV_CANDLES}", {}
            
            # Check for required columns
            required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                return False, f"Missing columns: {missing_cols}", {}
            
            # Check for valid data (non-null, positive prices)
            latest_close = float(df["close"].iloc[-1])
            if latest_close <= 0:
                return False, f"Invalid close price: {latest_close}", {}
            
            metrics = {
                "num_candles": len(df),
                "latest_close": latest_close,
                "latest_timestamp": str(df["timestamp"].iloc[-1]),
                "avg_volume": float(df["volume"].mean()) if "volume" in df.columns else 0
            }
            
            return True, None, metrics
            
        except Exception as e:
            return False, f"OHLCV validation failed: {str(e)}", {}
    
    def validate_symbol(self, symbol: str) -> Dict[str, Any]:
        """
        Perform complete validation for a single symbol.
        
        Returns:
            Validation result dict with all checks
        """
        result = {
            "symbol": symbol,
            "kraken_symbol": normalize_to_kraken(symbol),
            "valid": False,
            "checks": {},
            "errors": [],
            "suppressed": False,
            "validation_timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        # Check 1: Symbol mapping
        mapping_valid, mapping_error = self.validate_symbol_mapping(symbol)
        result["checks"]["symbol_mapping"] = {
            "valid": mapping_valid,
            "error": mapping_error
        }
        if not mapping_valid:
            result["errors"].append(f"Mapping: {mapping_error}")
            result["suppressed"] = True
            return result
        
        # Check 2: Mark price (existence check)
        price_valid, price_error, price = self.validate_mark_price(symbol)
        result["checks"]["mark_price"] = {
            "valid": price_valid,
            "error": price_error,
            "price": price
        }
        if not price_valid:
            result["errors"].append(f"Price: {price_error}")
            result["suppressed"] = True
            return result
        
        # Check 3: Orderbook
        ob_valid, ob_error, ob_metrics = self.validate_orderbook(symbol)
        result["checks"]["orderbook"] = {
            "valid": ob_valid,
            "error": ob_error,
            "metrics": ob_metrics
        }
        if not ob_valid:
            result["errors"].append(f"Orderbook: {ob_error}")
            result["suppressed"] = True
        
        # Check 4: OHLCV
        ohlcv_valid, ohlcv_error, ohlcv_metrics = self.validate_ohlcv(symbol)
        result["checks"]["ohlcv"] = {
            "valid": ohlcv_valid,
            "error": ohlcv_error,
            "metrics": ohlcv_metrics
        }
        if not ohlcv_valid:
            result["errors"].append(f"OHLCV: {ohlcv_error}")
            result["suppressed"] = True
        
        # Overall validation
        result["valid"] = mapping_valid and price_valid and ob_valid and ohlcv_valid
        
        return result
    
    def validate_all_symbols(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Validate all symbols in asset universe.
        
        Args:
            symbols: Optional list of symbols to validate (defaults to all enabled)
        
        Returns:
            Complete validation results
        """
        print("\n" + "="*70)
        print("🔍 VENUE SYMBOL VALIDATION")
        print("="*70)
        print(f"📍 Exchange: {self.exchange.upper()}")
        print(f"🔗 Gateway: {type(self.gateway).__name__}")
        print(f"🌐 Futures Client: {type(self.gateway.fut).__name__}")
        print("-"*70)
        
        if symbols is None:
            assets = self.load_asset_universe()
            symbols = [a["symbol"] for a in assets if a.get("enabled", True)]
        
        print(f"📋 Validating {len(symbols)} symbols...\n")
        
        results = {
            "venue": self.exchange,
            "validation_timestamp": datetime.utcnow().isoformat() + "Z",
            "symbols": {},
            "summary": {
                "total": len(symbols),
                "valid": 0,
                "invalid": 0,
                "suppressed": 0
            }
        }
        
        for i, symbol in enumerate(symbols, 1):
            print(f"[{i}/{len(symbols)}] Validating {symbol}...", end=" ", flush=True)
            
            try:
                result = self.validate_symbol(symbol)
                results["symbols"][symbol] = result
                
                if result["valid"]:
                    print("✅ VALID")
                    results["summary"]["valid"] += 1
                else:
                    print(f"❌ INVALID: {', '.join(result['errors'][:2])}")
                    results["summary"]["invalid"] += 1
                    if result["suppressed"]:
                        results["summary"]["suppressed"] += 1
                
                # Rate limiting (be nice to API)
                if i < len(symbols):
                    time.sleep(0.5)
                    
            except Exception as e:
                print(f"❌ ERROR: {str(e)}")
                results["symbols"][symbol] = {
                    "symbol": symbol,
                    "valid": False,
                    "errors": [f"Validation exception: {str(e)}"],
                    "suppressed": True
                }
                results["summary"]["invalid"] += 1
                results["summary"]["suppressed"] += 1
        
        # Save results
        status = self.load_validation_status()
        status["symbols"] = results["symbols"]
        status["last_validation"] = results["validation_timestamp"]
        status["venue"] = self.exchange
        self.save_validation_status(status)
        
        # Print summary
        print("\n" + "="*70)
        print("📊 VALIDATION SUMMARY")
        print("="*70)
        print(f"✅ Valid: {results['summary']['valid']}")
        print(f"❌ Invalid: {results['summary']['invalid']}")
        print(f"🚫 Suppressed: {results['summary']['suppressed']}")
        print("-"*70)
        
        # List suppressed symbols
        suppressed = [s for s, r in results["symbols"].items() if r.get("suppressed")]
        if suppressed:
            print(f"🚫 Suppressed symbols ({len(suppressed)}): {', '.join(suppressed)}")
            for symbol in suppressed:
                errors = results["symbols"][symbol].get("errors", [])
                print(f"   • {symbol}: {errors[0] if errors else 'Unknown error'}")
        else:
            print("✅ No symbols suppressed")
        
        print("="*70 + "\n")
        
        return results
    
    def get_suppressed_symbols(self) -> List[str]:
        """Get list of currently suppressed symbols."""
        status = self.load_validation_status()
        suppressed = []
        
        for symbol, data in status.get("symbols", {}).items():
            if data.get("suppressed", False):
                suppressed.append(symbol)
        
        return suppressed
    
    def update_asset_universe_enabled_flags(self, validation_results: Dict[str, Any]):
        """
        Update asset_universe.json to disable symbols that failed validation.
        
        Note: This modifies the config file - use with caution!
        """
        suppressed = self.get_suppressed_symbols()
        if not suppressed:
            print("✅ No symbols to suppress - all passed validation")
            return
        
        try:
            with open(ASSET_UNIVERSE_FILE, 'r') as f:
                config = json.load(f)
            
            updated = False
            for asset in config.get("asset_universe", []):
                symbol = asset.get("symbol")
                if symbol in suppressed:
                    if asset.get("enabled", True):
                        asset["enabled"] = False
                        asset["disabled_reason"] = "Failed venue validation"
                        asset["disabled_date"] = datetime.utcnow().isoformat() + "Z"
                        updated = True
                        print(f"🚫 Disabled {symbol} in asset_universe.json")
            
            if updated:
                # Backup original
                backup_file = ASSET_UNIVERSE_FILE.with_suffix('.json.backup')
                with open(backup_file, 'w') as f:
                    json.dump(config, f, indent=2)
                
                # Write updated
                with open(ASSET_UNIVERSE_FILE, 'w') as f:
                    json.dump(config, f, indent=2)
                
                print(f"💾 Updated asset_universe.json (backup saved to {backup_file.name})")
            else:
                print("ℹ️ No changes needed - symbols already disabled")
                
        except Exception as e:
            print(f"⚠️ Failed to update asset_universe.json: {e}")


def validate_venue_symbols(exchange_gateway=None, update_config: bool = False) -> Dict[str, Any]:
    """
    Main entry point for symbol validation.
    
    Args:
        exchange_gateway: Optional ExchangeGateway instance
        update_config: If True, updates asset_universe.json to disable failed symbols
    
    Returns:
        Validation results dict
    """
    validator = VenueSymbolValidator(exchange_gateway)
    results = validator.validate_all_symbols()
    
    if update_config:
        validator.update_asset_universe_enabled_flags(results)
    
    return results


if __name__ == "__main__":
    # Test/run validation
    results = validate_venue_symbols(update_config=False)
    print("\n✅ Validation complete!")
    print(f"📄 Status saved to: {STATUS_FILE}")
