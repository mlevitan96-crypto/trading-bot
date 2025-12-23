"""
Enhanced Trade Logging Module
==============================
Implements enhanced logging for trade analysis:
1. Volatility snapshot at entry (ATR, Volume, Regime)
2. Signal component breakdown (Liquidation, Funding, Whale Flow)
3. Golden hour trading window
4. Stable regime blocking
"""

import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from src.exchange_gateway import ExchangeGateway
from src.regime_detector import predict_regime
from src.regime_filter import get_regime_filter


def is_golden_hour() -> bool:
    """
    Check if current time is within golden trading hours.
    Trading Window: 09:00 UTC (London Open) to 16:00 UTC (NY Close)
    
    Returns:
        True if within golden hours, False otherwise
    """
    current_hour = datetime.now(timezone.utc).hour
    return 9 <= current_hour < 16


def get_market_data_snapshot(symbol: str) -> Dict[str, Any]:
    """
    Get market data snapshot at entry time.
    
    Returns:
        Dict with ATR, volume, and other market metrics
    """
    snapshot = {
        "atr_14": 0.0,
        "volume_24h": 0.0,
        "regime_at_entry": "unknown",
    }
    
    try:
        from src.exchange_gateway import ExchangeGateway
        from src.futures_ladder_exits import calculate_atr
        from src.venue_config import get_venue
        
        gateway = ExchangeGateway()
        venue = get_venue(symbol) if hasattr(__import__('src.venue_config', fromlist=['get_venue']), 'get_venue') else "futures"
        
        # Fetch OHLCV data for ATR calculation
        df = gateway.fetch_ohlcv(symbol, timeframe="1m", limit=50, venue=venue)
        if df is not None and len(df) >= 14:
            try:
                # Calculate ATR
                atr_val = calculate_atr(df["high"], df["low"], df["close"], period=14)
                snapshot["atr_14"] = float(atr_val) if atr_val and not (isinstance(atr_val, float) and (atr_val != atr_val or atr_val == float('inf'))) else 0.0
                if snapshot["atr_14"] == 0.0:
                    print(f"⚠️  [ENHANCED-LOGGING] ATR calculation returned 0 for {symbol} - check calculate_atr() function", flush=True)
            except Exception as e:
                print(f"⚠️  [ENHANCED-LOGGING] ATR calculation failed for {symbol}: {e}", flush=True)
                snapshot["atr_14"] = 0.0
            
            # Get volume (24h if available, otherwise recent average)
            if "volume" in df.columns:
                volume_24h = df["volume"].tail(1440).sum() if len(df) >= 1440 else df["volume"].sum()
                snapshot["volume_24h"] = float(volume_24h) if volume_24h else 0.0
        
        # Get regime at entry
        try:
            regime_filter = get_regime_filter()
            regime = regime_filter.get_regime(symbol)
            snapshot["regime_at_entry"] = regime if regime else "unknown"
        except:
            # Fallback to global regime
            try:
                regime = predict_regime()
                snapshot["regime_at_entry"] = regime if regime else "unknown"
            except:
                pass
                
    except Exception as e:
        # Silently fail - don't break trading if data fetch fails
        pass
    
    return snapshot


def extract_signal_components(signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract individual signal component scores from signals dict.
    
    Args:
        signals: Dict from predictive_flow_engine or similar
        
    Returns:
        Dict with liquidation, funding, whale flow scores
    """
    components = {
        "liquidation": 0.0,
        "funding": 0.0,
        "whale": 0.0,
    }
    
    if not signals:
        return components
    
    # Handle different signal formats
    if isinstance(signals, dict):
        # Format from predictive_flow_engine (has "signals" key)
        if "signals" in signals:
            signal_dict = signals["signals"]
        # Format from signal_context (already has signal_components)
        elif "signal_components" in signals:
            sig_comp = signals["signal_components"]
            if isinstance(sig_comp, dict):
                liq = sig_comp.get("liquidation_cascade", {}) or {}
                funding = sig_comp.get("funding_rate", {}) or {}
                whale = sig_comp.get("whale_flow", {}) or {}
                
                components["liquidation"] = float(liq.get("confidence", liq.get("total_1h", 0)) or 0)
                components["funding"] = float(funding.get("rate", funding.get("confidence", 0)) or 0)
                components["whale"] = float(whale.get("net_flow_usd", whale.get("confidence", 0)) or 0)
            return components
        else:
            signal_dict = signals
        
        # Liquidation cascade
        liq = signal_dict.get("liquidation", {}) or signal_dict.get("liquidation_cascade", {})
        if isinstance(liq, dict):
            # Try different field names
            components["liquidation"] = float(
                liq.get("score", 
                liq.get("confidence", 
                liq.get("total_1h", 0))) or 0
            )
        
        # Funding rate
        funding = signal_dict.get("funding", {}) or signal_dict.get("funding_rate", {})
        if isinstance(funding, dict):
            components["funding"] = float(
                funding.get("score",
                funding.get("rate",
                funding.get("confidence", 0))) or 0
            )
        
        # Whale flow
        whale = signal_dict.get("whale_flow", {})
        if isinstance(whale, dict):
            components["whale"] = float(
                whale.get("score",
                whale.get("net_flow_usd",
                whale.get("confidence", 0))) or 0
            )
    
    return components


def create_volatility_snapshot(symbol: str, signals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create complete volatility snapshot for trade logging.
    
    Args:
        symbol: Trading symbol
        signals: Signal dict from predictive_flow_engine (optional)
        
    Returns:
        Dict with all volatility and signal component data
    """
    market_data = get_market_data_snapshot(symbol)
    signal_components = extract_signal_components(signals) if signals else {}
    
    snapshot = {
        **market_data,
        "signal_components": signal_components,
    }
    
    return snapshot


def check_stable_regime_block(symbol: str, strategy: str) -> Tuple[bool, str]:
    """
    Check if trade should be blocked due to Stable regime.
    
    Analysis shows Stable regime has 35.2% win rate - HARD BLOCK.
    
    Args:
        symbol: Trading symbol
        strategy: Strategy name
        
    Returns:
        (should_block, reason)
    """
    try:
        regime_filter = get_regime_filter()
        current_regime = regime_filter.get_regime(symbol)
        
        if current_regime == "Stable":
            reason = "BLOCK: Stable Regime has 35.2% win rate (Market is chopping)."
            return True, reason
        
        # Also check global regime as fallback
        try:
            global_regime = predict_regime()
            if global_regime == "Stable":
                reason = "BLOCK: Global market is in Stable regime (35.2% win rate)."
                return True, reason
        except:
            pass
            
    except Exception as e:
        # If regime detection fails, don't block (fail open)
        pass
    
    return False, ""


def check_golden_hours_block() -> Tuple[bool, str]:
    """
    Check if trade should be blocked due to being outside golden hours.
    
    Returns:
        (should_block, reason)
    """
    if not is_golden_hour():
        reason = "BLOCK: Outside golden trading hours (09:00-16:00 UTC)."
        return True, reason
    
    return False, ""
