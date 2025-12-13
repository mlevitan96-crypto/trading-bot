"""
REALTIME FEATURES - Synchronized Feature Capture at Entry Time
================================================================
Captures market microstructure features at the exact moment of entry.
These features are stored with trade outcomes for proper ML training.
"""

import os
import json
from datetime import datetime
from typing import Dict, Optional, Tuple
import math

FEATURE_LOG = "logs/entry_features.jsonl"


class RealtimeFeatureCapture:
    """Captures market microstructure features at entry time."""
    
    def __init__(self, blofin_client=None):
        self.client = blofin_client
    
    def capture_orderbook_features(self, symbol: str) -> Dict:
        """
        Capture order book features at current moment.
        
        Features:
        - bid_ask_imbalance: (bid_depth - ask_depth) / total_depth
        - spread_bps: spread in basis points
        - bid_depth_usd: total USD value on bid side
        - ask_depth_usd: total USD value on ask side
        - mid_price: midpoint price
        - top_bid_size: size at best bid
        - top_ask_size: size at best ask
        """
        if not self.client:
            return self._empty_orderbook_features()
        
        try:
            book = self.client.get_orderbook(symbol, depth=20)
            
            bids = book.get('bids', [])
            asks = book.get('asks', [])
            
            if not bids or not asks:
                return self._empty_orderbook_features()
            
            best_bid = bids[0][0]
            best_ask = asks[0][0]
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_bps = (spread / mid_price) * 10000
            
            bid_depth = sum(b[0] * b[1] for b in bids)
            ask_depth = sum(a[0] * a[1] for a in asks)
            total_depth = bid_depth + ask_depth
            
            imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0
            
            return {
                'bid_ask_imbalance': round(imbalance, 4),
                'spread_bps': round(spread_bps, 2),
                'bid_depth_usd': round(bid_depth, 2),
                'ask_depth_usd': round(ask_depth, 2),
                'mid_price': round(mid_price, 6),
                'top_bid_size': round(bids[0][1], 4),
                'top_ask_size': round(asks[0][1], 4),
                'depth_ratio': round(bid_depth / ask_depth, 4) if ask_depth > 0 else 1.0
            }
            
        except Exception as e:
            return self._empty_orderbook_features()
    
    def _empty_orderbook_features(self) -> Dict:
        return {
            'bid_ask_imbalance': 0,
            'spread_bps': 0,
            'bid_depth_usd': 0,
            'ask_depth_usd': 0,
            'mid_price': 0,
            'top_bid_size': 0,
            'top_ask_size': 0,
            'depth_ratio': 1.0
        }
    
    def capture_price_momentum(self, symbol: str) -> Dict:
        """
        Capture recent price momentum.
        
        Features:
        - return_1m: 1-minute return
        - return_5m: 5-minute return
        - return_15m: 15-minute return
        - volatility_1h: 1-hour realized volatility
        """
        if not self.client:
            return self._empty_momentum_features()
        
        try:
            df = self.client.fetch_ohlcv(symbol, timeframe='1m', limit=60)
            
            if df is None or df.empty or len(df) < 15:
                return self._empty_momentum_features()
            
            prices = df['close'].tolist()
            if len(prices) < 15:
                return self._empty_momentum_features()
            
            current = prices[-1]
            
            return_1m = (current - prices[-2]) / prices[-2] if prices[-2] > 0 else 0
            return_5m = (current - prices[-6]) / prices[-6] if len(prices) >= 6 and prices[-6] > 0 else 0
            return_15m = (current - prices[-16]) / prices[-16] if len(prices) >= 16 and prices[-16] > 0 else 0
            
            if len(prices) >= 60:
                returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] > 0]
                volatility = (sum(r**2 for r in returns) / len(returns)) ** 0.5 if returns else 0
            else:
                volatility = 0
            
            return {
                'return_1m': round(return_1m * 100, 4),
                'return_5m': round(return_5m * 100, 4),
                'return_15m': round(return_15m * 100, 4),
                'volatility_1h': round(volatility * 100, 4),
                'price_trend': 1 if return_5m > 0 else (-1 if return_5m < 0 else 0)
            }
            
        except Exception as e:
            return self._empty_momentum_features()
    
    def _empty_momentum_features(self) -> Dict:
        return {
            'return_1m': 0,
            'return_5m': 0,
            'return_15m': 0,
            'volatility_1h': 0,
            'price_trend': 0
        }
    
    def capture_intelligence_features(self, symbol: str) -> Dict:
        """Load latest intelligence features for symbol."""
        intel_file = f"feature_store/intelligence/{symbol}_intel.json"
        
        try:
            with open(intel_file, 'r') as f:
                intel = json.load(f)
            
            taker = intel.get('taker', {})
            liq = intel.get('liquidation', {})
            signal = intel.get('signal', {})
            
            return {
                'buy_sell_ratio': taker.get('buy_sell_ratio', 1.0),
                'buy_ratio': taker.get('buy_ratio', 0.5),
                'liq_ratio': liq.get('liq_ratio', 0.5),
                'liq_long_1h': liq.get('liq_1h_long', 0) / 1e6,
                'liq_short_1h': liq.get('liq_1h_short', 0) / 1e6,
                'fear_greed': intel.get('fear_greed', 50) / 100.0,
                'intel_direction': 1 if signal.get('direction') == 'LONG' else (-1 if signal.get('direction') == 'SHORT' else 0),
                'intel_confidence': signal.get('confidence', 0)
            }
            
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'buy_sell_ratio': 1.0,
                'buy_ratio': 0.5,
                'liq_ratio': 0.5,
                'liq_long_1h': 0,
                'liq_short_1h': 0,
                'fear_greed': 0.5,
                'intel_direction': 0,
                'intel_confidence': 0
            }
    
    def capture_coinglass_features(self, symbol: str) -> Dict:
        """
        Capture funding rate, OI, and long/short ratio from CoinGlass intelligence cache.
        
        Data Source: feature_store/intelligence/ (populated by market_intelligence.py)
        API Reference: https://docs.coinglass.com/reference/endpoint-overview
        
        CRITICAL futures signals:
        - Funding rate: Extreme positive = too many longs (short signal)
        - OI delta: Rising OI + rising price = strong trend, divergence = reversal
        - Long/short ratio: Extreme readings = contrarian opportunity
        """
        base_symbol = symbol.replace("USDT", "").upper()
        intel_dir = "feature_store/intelligence"
        
        features = {
            'funding_rate': 0.0,
            'funding_zscore': 0.0,
            'oi_delta_pct': 0.0,
            'oi_current': 0.0,
            'long_short_ratio': 1.0,
            'long_ratio': 0.5,
            'short_ratio': 0.5
        }
        
        try:
            funding_file = f"{intel_dir}/funding_rates.json"
            if os.path.exists(funding_file):
                with open(funding_file, 'r') as f:
                    fund_data = json.load(f)
                rates = fund_data.get('rates', {})
                if base_symbol in rates:
                    sym_data = rates[base_symbol]
                    funding_rate = float(sym_data.get('funding_rate', 0) or 0)
                    features['funding_rate'] = round(funding_rate * 100, 6)
                    features['funding_zscore'] = float(sym_data.get('funding_signal', 0) or 0)
        except Exception:
            pass
        
        try:
            intel_file = f"{intel_dir}/{symbol}_intel.json"
            if os.path.exists(intel_file):
                with open(intel_file, 'r') as f:
                    intel_data = json.load(f)
                
                liq_data = intel_data.get('liquidation', {})
                if liq_data:
                    liq_long = float(liq_data.get('liq_long_24h', 0) or 0)
                    liq_short = float(liq_data.get('liq_short_24h', 0) or 0)
                    total_liq = liq_long + liq_short
                    
                    if total_liq > 0:
                        features['long_ratio'] = round(liq_long / total_liq, 4)
                        features['short_ratio'] = round(liq_short / total_liq, 4)
                        if liq_short > 0:
                            features['long_short_ratio'] = round(liq_long / liq_short, 4)
                
                taker_data = intel_data.get('taker', {})
                if taker_data:
                    buy_ratio = float(taker_data.get('buy_ratio', 0.5) or 0.5)
                    sell_ratio = float(taker_data.get('sell_ratio', 0.5) or 0.5)
                    if sell_ratio > 0:
                        features['oi_delta_pct'] = round((buy_ratio - sell_ratio) * 100, 4)
        except Exception:
            pass
        
        try:
            oi_file = f"{intel_dir}/open_interest.json"
            if os.path.exists(oi_file):
                with open(oi_file, 'r') as f:
                    oi_data = json.load(f)
                if base_symbol in oi_data:
                    oi_val = float(oi_data[base_symbol].get('oi_usd', 0) or 0)
                    features['oi_current'] = round(oi_val / 1e9, 4)
        except Exception:
            pass
        
        return features
    
    def capture_recent_streak(self, symbol: str) -> Dict:
        """
        Capture recent win/loss streak for this symbol.
        
        A coin on a hot streak may continue; a cold streak may need caution.
        """
        features = {
            'recent_wins': 0,
            'recent_losses': 0,
            'streak_direction': 0,
            'streak_length': 0,
            'recent_pnl': 0.0
        }
        
        try:
            pos_file = "logs/positions_futures.json"
            if os.path.exists(pos_file):
                with open(pos_file, 'r') as f:
                    data = json.load(f)
                closed = data.get('closed_positions', [])
                
                sym_trades = [p for p in closed if p.get('symbol') == symbol][-20:]
                
                if sym_trades:
                    wins = sum(1 for t in sym_trades if (t.get('net_pnl') or t.get('pnl') or 0) > 0)
                    losses = len(sym_trades) - wins
                    total_pnl = sum(t.get('net_pnl') or t.get('pnl') or 0 for t in sym_trades)
                    
                    features['recent_wins'] = wins
                    features['recent_losses'] = losses
                    features['recent_pnl'] = round(total_pnl, 2)
                    
                    streak = 0
                    streak_dir = 0
                    for t in reversed(sym_trades):
                        pnl = t.get('net_pnl') or t.get('pnl') or 0
                        current_dir = 1 if pnl > 0 else -1
                        if streak == 0:
                            streak_dir = current_dir
                            streak = 1
                        elif current_dir == streak_dir:
                            streak += 1
                        else:
                            break
                    
                    features['streak_direction'] = streak_dir
                    features['streak_length'] = streak
        except Exception:
            pass
        
        return features
    
    def capture_cross_asset_features(self, symbol: str) -> Dict:
        """
        Capture BTC/ETH as leading indicators for altcoins.
        
        BTC often leads alts - if BTC is strongly trending, alts may follow.
        """
        features = {
            'btc_return_15m': 0.0,
            'btc_trend': 0,
            'eth_return_15m': 0.0,
            'eth_trend': 0,
            'btc_eth_aligned': 0
        }
        
        if symbol in ['BTCUSDT', 'ETHUSDT']:
            return features
        
        try:
            btc_features = self.capture_price_momentum('BTCUSDT')
            features['btc_return_15m'] = btc_features.get('return_15m', 0)
            features['btc_trend'] = btc_features.get('price_trend', 0)
        except Exception:
            pass
        
        try:
            eth_features = self.capture_price_momentum('ETHUSDT')
            features['eth_return_15m'] = eth_features.get('return_15m', 0)
            features['eth_trend'] = eth_features.get('price_trend', 0)
        except Exception:
            pass
        
        if features['btc_trend'] == features['eth_trend'] and features['btc_trend'] != 0:
            features['btc_eth_aligned'] = features['btc_trend']
        
        return features
    
    def capture_sentiment_features(self, symbol: str) -> Dict:
        """
        Capture sentiment features from cached sentiment data.
        
        Features:
        - Fear/Greed index (0-100 normalized)
        - Sentiment signal (-1 to 1)
        - Social activity score
        - Sentiment confidence
        """
        try:
            from src.sentiment_fetcher import get_sentiment_features
            return get_sentiment_features(symbol)
        except Exception as e:
            return {
                'sentiment_fear_greed': 0.5,
                'sentiment_fg_signal': 0,
                'sentiment_score': 0,
                'sentiment_confidence': 0,
                'sentiment_signal': 0,
                'sentiment_activity': 0,
                'sentiment_is_stale': 1.0
            }
    
    def capture_onchain_features(self, symbol: str) -> Dict:
        """
        Capture on-chain features from cached whale/flow data.
        
        Features:
        - Exchange net flow (normalized)
        - Flow signal and confidence
        - Inflow/outflow volumes
        """
        try:
            from src.onchain_fetcher import get_onchain_features
            return get_onchain_features(symbol)
        except Exception as e:
            return {
                'onchain_net_flow': 0,
                'onchain_flow_signal': 0,
                'onchain_flow_confidence': 0,
                'onchain_inflows': 0,
                'onchain_outflows': 0,
                'onchain_is_stale': 1.0
            }
    
    def capture_all_features(self, symbol: str, proposed_direction: str) -> Dict:
        """
        Capture ALL features at entry time for ML training.
        
        Feature Groups (50+ total features):
        1. Temporal (4): hour, hour_sin/cos, day_of_week
        2. Order Book (8): imbalance, spread, depths, sizes
        3. Momentum (5): returns, volatility, trend
        4. Intelligence (8): buy/sell ratio, liquidations, fear/greed
        5. CoinGlass (7): funding rate, OI delta, long/short ratio
        6. Recent Streak (5): wins, losses, streak direction/length
        7. Cross-Asset (5): BTC/ETH as leading indicators
        8. Sentiment (7): fear/greed, social activity, sentiment signals (NEW)
        9. On-Chain (6): whale flows, exchange inflows/outflows (NEW)
        
        Args:
            symbol: Trading pair
            proposed_direction: LONG or SHORT
        
        Returns:
            Complete feature dict with all microstructure data
        """
        now = datetime.utcnow()
        hour = now.hour
        
        features = {
            'timestamp': now.isoformat() + 'Z',
            'symbol': symbol,
            'proposed_direction': proposed_direction,
            'hour': hour,
            'hour_sin': math.sin(2 * math.pi * hour / 24),
            'hour_cos': math.cos(2 * math.pi * hour / 24),
            'day_of_week': now.weekday()
        }
        
        features.update(self.capture_orderbook_features(symbol))
        features.update(self.capture_price_momentum(symbol))
        features.update(self.capture_intelligence_features(symbol))
        features.update(self.capture_coinglass_features(symbol))
        features.update(self.capture_recent_streak(symbol))
        features.update(self.capture_cross_asset_features(symbol))
        features.update(self.capture_sentiment_features(symbol))
        features.update(self.capture_onchain_features(symbol))
        
        self._log_features(features)
        
        return features
    
    def _log_features(self, features: Dict):
        """Log features to JSONL file."""
        try:
            with open(FEATURE_LOG, 'a') as f:
                f.write(json.dumps(features) + '\n')
        except Exception:
            pass
    
    def predict_direction(self, features: Dict) -> Tuple[str, float]:
        """
        Make entry prediction based on captured features.
        
        Returns:
            (direction, confidence) - LONG/SHORT with confidence 0-1
        """
        signals = []
        
        imbalance = features.get('bid_ask_imbalance', 0)
        if imbalance > 0.1:
            signals.append(('LONG', min(imbalance, 0.3)))
        elif imbalance < -0.1:
            signals.append(('SHORT', min(abs(imbalance), 0.3)))
        
        trend = features.get('return_5m', 0)
        if trend > 0.1:
            signals.append(('LONG', min(trend / 100, 0.3)))
        elif trend < -0.1:
            signals.append(('SHORT', min(abs(trend) / 100, 0.3)))
        
        intel_dir = features.get('intel_direction', 0)
        intel_conf = features.get('intel_confidence', 0)
        if intel_dir != 0 and intel_conf > 0.3:
            direction = 'LONG' if intel_dir > 0 else 'SHORT'
            signals.append((direction, intel_conf * 0.3))
        
        buy_sell = features.get('buy_sell_ratio', 1.0)
        if buy_sell > 1.1:
            signals.append(('LONG', min((buy_sell - 1) * 0.3, 0.2)))
        elif buy_sell < 0.9:
            signals.append(('SHORT', min((1 - buy_sell) * 0.3, 0.2)))
        
        if not signals:
            return 'NEUTRAL', 0.0
        
        long_score = sum(s[1] for s in signals if s[0] == 'LONG')
        short_score = sum(s[1] for s in signals if s[0] == 'SHORT')
        
        if long_score > short_score and long_score > 0.1:
            return 'LONG', min(long_score, 0.9)
        elif short_score > long_score and short_score > 0.1:
            return 'SHORT', min(short_score, 0.9)
        else:
            return 'NEUTRAL', 0.0


def get_entry_recommendation(symbol: str, proposed_direction: str, blofin_client=None) -> Dict:
    """
    Get entry recommendation with features and prediction.
    
    Args:
        symbol: Trading pair
        proposed_direction: What the signal says (LONG/SHORT)
        blofin_client: BlofinFuturesClient instance
    
    Returns:
        Dict with features, prediction, and recommendation
    """
    capture = RealtimeFeatureCapture(blofin_client)
    features = capture.capture_all_features(symbol, proposed_direction)
    
    predicted_dir, confidence = capture.predict_direction(features)
    
    if predicted_dir == proposed_direction:
        action = 'CONFIRM'
        sizing_mult = 1.0 + (confidence * 0.5)
    elif predicted_dir == 'NEUTRAL':
        action = 'PROCEED'
        sizing_mult = 0.8
    else:
        if confidence > 0.5:
            action = 'FLIP'
            sizing_mult = 0.5
        else:
            action = 'REDUCE'
            sizing_mult = 0.6
    
    return {
        'features': features,
        'proposed': proposed_direction,
        'predicted': predicted_dir,
        'confidence': round(confidence, 3),
        'action': action,
        'sizing_mult': round(sizing_mult, 2),
        'recommendation': f"{action}: {'Aligned' if action == 'CONFIRM' else 'Divergent'} signal"
    }


if __name__ == "__main__":
    print("Testing feature capture (without live client)...")
    capture = RealtimeFeatureCapture(None)
    features = capture.capture_all_features("BTCUSDT", "LONG")
    print(json.dumps(features, indent=2))
