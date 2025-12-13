"""
PREDICTIVE FLOW ENGINE - Multi-Factor Signal System
====================================================
Replaces flawed snapshot OFI with a comprehensive predictive signal system.

CORE PRINCIPLES:
1. Track MOMENTUM, not snapshots - rate of change matters more than magnitude
2. Require PRICE CONFIRMATION - signals must actually move price
3. Multiple INDEPENDENT signals must align - conviction gate
4. FLOW-OF-FUNDS leads price - funding, OI, liquidations, whale flows

PAPER MODE:
- When in paper trading mode, thresholds are relaxed to generate more signals
- This allows for more data collection and learning from a broader set of signals
- Thresholds are loaded from configs/trading_config.json

SIGNAL COMPONENTS (ranked by predictive power):
1. Liquidation Cascade Detection (25%) - forced selling creates momentum
2. Funding Rate Extremes (20%) - crowded trades unwind violently
3. Open Interest Velocity (20%) - new money flow direction
4. Whale Exchange Flows (15%) - smart money positioning
5. Order Flow Momentum (10%) - rate of change of buy/sell pressure
6. Fear & Greed Contrarian (10%) - extreme sentiment reversals

CONVICTION LEVELS:
- HIGH: 4+ signals aligned, expected edge > 2x fees
- MEDIUM: 3 signals aligned, expected edge > fees
- LOW: 2 signals aligned - size down or skip
- NONE: <2 signals - DO NOT TRADE
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from collections import deque

SIGNAL_HISTORY = Path("feature_store/signal_history")
SIGNAL_HISTORY.mkdir(parents=True, exist_ok=True)

OFI_HISTORY_FILE = SIGNAL_HISTORY / "ofi_momentum.json"
PREDICTION_LOG = Path("logs/predictive_signals.jsonl")
TRADING_CONFIG_FILE = Path("configs/trading_config.json")
PREDICTION_LOG.parent.mkdir(parents=True, exist_ok=True)


def _load_trading_config() -> Dict[str, Any]:
    """Load trading configuration from file."""
    try:
        if TRADING_CONFIG_FILE.exists():
            return json.loads(TRADING_CONFIG_FILE.read_text())
    except Exception as e:
        pass
    return {}


def _get_paper_mode() -> bool:
    """
    Determine if we're in paper trading mode.
    
    Priority:
    1. Environment variable TRADING_MODE ('paper' or 'live')
    2. Config file configs/trading_config.json mode field
    3. Default: True (paper mode for safety)
    """
    env_mode = os.environ.get('TRADING_MODE', '').lower()
    if env_mode in ('paper', 'live'):
        return env_mode == 'paper'
    
    config = _load_trading_config()
    mode = config.get('mode', 'paper').lower()
    return mode == 'paper'


def _get_signal_thresholds() -> Dict[str, Any]:
    """Get signal thresholds based on trading mode."""
    config = _load_trading_config()
    mode = 'paper' if _get_paper_mode() else 'live'
    thresholds = config.get('thresholds', {}).get(mode, {}).get('signal_thresholds', {})
    
    if mode == 'paper':
        return {
            'funding_min': thresholds.get('funding_min', 0.0001),
            'oi_velocity_min_pct': thresholds.get('oi_velocity_min_pct', 0.5),
            'whale_flow_min_usd': thresholds.get('whale_flow_min_usd', 250000),
            'liquidation_min_usd': thresholds.get('liquidation_min_usd', 50000),
            'fear_greed_fear_threshold': thresholds.get('fear_greed_fear_threshold', 15),
            'fear_greed_greed_threshold': thresholds.get('fear_greed_greed_threshold', 85)
        }
    else:
        return {
            'funding_min': thresholds.get('funding_min', 0.0002),
            'oi_velocity_min_pct': thresholds.get('oi_velocity_min_pct', 2.0),
            'whale_flow_min_usd': thresholds.get('whale_flow_min_usd', 1000000),
            'liquidation_min_usd': thresholds.get('liquidation_min_usd', 100000),
            'fear_greed_fear_threshold': thresholds.get('fear_greed_fear_threshold', 20),
            'fear_greed_greed_threshold': thresholds.get('fear_greed_greed_threshold', 80)
        }


PAPER_MODE = _get_paper_mode()
SIGNAL_THRESHOLDS = _get_signal_thresholds()

_mode_logged = False
def _log_mode_once():
    """Log the current trading mode once at startup."""
    global _mode_logged
    if not _mode_logged:
        mode_str = "PAPER (relaxed)" if PAPER_MODE else "LIVE (strict)"
        print(f"[PredictiveFlowEngine] Running in {mode_str} mode")
        print(f"[PredictiveFlowEngine] Signal thresholds: funding_min={SIGNAL_THRESHOLDS['funding_min']}, oi_min={SIGNAL_THRESHOLDS['oi_velocity_min_pct']}%, whale_min=${SIGNAL_THRESHOLDS['whale_flow_min_usd']:,}, liq_min=${SIGNAL_THRESHOLDS['liquidation_min_usd']:,}")
        _mode_logged = True


class OFIMomentumTracker:
    """Track OFI rate-of-change instead of snapshots."""
    
    def __init__(self, window_size: int = 10, max_age_seconds: float = 30.0):
        self.window_size = window_size
        self.max_age = max_age_seconds
        self.history: Dict[str, deque] = {}
        self._load_history()
    
    def _load_history(self):
        try:
            if OFI_HISTORY_FILE.exists():
                data = json.loads(OFI_HISTORY_FILE.read_text())
                for symbol, readings in data.items():
                    self.history[symbol] = deque(readings, maxlen=self.window_size)
        except:
            pass
    
    def _save_history(self):
        try:
            data = {s: list(h) for s, h in self.history.items()}
            OFI_HISTORY_FILE.write_text(json.dumps(data))
        except:
            pass
    
    def record_reading(self, symbol: str, ofi: float, price: float):
        """Record an OFI reading with timestamp and price."""
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=self.window_size)
        
        reading = {
            'ts': time.time(),
            'ofi': ofi,
            'price': price
        }
        self.history[symbol].append(reading)
        self._save_history()
    
    def get_momentum_signal(self, symbol: str, current_ofi: float, current_price: float) -> Dict[str, Any]:
        """
        Calculate OFI momentum signal.
        
        Returns:
            {
                'ofi_momentum': float,  # Rate of change (-1 to 1)
                'price_response': float,  # Did price follow OFI?
                'freshness': float,  # 0-1, how fresh is the data?
                'signal': str,  # 'STRONG_LONG', 'LONG', 'NEUTRAL', 'SHORT', 'STRONG_SHORT'
                'confidence': float,  # 0-1
                'reasons': list
            }
        """
        if symbol not in self.history or len(self.history[symbol]) < 3:
            return {
                'ofi_momentum': 0.0,
                'price_response': 0.0,
                'freshness': 0.0,
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'reasons': ['insufficient_history']
            }
        
        readings = list(self.history[symbol])
        now = time.time()
        
        fresh_readings = [r for r in readings if (now - r['ts']) < self.max_age]
        if len(fresh_readings) < 2:
            return {
                'ofi_momentum': 0.0,
                'price_response': 0.0,
                'freshness': 0.0,
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'reasons': ['stale_data']
            }
        
        oldest = fresh_readings[0]
        freshness = 1.0 - min(1.0, (now - fresh_readings[-1]['ts']) / self.max_age)
        
        ofi_change = current_ofi - oldest['ofi']
        time_delta = now - oldest['ts']
        ofi_momentum = ofi_change / max(0.1, time_delta) * 10
        
        if oldest['price'] > 0:
            price_change = (current_price - oldest['price']) / oldest['price']
        else:
            price_change = 0
        
        expected_direction = 1 if current_ofi > 0 else -1
        actual_direction = 1 if price_change > 0 else -1 if price_change < 0 else 0
        
        price_response = 1.0 if (expected_direction == actual_direction and abs(price_change) > 0.0005) else 0.0
        
        signal = 'NEUTRAL'
        confidence = 0.0
        reasons = []
        
        if ofi_momentum > 0.05 and price_response > 0:
            signal = 'STRONG_LONG' if ofi_momentum > 0.15 else 'LONG'
            confidence = min(1.0, abs(ofi_momentum) * 2 + price_response * 0.3) * freshness
            reasons.append(f'rising_ofi_{ofi_momentum:.3f}')
            reasons.append('price_confirming')
        elif ofi_momentum < -0.05 and price_response > 0:
            signal = 'STRONG_SHORT' if ofi_momentum < -0.15 else 'SHORT'
            confidence = min(1.0, abs(ofi_momentum) * 2 + price_response * 0.3) * freshness
            reasons.append(f'falling_ofi_{ofi_momentum:.3f}')
            reasons.append('price_confirming')
        elif abs(ofi_momentum) > 0.05:
            signal = 'LONG' if ofi_momentum > 0 else 'SHORT'
            confidence = min(1.0, abs(ofi_momentum)) * freshness * 0.5
            reasons.append(f'ofi_moving_but_no_price_confirm')
        
        if abs(current_ofi) > 0.8 and abs(ofi_momentum) < 0.03:
            signal = 'NEUTRAL'
            confidence = 0.0
            reasons = ['extreme_ofi_but_exhausted']
        
        return {
            'ofi_momentum': round(ofi_momentum, 4),
            'price_response': round(price_response, 2),
            'freshness': round(freshness, 2),
            'signal': signal,
            'confidence': round(confidence, 3),
            'reasons': reasons
        }


class FundingRateSignal:
    """Fade extreme funding rates - crowded trades unwind."""
    
    def __init__(self):
        self._update_thresholds()
    
    def _update_thresholds(self):
        """Update thresholds from config."""
        thresholds = _get_signal_thresholds()
        min_funding = thresholds.get('funding_min', 0.0002)
        self.NEUTRAL_THRESHOLD = min_funding
        self.HIGH_THRESHOLD = min_funding * 2.5
        self.EXTREME_THRESHOLD = min_funding * 4
    
    def compute_signal(self, funding_rate: float) -> Dict[str, Any]:
        """
        Extreme positive funding = shorts pay longs = crowded longs = fade (SHORT)
        Extreme negative funding = longs pay shorts = crowded shorts = fade (LONG)
        """
        self._update_thresholds()
        abs_funding = abs(funding_rate)
        
        if abs_funding < self.NEUTRAL_THRESHOLD:
            return {
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'funding_rate': funding_rate,
                'reasons': ['neutral_funding']
            }
        
        if funding_rate > self.EXTREME_THRESHOLD:
            return {
                'signal': 'SHORT',
                'confidence': min(1.0, (funding_rate - self.NEUTRAL_THRESHOLD) / 0.001),
                'funding_rate': funding_rate,
                'reasons': [f'extreme_positive_funding_{funding_rate:.5f}', 'crowded_longs_fade']
            }
        elif funding_rate < -self.EXTREME_THRESHOLD:
            return {
                'signal': 'LONG',
                'confidence': min(1.0, (abs_funding - self.NEUTRAL_THRESHOLD) / 0.001),
                'funding_rate': funding_rate,
                'reasons': [f'extreme_negative_funding_{funding_rate:.5f}', 'crowded_shorts_fade']
            }
        elif funding_rate > self.HIGH_THRESHOLD:
            return {
                'signal': 'SHORT',
                'confidence': min(0.6, (funding_rate - self.NEUTRAL_THRESHOLD) / 0.001),
                'funding_rate': funding_rate,
                'reasons': [f'high_positive_funding_{funding_rate:.5f}']
            }
        elif funding_rate < -self.HIGH_THRESHOLD:
            return {
                'signal': 'LONG',
                'confidence': min(0.6, (abs_funding - self.NEUTRAL_THRESHOLD) / 0.001),
                'funding_rate': funding_rate,
                'reasons': [f'high_negative_funding_{funding_rate:.5f}']
            }
        
        return {
            'signal': 'NEUTRAL',
            'confidence': 0.0,
            'funding_rate': funding_rate,
            'reasons': ['moderate_funding']
        }


class OpenInterestVelocity:
    """Track rate of change of open interest - new money flow."""
    
    def __init__(self):
        self.history: Dict[str, deque] = {}
    
    def _get_min_oi_change(self) -> float:
        """Get minimum OI change threshold from config."""
        thresholds = _get_signal_thresholds()
        return thresholds.get('oi_velocity_min_pct', 2.0) / 100.0
    
    def compute_signal(self, symbol: str, current_oi: float, price_direction: int) -> Dict[str, Any]:
        """
        Rising OI + Rising Price = New longs entering (bullish continuation)
        Rising OI + Falling Price = New shorts entering (bearish continuation)
        Falling OI + Price move = Position closing (potential reversal)
        """
        min_oi_change = self._get_min_oi_change()
        
        if symbol not in self.history:
            self.history[symbol] = deque(maxlen=10)
        
        now = time.time()
        self.history[symbol].append({'ts': now, 'oi': current_oi})
        
        if len(self.history[symbol]) < 3:
            return {
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'oi_velocity': 0.0,
                'reasons': ['insufficient_oi_history']
            }
        
        readings = list(self.history[symbol])
        old_oi = readings[0]['oi']
        if old_oi <= 0:
            return {
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'oi_velocity': 0.0,
                'reasons': ['invalid_oi_data']
            }
        
        oi_change_pct = (current_oi - old_oi) / old_oi
        
        if oi_change_pct > min_oi_change and price_direction > 0:
            return {
                'signal': 'LONG',
                'confidence': min(1.0, oi_change_pct * (10 / (min_oi_change * 100))),
                'oi_velocity': oi_change_pct,
                'reasons': ['rising_oi_rising_price', 'new_longs_entering']
            }
        elif oi_change_pct > min_oi_change and price_direction < 0:
            return {
                'signal': 'SHORT',
                'confidence': min(1.0, oi_change_pct * (10 / (min_oi_change * 100))),
                'oi_velocity': oi_change_pct,
                'reasons': ['rising_oi_falling_price', 'new_shorts_entering']
            }
        elif oi_change_pct < -min_oi_change:
            reversal_signal = 'SHORT' if price_direction > 0 else 'LONG' if price_direction < 0 else 'NEUTRAL'
            return {
                'signal': reversal_signal,
                'confidence': min(0.7, abs(oi_change_pct) * (5 / (min_oi_change * 100))),
                'oi_velocity': oi_change_pct,
                'reasons': ['falling_oi', 'positions_closing', 'potential_reversal']
            }
        
        return {
            'signal': 'NEUTRAL',
            'confidence': 0.0,
            'oi_velocity': oi_change_pct,
            'reasons': ['stable_oi']
        }


class LiquidationCascadeDetector:
    """Detect and trade liquidation cascades - forced selling creates momentum."""
    
    IMBALANCE_THRESHOLD = 0.65
    
    def _get_thresholds(self) -> Tuple[float, float]:
        """Get liquidation thresholds from config."""
        thresholds = _get_signal_thresholds()
        min_liq = thresholds.get('liquidation_min_usd', 100000)
        cascade_threshold = min_liq * 50
        return min_liq, cascade_threshold
    
    def compute_signal(self, liq_long_1h: float, liq_short_1h: float, 
                       liq_long_4h: float = 0, liq_short_4h: float = 0) -> Dict[str, Any]:
        """
        Massive long liquidations = bearish cascade in progress
        Massive short liquidations = short squeeze in progress
        """
        min_liq, cascade_threshold = self._get_thresholds()
        total_1h = liq_long_1h + liq_short_1h
        total_4h = liq_long_4h + liq_short_4h
        
        if total_1h < min_liq:
            return {
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'cascade_active': False,
                'cascade_direction': None,
                'liq_imbalance': 0.5,
                'reasons': ['low_liquidation_volume']
            }
        
        long_ratio = liq_long_1h / total_1h if total_1h > 0 else 0.5
        
        is_cascade = total_1h > cascade_threshold
        
        if is_cascade and long_ratio > self.IMBALANCE_THRESHOLD:
            cascade_strength = min(1.0, (long_ratio - 0.5) * 2) * min(1.0, total_1h / (cascade_threshold * 2))
            return {
                'signal': 'SHORT',
                'confidence': cascade_strength,
                'cascade_active': True,
                'cascade_direction': 'BEARISH',
                'liq_imbalance': long_ratio,
                'liq_volume_usd': total_1h,
                'reasons': [f'long_liquidation_cascade_{total_1h/1e6:.1f}M', f'liq_ratio_{long_ratio:.2f}']
            }
        elif is_cascade and long_ratio < (1 - self.IMBALANCE_THRESHOLD):
            cascade_strength = min(1.0, (0.5 - long_ratio) * 2) * min(1.0, total_1h / (cascade_threshold * 2))
            return {
                'signal': 'LONG',
                'confidence': cascade_strength,
                'cascade_active': True,
                'cascade_direction': 'BULLISH',
                'liq_imbalance': long_ratio,
                'liq_volume_usd': total_1h,
                'reasons': [f'short_squeeze_cascade_{total_1h/1e6:.1f}M', f'liq_ratio_{long_ratio:.2f}']
            }
        elif total_1h > min_liq * 10:
            if long_ratio > 0.55:
                return {
                    'signal': 'SHORT',
                    'confidence': min(0.5, (long_ratio - 0.5) * 2),
                    'cascade_active': False,
                    'cascade_direction': 'BEARISH_BIAS',
                    'liq_imbalance': long_ratio,
                    'liq_volume_usd': total_1h,
                    'reasons': ['elevated_long_liquidations']
                }
            elif long_ratio < 0.45:
                return {
                    'signal': 'LONG',
                    'confidence': min(0.5, (0.5 - long_ratio) * 2),
                    'cascade_active': False,
                    'cascade_direction': 'BULLISH_BIAS',
                    'liq_imbalance': long_ratio,
                    'liq_volume_usd': total_1h,
                    'reasons': ['elevated_short_liquidations']
                }
        
        return {
            'signal': 'NEUTRAL',
            'confidence': 0.0,
            'cascade_active': False,
            'cascade_direction': None,
            'liq_imbalance': long_ratio,
            'reasons': ['balanced_liquidations']
        }


class WhaleFlowSignal:
    """Track whale exchange flows - smart money positioning."""
    
    def _get_min_flow(self) -> float:
        """Get minimum whale flow threshold from config."""
        thresholds = _get_signal_thresholds()
        return thresholds.get('whale_flow_min_usd', 1000000)
    
    def compute_signal(self, net_exchange_flow: float, inflows: float, outflows: float) -> Dict[str, Any]:
        """
        Large net inflows = selling pressure coming (bearish)
        Large net outflows = accumulation (bullish)
        """
        min_flow = self._get_min_flow()
        significant_flow = min_flow * 10
        total_flow = inflows + outflows
        
        if total_flow < min_flow:
            return {
                'signal': 'NEUTRAL',
                'confidence': 0.0,
                'net_flow': net_exchange_flow,
                'reasons': ['low_whale_activity']
            }
        
        if net_exchange_flow > significant_flow:
            confidence = min(1.0, net_exchange_flow / (significant_flow * 2))
            return {
                'signal': 'SHORT',
                'confidence': confidence,
                'net_flow': net_exchange_flow,
                'reasons': [f'large_exchange_inflow_{net_exchange_flow/1e6:.1f}M', 'selling_pressure']
            }
        elif net_exchange_flow < -significant_flow:
            confidence = min(1.0, abs(net_exchange_flow) / (significant_flow * 2))
            return {
                'signal': 'LONG',
                'confidence': confidence,
                'net_flow': net_exchange_flow,
                'reasons': [f'large_exchange_outflow_{abs(net_exchange_flow)/1e6:.1f}M', 'accumulation']
            }
        
        return {
            'signal': 'NEUTRAL',
            'confidence': 0.0,
            'net_flow': net_exchange_flow,
            'reasons': ['balanced_flows']
        }


class FearGreedContrarian:
    """Trade against extreme sentiment."""
    
    def _get_thresholds(self) -> Tuple[int, int]:
        """Get fear/greed thresholds from config."""
        thresholds = _get_signal_thresholds()
        fear_threshold = int(thresholds.get('fear_greed_fear_threshold', 20))
        greed_threshold = int(thresholds.get('fear_greed_greed_threshold', 80))
        return fear_threshold, greed_threshold
    
    def compute_signal(self, fear_greed_index: int) -> Dict[str, Any]:
        """
        Extreme Fear (<fear_threshold) = contrarian buy signal
        Extreme Greed (>greed_threshold) = contrarian sell signal
        Moderate Fear = mild contrarian buy signal
        Moderate Greed = mild contrarian sell signal
        """
        fear_threshold, greed_threshold = self._get_thresholds()
        
        extreme_fear = fear_threshold - 5
        extreme_greed = greed_threshold + 5
        moderate_fear = fear_threshold + 10
        moderate_greed = greed_threshold - 10
        
        if fear_greed_index < extreme_fear:
            return {
                'signal': 'STRONG_LONG',
                'confidence': min(1.0, (fear_threshold - fear_greed_index) / 15),
                'fear_greed': fear_greed_index,
                'reasons': ['extreme_fear', 'contrarian_buy']
            }
        elif fear_greed_index < fear_threshold:
            return {
                'signal': 'LONG',
                'confidence': min(0.7, (fear_threshold - fear_greed_index + 5) / 15),
                'fear_greed': fear_greed_index,
                'reasons': ['fear', 'contrarian_buy']
            }
        elif fear_greed_index < moderate_fear:
            return {
                'signal': 'LONG',
                'confidence': min(0.4, (moderate_fear - fear_greed_index) / 20),
                'fear_greed': fear_greed_index,
                'reasons': ['mild_fear', 'slight_contrarian_buy']
            }
        elif fear_greed_index > extreme_greed:
            return {
                'signal': 'STRONG_SHORT',
                'confidence': min(1.0, (fear_greed_index - greed_threshold) / 15),
                'fear_greed': fear_greed_index,
                'reasons': ['extreme_greed', 'contrarian_sell']
            }
        elif fear_greed_index > greed_threshold:
            return {
                'signal': 'SHORT',
                'confidence': min(0.7, (fear_greed_index - greed_threshold + 5) / 15),
                'fear_greed': fear_greed_index,
                'reasons': ['greed', 'contrarian_sell']
            }
        elif fear_greed_index > moderate_greed:
            return {
                'signal': 'SHORT',
                'confidence': min(0.4, (fear_greed_index - moderate_greed) / 20),
                'fear_greed': fear_greed_index,
                'reasons': ['mild_greed', 'slight_contrarian_sell']
            }
        
        return {
            'signal': 'NEUTRAL',
            'confidence': 0.0,
            'fear_greed': fear_greed_index,
            'reasons': ['neutral_sentiment']
        }


class PredictiveFlowEngine:
    """
    Master engine combining all predictive signals.
    
    Only generates trade signals when multiple independent signals align.
    """
    
    SIGNAL_WEIGHTS = {
        'liquidation': 0.22,
        'funding': 0.16,
        'oi_velocity': 0.05,
        'whale_flow': 0.20,
        'ofi_momentum': 0.06,
        'fear_greed': 0.06,
        'hurst': 0.08,
        'lead_lag': 0.08,
        'volatility_skew': 0.05,  # Loss aversion / complacency detection
        'oi_divergence': 0.04    # Price/OI trap detection
    }
    
    CONVICTION_THRESHOLDS = {
        'HIGH': {'min_signals': 4, 'min_confidence': 0.6, 'size_multiplier': 1.5},
        'MEDIUM': {'min_signals': 3, 'min_confidence': 0.4, 'size_multiplier': 1.0},
        'LOW': {'min_signals': 2, 'min_confidence': 0.3, 'size_multiplier': 0.5},
        'NONE': {'min_signals': 0, 'min_confidence': 0.0, 'size_multiplier': 0.0}
    }
    
    def __init__(self):
        self.ofi_tracker = OFIMomentumTracker()
        self.funding_signal = FundingRateSignal()
        self.oi_velocity = OpenInterestVelocity()
        self.liquidation_detector = LiquidationCascadeDetector()
        self.whale_flow = WhaleFlowSignal()
        self.fear_greed = FearGreedContrarian()
        _log_mode_once()
    
    def _load_intelligence_data(self, symbol: str) -> Dict[str, Any]:
        """Load cached intelligence data for symbol from summary.json."""
        intel_path = Path("feature_store/intelligence/summary.json")
        if intel_path.exists():
            try:
                data = json.loads(intel_path.read_text())
                clean_symbol = symbol.upper().replace('-', '')
                if not clean_symbol.endswith('USDT'):
                    clean_symbol = f"{clean_symbol}USDT"
                
                symbol_data = data.get('signals', {}).get(clean_symbol, {})
                
                result = {
                    'fear_greed': data.get('fear_greed', 50),
                    'liquidation': {
                        'liq_1h_long': symbol_data.get('raw', {}).get('liq_ratio', 0.5) * 1000000,
                        'liq_1h_short': (1 - symbol_data.get('raw', {}).get('liq_ratio', 0.5)) * 1000000,
                        'liq_4h_long': 0,
                        'liq_4h_short': 0
                    },
                    'funding_rate': symbol_data.get('funding', {}).get('funding_rate', 0),
                    'buy_sell_ratio': symbol_data.get('raw', {}).get('buy_sell_ratio', 1.0),
                    'confidence': symbol_data.get('confidence', 0)
                }
                return result
            except Exception as e:
                pass
        return {'fear_greed': 50}
    
    def _load_onchain_data(self, symbol: str) -> Dict[str, Any]:
        """Load cached on-chain data from exchange_flows.json."""
        flows_path = Path("feature_store/onchain/exchange_flows.json")
        if flows_path.exists():
            try:
                data = json.loads(flows_path.read_text())
                
                clean_symbol = symbol.upper().replace('USDT', '').replace('-USDT', '')
                
                signals_data = data.get('signals', data.get('coins', {}))
                if clean_symbol in signals_data:
                    coin_data = signals_data[clean_symbol]
                    return {
                        'net_flow': coin_data.get('net_flow_usd', 0),
                        'inflows': coin_data.get('inflows_usd', 0),
                        'outflows': coin_data.get('outflows_usd', 0),
                        'signal': coin_data.get('signal', 0),
                        'confidence': coin_data.get('confidence', 0)
                    }
            except:
                pass
        return {}
    
    def _load_funding_rate(self, symbol: str) -> float:
        """Load cached funding rate."""
        funding_path = Path("feature_store/intelligence/funding_rates.json")
        if funding_path.exists():
            try:
                data = json.loads(funding_path.read_text())
                rates = data.get('rates', data)
                clean_symbol = symbol.upper().replace('USDT', '').replace('-USDT', '')
                return float(rates.get(clean_symbol, {}).get('funding_rate', 0))
            except:
                pass
        return 0.0
    
    def _load_open_interest(self, symbol: str) -> Dict[str, float]:
        """Load cached open interest with 1h change percentage."""
        oi_path = Path("feature_store/intelligence/open_interest.json")
        if oi_path.exists():
            try:
                data = json.loads(oi_path.read_text())
                oi_data = data.get('oi', data)
                clean_symbol = symbol.upper().replace('USDT', '').replace('-USDT', '')
                symbol_data = oi_data.get(clean_symbol, {})
                return {
                    'open_interest': float(symbol_data.get('open_interest', 0) or 0),
                    'oi_change_1h': float(symbol_data.get('oi_change_1h', 0) or 0),
                    'oi_change_24h': float(symbol_data.get('oi_change_24h', 0) or 0),
                    'oi_signal': int(symbol_data.get('oi_signal', 0) or 0)
                }
            except:
                pass
        return {'open_interest': 0.0, 'oi_change_1h': 0.0, 'oi_change_24h': 0.0, 'oi_signal': 0}
    
    def generate_signal(self, symbol: str, current_ofi: float, current_price: float,
                       price_direction: int = 0) -> Dict[str, Any]:
        """
        Generate a comprehensive predictive signal.
        
        Args:
            symbol: Trading symbol (e.g., 'BTC', 'ETH')
            current_ofi: Current order flow imbalance (-1 to 1)
            current_price: Current price
            price_direction: Recent price direction (1=up, -1=down, 0=flat)
        
        Returns:
            {
                'symbol': str,
                'direction': 'LONG' | 'SHORT' | 'NEUTRAL',
                'conviction': 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE',
                'confidence': float (0-1),
                'size_multiplier': float,
                'should_trade': bool,
                'signals': {...},  # Individual signal details
                'aligned_signals': int,
                'reasons': list
            }
        """
        self.ofi_tracker.record_reading(symbol, current_ofi, current_price)
        
        intel_data = self._load_intelligence_data(symbol)
        onchain_data = self._load_onchain_data(symbol)
        funding_rate = self._load_funding_rate(symbol)
        oi_data = self._load_open_interest(symbol)
        
        signals = {}
        
        signals['ofi_momentum'] = self.ofi_tracker.get_momentum_signal(
            symbol, current_ofi, current_price
        )
        
        signals['funding'] = self.funding_signal.compute_signal(funding_rate)
        
        thresholds = _get_signal_thresholds()
        oi_min_pct = thresholds.get('oi_velocity_min_pct', 2.0)
        oi_change_1h = oi_data.get('oi_change_1h', 0)
        if abs(oi_change_1h) > oi_min_pct:
            if oi_change_1h > oi_min_pct and price_direction > 0:
                signals['oi_velocity'] = {
                    'signal': 'LONG',
                    'confidence': min(1.0, abs(oi_change_1h) / (oi_min_pct * 5)),
                    'oi_velocity': oi_change_1h / 100,
                    'reasons': ['rising_oi_rising_price', 'new_longs_entering', 'cached_oi']
                }
            elif oi_change_1h > oi_min_pct and price_direction < 0:
                signals['oi_velocity'] = {
                    'signal': 'SHORT',
                    'confidence': min(1.0, abs(oi_change_1h) / (oi_min_pct * 5)),
                    'oi_velocity': oi_change_1h / 100,
                    'reasons': ['rising_oi_falling_price', 'new_shorts_entering', 'cached_oi']
                }
            elif oi_change_1h < -oi_min_pct:
                reversal_signal = 'SHORT' if price_direction > 0 else ('LONG' if price_direction < 0 else 'NEUTRAL')
                signals['oi_velocity'] = {
                    'signal': reversal_signal,
                    'confidence': min(0.7, abs(oi_change_1h) / (oi_min_pct * 5)),
                    'oi_velocity': oi_change_1h / 100,
                    'reasons': ['falling_oi', 'positions_closing', 'cached_oi']
                }
            else:
                signals['oi_velocity'] = self.oi_velocity.compute_signal(
                    symbol, oi_data.get('open_interest', 0), price_direction
                )
        else:
            signals['oi_velocity'] = self.oi_velocity.compute_signal(
                symbol, oi_data.get('open_interest', 0), price_direction
            )
        
        liq = intel_data.get('liquidation', {})
        signals['liquidation'] = self.liquidation_detector.compute_signal(
            liq.get('liq_1h_long', 0),
            liq.get('liq_1h_short', 0),
            liq.get('liq_4h_long', 0),
            liq.get('liq_4h_short', 0)
        )
        
        signals['whale_flow'] = self.whale_flow.compute_signal(
            onchain_data.get('net_flow', 0),
            onchain_data.get('inflows', 0),
            onchain_data.get('outflows', 0)
        )
        
        fear_greed_value = intel_data.get('fear_greed', 50)
        signals['fear_greed'] = self.fear_greed.compute_signal(fear_greed_value)
        
        # Hurst Exponent signal - regime detection (trending vs mean-reverting)
        try:
            from src.hurst_exponent import get_hurst_signal
            clean_symbol = symbol.upper().replace('-', '')
            if not clean_symbol.endswith('USDT'):
                clean_symbol = f"{clean_symbol}USDT"
            hurst_signal = get_hurst_signal(clean_symbol)
            signals['hurst'] = {
                'signal': hurst_signal.get('direction', 'NEUTRAL'),
                'confidence': hurst_signal.get('confidence', 0),
                'hurst_value': hurst_signal.get('hurst_value', 0.5),
                'regime': hurst_signal.get('regime', 'unknown'),
                'reasons': [f"hurst_{hurst_signal.get('regime', 'unknown')}", hurst_signal.get('interpretation', '')]
            }
        except Exception as e:
            signals['hurst'] = {
                'signal': 'NEUTRAL',
                'confidence': 0,
                'hurst_value': 0.5,
                'regime': 'unknown',
                'reasons': ['hurst_calculation_failed']
            }
        
        # Lead-Lag signal - BTC/ETH leads altcoins
        try:
            from src.lead_lag_signal import get_lead_lag_signal
            clean_symbol = symbol.upper().replace('-', '')
            if not clean_symbol.endswith('USDT'):
                clean_symbol = f"{clean_symbol}USDT"
            lead_lag_result = get_lead_lag_signal(clean_symbol)
            signals['lead_lag'] = {
                'signal': lead_lag_result.get('signal', 'NEUTRAL'),
                'confidence': lead_lag_result.get('confidence', 0),
                'optimal_lag': lead_lag_result.get('optimal_lag', 0),
                'correlation': lead_lag_result.get('correlation', 0),
                'leader_direction': lead_lag_result.get('leader_direction', 'NEUTRAL'),
                'reasons': lead_lag_result.get('reasons', [])
            }
        except Exception as e:
            signals['lead_lag'] = {
                'signal': 'NEUTRAL',
                'confidence': 0,
                'optimal_lag': 0,
                'correlation': 0,
                'leader_direction': 'NEUTRAL',
                'reasons': ['lead_lag_calculation_failed']
            }
        
        # Volatility Skew signal - behavioral economics (loss aversion / complacency)
        try:
            from src.volatility_skew_signal import get_volatility_skew_signal
            clean_symbol = symbol.upper().replace('-', '')
            if not clean_symbol.endswith('USDT'):
                clean_symbol = f"{clean_symbol}USDT"
            skew_result = get_volatility_skew_signal(clean_symbol)
            signals['volatility_skew'] = {
                'signal': skew_result.get('signal', 'NEUTRAL'),
                'confidence': skew_result.get('confidence', 0),
                'skew_value': skew_result.get('skew_value', 0),
                'interpretation': skew_result.get('skew_interpretation', 'unknown'),
                'quantile': skew_result.get('quantile', 0.5),
                'reasons': skew_result.get('reasons', [])
            }
        except Exception as e:
            signals['volatility_skew'] = {
                'signal': 'NEUTRAL',
                'confidence': 0,
                'skew_value': 0,
                'interpretation': 'unknown',
                'quantile': 0.5,
                'reasons': ['volatility_skew_failed']
            }
        
        # OI Divergence signal - game theory trap detection
        try:
            from src.oi_divergence_signal import get_oi_divergence_signal
            clean_symbol = symbol.upper().replace('-', '')
            if not clean_symbol.endswith('USDT'):
                clean_symbol = f"{clean_symbol}USDT"
            divergence_result = get_oi_divergence_signal(clean_symbol)
            signals['oi_divergence'] = {
                'signal': divergence_result.get('signal', 'NEUTRAL'),
                'confidence': divergence_result.get('confidence', 0),
                'trap_type': divergence_result.get('trap_type', 'none'),
                'price_change': divergence_result.get('price_change', 0),
                'oi_change': divergence_result.get('oi_change', 0),
                'divergence_ratio': divergence_result.get('divergence_ratio', 0),
                'reasons': divergence_result.get('reasons', [])
            }
        except Exception as e:
            signals['oi_divergence'] = {
                'signal': 'NEUTRAL',
                'confidence': 0,
                'trap_type': 'none',
                'price_change': 0,
                'oi_change': 0,
                'divergence_ratio': 0,
                'reasons': ['oi_divergence_failed']
            }
        
        long_votes = 0
        short_votes = 0
        weighted_confidence = 0.0
        aligned_signals = 0
        all_reasons = []
        
        for signal_name, signal_data in signals.items():
            direction = signal_data.get('signal', 'NEUTRAL')
            confidence = signal_data.get('confidence', 0)
            weight = self.SIGNAL_WEIGHTS.get(signal_name, 0.1)
            
            if direction == 'LONG' or direction == 'STRONG_LONG':
                long_votes += 1
                weighted_confidence += confidence * weight
                if confidence > 0.3:
                    aligned_signals += 1
                    all_reasons.extend(signal_data.get('reasons', []))
            elif direction == 'SHORT' or direction == 'STRONG_SHORT':
                short_votes += 1
                weighted_confidence += confidence * weight
                if confidence > 0.3:
                    aligned_signals += 1
                    all_reasons.extend(signal_data.get('reasons', []))
        
        total_signals = len(signals)  # Currently 10 signals
        
        if long_votes > short_votes and long_votes >= 2:
            final_direction = 'LONG'
            alignment_score = long_votes / total_signals
        elif short_votes > long_votes and short_votes >= 2:
            final_direction = 'SHORT'
            alignment_score = short_votes / total_signals
        else:
            final_direction = 'NEUTRAL'
            alignment_score = 0
        
        conviction = 'NONE'
        for level in ['HIGH', 'MEDIUM', 'LOW']:
            thresholds = self.CONVICTION_THRESHOLDS[level]
            if aligned_signals >= thresholds['min_signals'] and weighted_confidence >= thresholds['min_confidence']:
                conviction = level
                break
        
        should_trade = conviction in ['HIGH', 'MEDIUM'] and final_direction != 'NEUTRAL'
        size_multiplier = self.CONVICTION_THRESHOLDS[conviction]['size_multiplier']
        
        result = {
            'symbol': symbol,
            'direction': final_direction,
            'conviction': conviction,
            'confidence': round(weighted_confidence, 3),
            'size_multiplier': size_multiplier,
            'should_trade': should_trade,
            'signals': signals,
            'aligned_signals': aligned_signals,
            'alignment_score': round(alignment_score, 2),
            'long_votes': long_votes,
            'short_votes': short_votes,
            'reasons': all_reasons[:10],
            'paper_mode': PAPER_MODE,
            'ts': datetime.utcnow().isoformat()
        }
        
        try:
            with open(PREDICTION_LOG, 'a') as f:
                f.write(json.dumps(result) + '\n')
        except:
            pass
        
        return result


_engine_instance = None

def get_predictive_engine() -> PredictiveFlowEngine:
    """Get singleton engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PredictiveFlowEngine()
    return _engine_instance


def generate_predictive_signal(symbol: str, current_ofi: float = 0.0, 
                               current_price: float = 0.0,
                               price_direction: int = 0) -> Dict[str, Any]:
    """
    Convenience function for generating predictive signals.
    
    This replaces the old snapshot-based OFI signal system.
    """
    engine = get_predictive_engine()
    return engine.generate_signal(symbol, current_ofi, current_price, price_direction)


def is_paper_mode() -> bool:
    """Check if running in paper mode."""
    return PAPER_MODE


def reload_config():
    """Reload configuration at runtime."""
    global PAPER_MODE, SIGNAL_THRESHOLDS, _mode_logged
    PAPER_MODE = _get_paper_mode()
    SIGNAL_THRESHOLDS = _get_signal_thresholds()
    _mode_logged = False
    _log_mode_once()


if __name__ == "__main__":
    print("=" * 60)
    print("PREDICTIVE FLOW ENGINE - Test")
    print("=" * 60)
    
    print(f"\nPaper Mode: {PAPER_MODE}")
    print(f"Signal Thresholds: {json.dumps(SIGNAL_THRESHOLDS, indent=2)}")
    
    engine = get_predictive_engine()
    
    for i in range(5):
        engine.ofi_tracker.record_reading('BTC', 0.3 + i * 0.1, 95000 + i * 100)
        time.sleep(0.1)
    
    signal = engine.generate_signal('BTC', 0.7, 95400, 1)
    
    print(f"\nSymbol: {signal['symbol']}")
    print(f"Direction: {signal['direction']}")
    print(f"Conviction: {signal['conviction']}")
    print(f"Confidence: {signal['confidence']}")
    print(f"Should Trade: {signal['should_trade']}")
    print(f"Size Multiplier: {signal['size_multiplier']}")
    print(f"Aligned Signals: {signal['aligned_signals']}/6")
    print(f"Paper Mode: {signal['paper_mode']}")
    print(f"\nReasons: {', '.join(signal['reasons'][:5])}")
    
    print("\n" + "=" * 60)
    print("Individual Signals:")
    for name, data in signal['signals'].items():
        print(f"\n  {name}:")
        print(f"    Signal: {data.get('signal', 'N/A')}")
        print(f"    Confidence: {data.get('confidence', 0):.3f}")
        print(f"    Reasons: {data.get('reasons', [])}")
