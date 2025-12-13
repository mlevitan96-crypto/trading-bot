"""
Phase 7.3 Expanded SHORT Suppression
Adds R:R skew and slippage quality checks
"""

from typing import Optional
from phase73_config import Phase73Config
from phase73_telemetry import get_phase73_telemetry


def short_allowed(symbol: str, config: Phase73Config) -> tuple[bool, str]:
    if not config.suppress_shorts_until_profitable:
        return (True, "suppression_disabled")
    
    telemetry = get_phase73_telemetry()
    
    wr, pnl, n = telemetry.get_shorts_stats_symbol(symbol, config.shorts_window_trades)
    
    if n < config.shorts_window_trades:
        return (False, f"insufficient_data:n={n}<{config.shorts_window_trades}")
    
    if wr < config.shorts_min_wr:
        return (False, f"low_wr:{wr:.2%}<{config.shorts_min_wr:.2%}")
    
    if pnl < config.shorts_min_pnl_usd:
        return (False, f"negative_pnl:${pnl:.2f}<${config.shorts_min_pnl_usd:.2f}")
    
    rr_skew = telemetry.get_shorts_rr_skew(symbol, config.shorts_window_trades)
    if rr_skew is None or rr_skew < config.shorts_min_rr_skew:
        return (False, f"poor_rr_skew:{rr_skew if rr_skew else 'N/A'}<{config.shorts_min_rr_skew}")
    
    slip_p75 = telemetry.get_shorts_slippage_p75(symbol, config.shorts_window_trades)
    if slip_p75 is None or slip_p75 > config.shorts_slippage_p75_cap_bps:
        return (False, f"high_slippage:{slip_p75 if slip_p75 else 'N/A'}bps>{config.shorts_slippage_p75_cap_bps}bps")
    
    return (True, "passed_all_checks")
