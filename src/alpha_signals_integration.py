# src/alpha_signals_integration.py
#
# Integration module for OFI and Micro-Arb signals (Phases 274-275)
# Bridges new alpha sources into the main trading loop
#
# UPDATED: Now applies intelligence-based inversion from promoted rules
# Based on analysis of 630 enriched decisions showing signals are systematically inverted
#
# DAY 2 PATCH: Added null safety to prevent overnight crashes when market data is sparse

import time
from typing import Dict, Any, Optional, Tuple


def safe_float(value, default=0.0):
    """
    Null-safe float conversion to prevent crashes from None/invalid values.
    This is critical for overnight operation when market data may be sparse.
    """
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default
from src.intelligence_inversion import apply_intelligence_inversion, get_inversion_stats
from src.phase_271_280 import (
    generate_alpha_signals,
    regime_entry_filter,
    tune_offset_and_venue,
    evaluate_exit,
    log_trade_execution,
    get_expectancy_metrics,
    get_leak_lists
)


class AlphaSignalsEngine:
    """
    Centralized engine for OFI and micro-arb signal generation and filtering.
    
    Integrates Phases 274-275 (OFI, micro-arb) into the live trading system.
    """
    
    def __init__(self):
        self.last_ofi_signals = {}
        self.last_arb_signals = {}
        self.signal_count = 0
        
    def fetch_orderbook_depth(self, exchange_gateway, symbol: str, venue: str = "futures", max_retries: int = 3) -> Tuple[float, float, float, float]:
        """
        Fetch L5 (Level 5) Depth for High-Fidelity OFI.
        Summing levels 1-5 removes 'flickering' noise from HFT algos.
        
        Implements exponential backoff retry mechanism. Returns (None, None, None, None)
        on data outage to signal that trading should be paused for this symbol.
        
        Returns: (bid_size, ask_size, best_bid_price, best_ask_price) or (None, None, None, None) on outage
        """
        import time
        
        last_error = None
        for attempt in range(max_retries):
            try:
                # Connect to client
                from src.blofin_futures_client import BlofinFuturesClient
                client = BlofinFuturesClient()
                orderbook = client.get_orderbook(symbol, depth=10)
                
                if not orderbook:
                    raise ValueError("Empty orderbook response")
                
                # L5 Aggregation Logic
                bids = orderbook.get("bids", [])
                asks = orderbook.get("asks", [])
                
                if len(bids) < 1 or len(asks) < 1:
                    raise ValueError(f"Insufficient orderbook levels: {len(bids)} bids, {len(asks)} asks")
                
                # Sum volume of top 5 levels
                bid_size = sum([float(level[1]) for level in bids[:5]])
                ask_size = sum([float(level[1]) for level in asks[:5]])
                
                # Get Best Price for Reference
                best_bid = float(bids[0][0]) if bids else 0.0
                best_ask = float(asks[0][0]) if asks else 0.0
                
                if best_bid <= 0 or best_ask <= 0:
                    raise ValueError(f"Invalid prices: bid={best_bid}, ask={best_ask}")
                
                return bid_size, ask_size, best_bid, best_ask
                
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    backoff = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                    print(f"⚠️ [ALPHA] L5 Depth fetch retry {attempt+1}/{max_retries} for {symbol}: {e}")
                    time.sleep(backoff)
        
        # All retries failed - log DATA OUTAGE and return None markers
        print(f"🚨 [ALPHA] DATA OUTAGE for {symbol} after {max_retries} retries: {last_error}")
        return None, None, None, None
    
    def generate_ofi_and_arb_signals(
        self,
        symbol: str,
        exchange_gateway,
        venue: str = "futures",
        cross_venue_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Generate OFI and micro-arb signals for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            exchange_gateway: Exchange gateway for data access
            venue: Primary venue (default: "futures")
            cross_venue_price: Price from alternate venue for arb detection
            
        Returns:
            {
                "ofi": {"symbol": str, "ofi": float, "signal": str},
                "arb": {"symbol": str, "arb_opportunity": bool, "spread": float},
                "combined_signal": str,  # "LONG", "SHORT", "HOLD", or "DATA_OUTAGE"
                "data_available": bool  # False if orderbook data unavailable
            }
        """
        # Fetch orderbook depth
        bid_size, ask_size, bid_price, ask_price = self.fetch_orderbook_depth(
            exchange_gateway, symbol, venue
        )
        
        # Check for DATA OUTAGE - do not trade on fake data
        if bid_size is None or ask_size is None:
            return {
                "ofi": {"symbol": symbol, "ofi": 0.0, "signal": "DATA_OUTAGE"},
                "arb": {"symbol": symbol, "arb_opportunity": False, "spread": 0.0},
                "combined_signal": "DATA_OUTAGE",
                "data_available": False,
                "reason": "Orderbook data unavailable after retries"
            }
        
        # Get current price
        try:
            current_price = exchange_gateway.get_price(symbol, venue=venue)
        except:
            current_price = (bid_price + ask_price) / 2 if bid_price and ask_price else 0
        
        # Cross-venue arbitrage requires real secondary venue data
        # Without real cross-venue data, disable arb detection (was causing phantom trades)
        arb_disabled = False
        if cross_venue_price is None:
            cross_venue_price = current_price  # Same price = no arb opportunity
            arb_disabled = True  # Flag to suppress arb signals
        
        # Generate OFI and arb signals
        signals = generate_alpha_signals(
            symbol=symbol,
            bid_size=bid_size,
            ask_size=ask_size,
            price1=current_price,
            price2=cross_venue_price
        )
        
        # Extract OFI value with null safety
        ofi_value = safe_float(signals.get("ofi", {}).get("ofi"), 0.0)
        
        # Interpret OFI signal
        ofi_signal = "HOLD"
        if ofi_value > 0.10:  # >10% buy pressure
            ofi_signal = "LONG"
        elif ofi_value < -0.10:  # >10% sell pressure
            ofi_signal = "SHORT"
        
        signals["ofi"]["signal"] = ofi_signal
        
        # Combined signal (OFI takes priority, arb is confirmatory)
        combined_signal = "HOLD"
        
        # Disable phantom arb signals if we don't have real cross-venue data
        has_real_arb = signals["arb"]["arb_opportunity"] and not arb_disabled
        
        # Strong OFI signal
        if abs(ofi_value) > 0.15:  # >15% imbalance
            combined_signal = ofi_signal
        # Moderate OFI + real arb confirmation (not phantom)
        elif abs(ofi_value) > 0.10 and has_real_arb:
            combined_signal = ofi_signal
        # Pure arb only with real cross-venue data
        elif has_real_arb:
            # Arb can work both directions, use OFI for direction
            combined_signal = ofi_signal if abs(ofi_value) > 0.05 else "HOLD"
        
        signals["combined_signal"] = combined_signal
        
        # Cache signals
        self.last_ofi_signals[symbol] = signals.get("ofi", {})
        self.last_arb_signals[symbol] = signals.get("arb", {})
        self.signal_count += 1
        
        # Return null-safe result (Day 2 Patch)
        return {
            "ofi": {
                "symbol": symbol,
                "ofi": safe_float(signals.get("ofi", {}).get("ofi"), 0.0),
                "signal": signals.get("ofi", {}).get("signal", "HOLD")
            },
            "arb": {
                "symbol": symbol,
                "arb_opportunity": signals.get("arb", {}).get("arb_opportunity", False),
                "spread": safe_float(signals.get("arb", {}).get("spread"), 0.0)
            },
            "combined_signal": signals.get("combined_signal", "HOLD"),
            "data_available": True
        }
    
    def should_enter_trade(
        self,
        regime: str,
        volatility: float,
        spread_bp: float,
        depth_units: int,
        ofi_signal: str = "HOLD"
    ) -> Tuple[bool, str]:
        """
        Apply regime-aware entry filter (Phase 276).
        
        Returns: (should_enter, reason)
        """
        # Check OFI signal strength first
        if ofi_signal == "HOLD":
            return False, "ofi_hold"
        
        # Apply regime-aware microstructure filter
        passed = regime_entry_filter(
            regime=regime,
            volatility=volatility,
            spread_bp=spread_bp,
            depth_units=depth_units,
            vol_threshold=0.02,     # 2% max volatility
            spread_cap_bp=8.0,      # 8bp max spread
            min_depth=3             # 3 levels min depth
        )
        
        if not passed:
            return False, "microstructure_filter"
        
        return True, "passed"
    
    def get_execution_tuning(
        self,
        symbol: str,
        recent_slippage_bp: float = 5.0,
        maker_fill_rate: float = 0.5
    ) -> Dict[str, Any]:
        """
        Get execution tuning parameters (Phase 277).
        
        Returns: {"offset_bp": float, "prefer_maker": bool}
        """
        return tune_offset_and_venue(
            symbol=symbol,
            recent_slippage_bp=recent_slippage_bp,
            maker_fill_rate=maker_fill_rate,
            base_offset_bp=5.0
        )
    
    def should_exit_position(
        self,
        entry_ts: int,
        current_pnl: float,
        regime: str = "momentum"
    ) -> Tuple[bool, str]:
        """
        Check if should exit position (Phase 278).
        
        Returns: (should_exit, reason)
        """
        max_hold = 600 if regime == "momentum" else 480  # 10 min vs 8 min
        
        should_exit = evaluate_exit(
            entry_ts=entry_ts,
            pnl=current_pnl,
            regime=regime,
            max_hold_sec=max_hold,
            stop_loss_bp=10.0  # -10bp stop
        )
        
        if should_exit:
            # Determine reason
            held_time = time.time() - entry_ts
            if current_pnl < -0.001:  # -10bp = -0.1% = -0.001
                return True, "stop_loss"
            elif held_time > max_hold:
                return True, "time_based_exit"
            else:
                return True, "exit_logic"
        
        return False, "hold"
    
    def log_trade_forensics(
        self,
        symbol: str,
        pnl: float,
        fees: float,
        slippage: float,
        spread: float,
        latency: int,
        venue: str,
        maker: bool,
        entry_ts: int,
        exit_ts: int,
        direction: str,
        strategy: str
    ):
        """Log trade forensics (Phase 271)."""
        log_trade_execution(
            symbol=symbol,
            pnl=pnl,
            fees=fees,
            slippage=slippage,
            spread=spread,
            latency=latency,
            venue=venue,
            maker=maker,
            entry_ts=entry_ts,
            exit_ts=exit_ts,
            direction=direction,
            reason=strategy
        )
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get current system performance metrics.
        
        Returns: {
            "expectancy": {...},
            "leaks": {...},
            "signal_count": int
        }
        """
        return {
            "expectancy": get_expectancy_metrics(window=500),
            "leaks": get_leak_lists(window=1000),
            "signal_count": self.signal_count
        }


# Singleton instance
_alpha_engine = None

def get_alpha_signals_engine() -> AlphaSignalsEngine:
    """Get singleton alpha signals engine instance."""
    global _alpha_engine
    if _alpha_engine is None:
        _alpha_engine = AlphaSignalsEngine()
    return _alpha_engine


# Convenience functions for easy integration
def generate_live_alpha_signals(symbol: str, exchange_gateway=None, regime: str = "momentum") -> Dict[str, Any]:
    """
    Generate OFI and micro-arb signals for live trading.
    
    Returns: {
        "symbol": str,
        "ofi_signal": str,  # "LONG", "SHORT", "HOLD"
        "ofi_value": float,
        "arb_opportunity": bool,
        "combined_signal": str,
        "should_enter": bool,
        "entry_reason": str
    }
    """
    # Check pair overrides first - respect disabled symbols
    from src.pair_overrides_loader import get_pair_override
    enabled = get_pair_override(symbol, "enabled", default=True)
    preferred_strategies = get_pair_override(symbol, "preferred_strategies", default=None)
    
    # If symbol is explicitly disabled, return HOLD signal immediately
    if enabled is False or (preferred_strategies is not None and len(preferred_strategies) == 0):
        return {
            "symbol": symbol,
            "ofi_signal": "HOLD",
            "ofi_value": 0.0,
            "arb_opportunity": False,
            "combined_signal": "HOLD",
            "should_enter": False,
            "entry_reason": f"symbol_disabled_by_override"
        }
    
    # Create fresh gateway instance to avoid module caching issues
    if exchange_gateway is None:
        import importlib
        import src.exchange_gateway
        importlib.reload(src.exchange_gateway)
        from src.exchange_gateway import ExchangeGateway
        exchange_gateway = ExchangeGateway()
    
    engine = get_alpha_signals_engine()
    
    # Generate signals
    signals = engine.generate_ofi_and_arb_signals(symbol, exchange_gateway)
    
    # DATA OUTAGE CHECK: If orderbook data unavailable, do NOT trade
    if signals.get("data_available") is False or signals.get("combined_signal") == "DATA_OUTAGE":
        return {
            "symbol": symbol,
            "ofi_signal": "DATA_OUTAGE",
            "ofi_value": 0.0,
            "arb_opportunity": False,
            "combined_signal": "DATA_OUTAGE",
            "should_enter": False,
            "entry_reason": "data_outage_orderbook_unavailable",
            "data_available": False
        }
    
    # Calculate volatility (simplified - use 5% default)
    volatility = 0.015  # 1.5% default
    spread_bp = 5.0     # 5bp default spread
    depth_units = 5     # 5 levels
    
    # Check entry filter
    should_enter, reason = engine.should_enter_trade(
        regime=regime,
        volatility=volatility,
        spread_bp=spread_bp,
        depth_units=depth_units,
        ofi_signal=signals["combined_signal"]
    )
    
    # Build base signal for intelligence inversion
    base_signal = {
        "symbol": symbol,
        "direction": signals["combined_signal"],
        "ofi": signals["ofi"]["ofi"],
        "ensemble": 0.0  # Will be populated from market data if available
    }
    
    # Apply intelligence-based inversion (from 630 enriched decisions analysis)
    inverted_signal = apply_intelligence_inversion(base_signal, bot_id="alpha")
    
    # Use inverted direction if inversion was applied
    final_signal = inverted_signal["direction"] if inverted_signal.get("inverted") else signals["combined_signal"]
    
    return {
        "symbol": symbol,
        "ofi_signal": signals["ofi"]["signal"],
        "ofi_value": signals["ofi"]["ofi"],
        "arb_opportunity": signals["arb"]["arb_opportunity"],
        "combined_signal": final_signal,
        "original_signal": signals["combined_signal"],
        "inverted": inverted_signal.get("inverted", False),
        "inversion_reason": inverted_signal.get("inversion_reason"),
        "size_modifier": inverted_signal.get("size_modifier", 1.0),
        "should_enter": should_enter,
        "entry_reason": reason
    }


def check_alpha_exit(position: Dict[str, Any], regime: str = "momentum") -> Tuple[bool, str]:
    """
    Check if should exit position based on alpha logic.
    
    Args:
        position: Position dict with entry_ts, current_pnl
        regime: Current market regime
        
    Returns: (should_exit, reason)
    """
    engine = get_alpha_signals_engine()
    return engine.should_exit_position(
        entry_ts=position.get("entry_ts", int(time.time())),
        current_pnl=position.get("current_pnl", 0.0),
        regime=regime
    )


def log_alpha_trade(trade_data: Dict[str, Any]):
    """
    Log trade forensics for attribution analysis.
    
    Args:
        trade_data: Dict with symbol, pnl, fees, slippage, spread, latency,
                    venue, maker, entry_ts, exit_ts, direction, strategy
    """
    engine = get_alpha_signals_engine()
    engine.log_trade_forensics(**trade_data)


if __name__ == "__main__":
    # Demo: Test alpha signals engine
    print("="*60)
    print("Alpha Signals Engine - Integration Test")
    print("="*60)
    
    # Mock exchange gateway
    class MockGateway:
        def get_price(self, symbol, venue="futures"):
            return 50000.0
        
        def get_orderbook(self, symbol, venue="futures", depth=5):
            return {
                "bids": [[50000, 10], [49999, 8], [49998, 6], [49997, 4], [49996, 2]],
                "asks": [[50001, 7], [50002, 5], [50003, 3], [50004, 2], [50005, 1]]
            }
    
    gw = MockGateway()
    
    # Test signal generation
    result = generate_live_alpha_signals("BTCUSDT", gw, regime="momentum")
    
    print(f"\nSymbol: {result['symbol']}")
    print(f"OFI Signal: {result['ofi_signal']}")
    print(f"OFI Value: {result['ofi_value']:.4f}")
    print(f"Arb Opportunity: {result['arb_opportunity']}")
    print(f"Combined Signal: {result['combined_signal']}")
    print(f"Should Enter: {result['should_enter']}")
    print(f"Reason: {result['entry_reason']}")
    
    print("\n✅ Alpha signals engine integration test complete!")
