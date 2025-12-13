import pandas as pd
import numpy as np


CLUSTERS = [
    ['ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT'],  # Alt L1 cluster (high correlation)
    ['BTCUSDT'],  # BTC standalone (market leader)
    ['TRXUSDT', 'XRPUSDT'],  # Payment tokens
    ['ARBUSDT', 'OPUSDT'],  # Ethereum L2 cluster
    ['LINKUSDT'],  # DeFi/Oracle (standalone - lower correlation)
    ['PEPEUSDT', 'DOGEUSDT'],  # Meme cluster
    ['ADAUSDT', 'BNBUSDT'],  # Exchange/Smart contract
]


def compute_correlation_matrix(price_series_map, window=100):
    """
    Compute correlation matrix for given price series.
    
    Args:
        price_series_map: {symbol: list or pd.Series of closes}
        window: Rolling window for correlation calculation
    
    Returns:
        pd.DataFrame: Correlation matrix
    """
    if len(price_series_map) < 2:
        return pd.DataFrame()
    
    df = pd.DataFrame(price_series_map)
    
    if len(df) < 2:
        return pd.DataFrame()
    
    corr = df.pct_change().tail(window).corr()
    return corr


def correlation_exposure_cap(open_positions, corr_matrix, max_pair_corr=0.85, max_cluster_exposure_pct=0.40, portfolio_value=10000.0):
    """
    Calculate exposure caps based on correlation clustering.
    Reduces exposure when symbols cluster with high correlation.
    
    Args:
        open_positions: List of open position dicts with 'symbol' and 'size' keys
        corr_matrix: pd.DataFrame correlation matrix
        max_pair_corr: Threshold for high correlation (default 0.85)
        max_cluster_exposure_pct: Max combined exposure for correlated pairs (default 40%)
        portfolio_value: Total portfolio value for exposure calculation
    
    Returns:
        dict: {symbol: recommended_size_cap}
    """
    if corr_matrix.empty:
        return {}
    
    # Calculate current exposure per symbol
    symbol_sizes = {}
    for p in open_positions:
        symbol = p.get('symbol', '')
        size = p.get('size', 0.0)
        symbol_sizes[symbol] = symbol_sizes.get(symbol, 0.0) + size
    
    # Initialize caps at portfolio value (no restriction)
    caps = {s: portfolio_value for s in symbol_sizes}
    symbols = list(symbol_sizes.keys())
    
    # Check all symbol pairs for high correlation
    for i in range(len(symbols)):
        for j in range(i+1, len(symbols)):
            si, sj = symbols[i], symbols[j]
            
            # Get correlation coefficient
            if si in corr_matrix.index and sj in corr_matrix.columns:
                c = corr_matrix.loc[si, sj]
            else:
                c = 0.0
            
            # If highly correlated, cap combined exposure
            if c >= max_pair_corr:
                combined = symbol_sizes[si] + symbol_sizes[sj]
                cap_total = portfolio_value * max_cluster_exposure_pct
                
                if combined > cap_total:
                    # Recommend proportional caps
                    ratio_i = symbol_sizes[si] / combined
                    ratio_j = symbol_sizes[sj] / combined
                    caps[si] = min(caps[si], cap_total * ratio_i)
                    caps[sj] = min(caps[sj], cap_total * ratio_j)
    
    return caps


def get_prospective_correlation_cap(symbol, prospective_size, open_positions, corr_matrix, max_pair_corr=0.85, max_cluster_exposure_pct=0.40, portfolio_value=10000.0):
    """
    Calculate correlation cap for a prospective trade BEFORE execution.
    Checks if symbol is correlated with existing positions and limits sizing accordingly.
    
    Args:
        symbol: Symbol for prospective trade
        prospective_size: Proposed position size
        open_positions: Current open positions
        corr_matrix: Correlation matrix
        max_pair_corr: Correlation threshold (default 0.85)
        max_cluster_exposure_pct: Max cluster exposure (default 40%)
        portfolio_value: Portfolio value
    
    Returns:
        float: Maximum allowed position size for this symbol
    """
    if corr_matrix.empty or symbol not in corr_matrix.index:
        return portfolio_value
    
    # Calculate current exposure per symbol
    symbol_sizes = {}
    for p in open_positions:
        sym = p.get('symbol', '')
        size = p.get('size', 0.0)
        symbol_sizes[sym] = symbol_sizes.get(sym, 0.0) + size
    
    # Get current exposure for prospective symbol (if any)
    current_exposure = symbol_sizes.get(symbol, 0.0)
    
    # Check correlation with all existing positions
    max_cap = portfolio_value
    cluster_limit = portfolio_value * max_cluster_exposure_pct
    
    for existing_symbol, existing_size in symbol_sizes.items():
        if existing_symbol == symbol:
            continue
        
        # Get correlation
        if existing_symbol in corr_matrix.columns:
            c = corr_matrix.loc[symbol, existing_symbol]
        else:
            c = 0.0
        
        # If highly correlated, limit new position
        if c >= max_pair_corr:
            # Combined exposure would be: existing + current + prospective
            combined = existing_size + current_exposure + prospective_size
            
            if combined > cluster_limit:
                # Calculate maximum allowed for prospective trade
                remaining_capacity = cluster_limit - (existing_size + current_exposure)
                max_cap = min(max_cap, max(0, remaining_capacity))
    
    return max_cap


def enforce_cluster_caps(open_positions, portfolio_value, max_cluster_pct=0.40):
    """
    Enforce cluster-level exposure caps to prevent concentration risk.
    Scales existing positions proportionally to meet cluster limit.
    
    Args:
        open_positions: List of open position dicts
        portfolio_value: Total portfolio value
        max_cluster_pct: Maximum exposure per cluster (default 40%)
    
    Returns:
        dict: {symbol: max_allowed_size} caps for symbols exceeding cluster limit
    
    Example:
        - Cluster has ETHUSDT at 50% exposure
        - Cluster cap is 40%
        - Returns: {'ETHUSDT': portfolio_value * 0.40}
    """
    caps = {}
    
    for cluster in CLUSTERS:
        symbol_sizes = {}
        cluster_total = 0.0
        
        for p in open_positions:
            sym = p.get('symbol', '')
            if sym in cluster:
                size = p.get('size', 0.0)
                symbol_sizes[sym] = symbol_sizes.get(sym, 0.0) + size
                cluster_total += size
        
        cap_total = portfolio_value * max_cluster_pct
        
        if cluster_total > cap_total:
            for sym, current_size in symbol_sizes.items():
                ratio = current_size / cluster_total if cluster_total > 0 else 0
                caps[sym] = cap_total * ratio
    
    return caps


def enforce_cluster_caps_with_leverage(open_spot_positions, open_futures_positions, portfolio_value, max_cluster_pct=0.40):
    """
    Enforce cluster-level exposure caps accounting for leveraged futures exposure.
    
    Key difference from enforce_cluster_caps:
    - Spot positions: exposure = position size
    - Futures positions: exposure = margin × leverage (notional exposure)
    
    Args:
        open_spot_positions: List of open spot position dicts with 'symbol' and 'size'
        open_futures_positions: List of open futures position dicts with 'symbol', 'margin_collateral', and 'leverage'
        portfolio_value: Total portfolio value
        max_cluster_pct: Maximum exposure per cluster (default 40%)
    
    Returns:
        dict: {symbol: {spot_cap: USD, futures_margin_cap: USD}} for symbols exceeding cluster limit
    """
    caps = {}
    
    for cluster in CLUSTERS:
        symbol_exposures = {}  # Total notional exposure per symbol
        symbol_spot_sizes = {}
        symbol_futures_margins = {}
        cluster_total_exposure = 0.0
        
        # Calculate spot exposure
        for p in open_spot_positions:
            sym = p.get('symbol', '')
            if sym in cluster:
                size = p.get('size', 0.0)
                symbol_spot_sizes[sym] = symbol_spot_sizes.get(sym, 0.0) + size
                symbol_exposures[sym] = symbol_exposures.get(sym, 0.0) + size
                cluster_total_exposure += size
        
        # Calculate futures exposure (notional = margin × leverage)
        for p in open_futures_positions:
            sym = p.get('symbol', '')
            if sym in cluster:
                margin = p.get('margin_collateral', 0.0)
                leverage = p.get('leverage', 1)
                notional_exposure = margin * leverage
                symbol_futures_margins[sym] = symbol_futures_margins.get(sym, 0.0) + margin
                symbol_exposures[sym] = symbol_exposures.get(sym, 0.0) + notional_exposure
                cluster_total_exposure += notional_exposure
        
        cap_total = portfolio_value * max_cluster_pct
        
        # If cluster exceeds cap, proportionally reduce
        if cluster_total_exposure > cap_total:
            for sym in symbol_exposures.keys():
                exposure = symbol_exposures[sym]
                ratio = exposure / cluster_total_exposure if cluster_total_exposure > 0 else 0
                allocated_cap = cap_total * ratio
                
                # Split allocated cap between spot and futures proportionally
                spot_size = symbol_spot_sizes.get(sym, 0.0)
                futures_notional = symbol_exposures[sym] - spot_size
                
                if sym not in caps:
                    caps[sym] = {}
                
                # Spot cap is straightforward
                if spot_size > 0:
                    caps[sym]['spot_cap'] = allocated_cap * (spot_size / exposure) if exposure > 0 else 0
                
                # Futures cap: convert notional cap back to margin cap
                # futures_margin_cap = futures_notional_cap / avg_leverage
                if futures_notional > 0:
                    avg_leverage = futures_notional / symbol_futures_margins.get(sym, 1) if symbol_futures_margins.get(sym, 0) > 0 else 1
                    futures_notional_cap = allocated_cap * (futures_notional / exposure) if exposure > 0 else 0
                    caps[sym]['futures_margin_cap'] = futures_notional_cap / avg_leverage
    
    return caps


def get_available_futures_margin_for_symbol(symbol, open_futures_positions, corr_matrix, portfolio_value, proposed_leverage=1, max_pair_corr=0.85, max_cluster_exposure_pct=0.40):
    """
    Calculate available margin collateral for a futures position accounting for leveraged exposure correlation.
    
    Similar to get_correlation_cap_for_symbol but for futures:
    - Uses notional exposure (margin × leverage) for correlation calculations
    - Returns maximum margin allocation (not notional)
    
    Args:
        symbol: Symbol to check
        open_futures_positions: List of open futures position dicts
        corr_matrix: Correlation matrix
        portfolio_value: Total portfolio value
        proposed_leverage: Proposed leverage for new position
        max_pair_corr: Correlation threshold (default 0.85)
        max_cluster_exposure_pct: Max cluster exposure % (default 40%)
    
    Returns:
        float: Maximum margin collateral allowed for this symbol
    """
    if corr_matrix.empty or symbol not in corr_matrix.index:
        return portfolio_value * 0.15  # Conservative default: 15% margin
    
    # Calculate current notional exposure per symbol
    symbol_notional = {}
    for p in open_futures_positions:
        sym = p.get('symbol', '')
        margin = p.get('margin_collateral', 0.0)
        lev = p.get('leverage', 1)
        notional = margin * lev
        symbol_notional[sym] = symbol_notional.get(sym, 0.0) + notional
    
    # Get current notional for prospective symbol
    current_notional = symbol_notional.get(symbol, 0.0)
    
    # Check correlation with all existing positions
    max_margin_cap = portfolio_value * 0.15
    cluster_notional_limit = portfolio_value * max_cluster_exposure_pct
    
    for existing_symbol, existing_notional in symbol_notional.items():
        if existing_symbol == symbol:
            continue
        
        # Get correlation
        if existing_symbol in corr_matrix.columns:
            c = corr_matrix.loc[symbol, existing_symbol]
        else:
            c = 0.0
        
        # If highly correlated, limit new position's notional
        if c >= max_pair_corr:
            # Combined notional exposure would be: existing + current + (prospective_margin × leverage)
            remaining_notional_capacity = cluster_notional_limit - (existing_notional + current_notional)
            
            if remaining_notional_capacity > 0:
                # Convert notional capacity back to margin cap
                max_margin_from_this_pair = remaining_notional_capacity / proposed_leverage
                max_margin_cap = min(max_margin_cap, max_margin_from_this_pair)
            else:
                max_margin_cap = 0.0
                break
    
    return max(0.0, max_margin_cap)


def build_price_series_map(blofin_client, symbols, timeframe="1m", limit=120):
    """
    Build price series map from recent market data.
    
    Args:
        blofin_client: API client instance
        symbols: List of trading symbols
        timeframe: Timeframe for data (default "1m")
        limit: Number of candles to fetch (default 120)
    
    Returns:
        dict: {symbol: pd.Series of close prices}
    """
    price_series_map = {}
    
    for symbol in symbols:
        try:
            df = blofin_client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if df is not None and not df.empty and 'close' in df.columns:
                price_series_map[symbol] = df['close']
        except Exception as e:
            print(f"⚠️  Correlation: Failed to fetch {symbol}: {e}")
            continue
    
    return price_series_map
