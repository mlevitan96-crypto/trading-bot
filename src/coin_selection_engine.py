"""
Coin Selection Engine - Picks the RIGHT coin before trading.

This engine runs in parallel with existing learning to:
1. Rank coins by direction accuracy (from learning data)
2. Gate trades on low-accuracy coins
3. Boost sizing on high-accuracy coins
4. Track both trend-following (longer) and scalping (quick) opportunities
5. Learn which coin+direction+condition combos actually make money

The #1 goal is profitability through intelligent coin selection.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

COIN_PROFILES_PATH = "feature_store/coin_profiles.json"
DAILY_RULES_PATH = "feature_store/daily_learning_rules.json"
FEEDBACK_SUMMARY_PATH = "feature_store/feedback_loop_summary.json"
SELECTION_LOG_PATH = "logs/coin_selection.jsonl"
SELECTION_STATE_PATH = "feature_store/coin_selection_state.json"

MIN_DIRECTION_ACCURACY = 0.58
HIGH_ACCURACY_THRESHOLD = 0.70
ELITE_ACCURACY_THRESHOLD = 0.80

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _log(msg: str):
    ts = datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] [COIN-SELECT] {msg}")

def _read_json(path: str, default=None):
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except:
        pass
    return default if default is not None else {}

def _write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def _append_jsonl(path: str, record: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record) + '\n')


class CoinSelectionEngine:
    """
    Intelligent coin selection based on learned direction accuracy and patterns.
    
    Strategy:
    - FOCUS on coins where we predict direction correctly (>60%)
    - SIZE UP on elite coins (>80% accuracy)
    - SKIP or SIZE DOWN on random coins (<58% accuracy)
    - TRACK both long-term trends and short-term scalps
    """
    
    def __init__(self):
        self.coin_profiles = {}
        self.daily_rules = {}
        self.direction_accuracy = {}
        self.profitable_patterns = {}
        self.coin_rankings = []
        self.load_data()
    
    def load_data(self):
        """Load all learning data."""
        self.coin_profiles = _read_json(COIN_PROFILES_PATH, {})
        self.daily_rules = _read_json(DAILY_RULES_PATH, {})
        self.profitable_patterns = self.daily_rules.get("profitable_patterns", {})
        
        for symbol, profile in self.coin_profiles.items():
            if symbol.startswith("_"):
                continue
            acc = profile.get("direction_accuracy", 0.5)
            self.direction_accuracy[symbol] = acc
        
        self._rank_coins()
        _log(f"Loaded {len(self.direction_accuracy)} coins, {len(self.profitable_patterns)} profitable patterns")
    
    def _rank_coins(self):
        """Rank coins by direction accuracy and profitability."""
        rankings = []
        
        for symbol, accuracy in self.direction_accuracy.items():
            profit_score = self._get_profit_score(symbol)
            
            composite_score = (accuracy * 0.6) + (profit_score * 0.4)
            
            tier = "SKIP"
            if accuracy >= ELITE_ACCURACY_THRESHOLD:
                tier = "ELITE"
            elif accuracy >= HIGH_ACCURACY_THRESHOLD:
                tier = "HIGH"
            elif accuracy >= MIN_DIRECTION_ACCURACY:
                tier = "STANDARD"
            
            rankings.append({
                "symbol": symbol,
                "direction_accuracy": accuracy,
                "profit_score": profit_score,
                "composite_score": composite_score,
                "tier": tier
            })
        
        self.coin_rankings = sorted(rankings, key=lambda x: x["composite_score"], reverse=True)
    
    def _get_profit_score(self, symbol: str) -> float:
        """Calculate profit score from profitable patterns."""
        total_pnl = 0
        pattern_count = 0
        
        for pattern_key, data in self.profitable_patterns.items():
            if f"sym={symbol}" in pattern_key:
                total_pnl += data.get("pnl", 0)
                pattern_count += 1
        
        if pattern_count == 0:
            return 0.5
        
        if total_pnl > 10:
            return 1.0
        elif total_pnl > 5:
            return 0.8
        elif total_pnl > 0:
            return 0.6
        else:
            return 0.4
    
    def should_trade_coin(self, symbol: str, direction: str = None) -> Tuple[bool, str, float]:
        """
        Determine if we should trade this coin.
        
        Returns:
            (should_trade, reason, size_multiplier)
        """
        accuracy = self.direction_accuracy.get(symbol, 0.5)
        
        for pattern_key, data in self.profitable_patterns.items():
            if f"sym={symbol}" in pattern_key:
                if direction and f"dir={direction}" in pattern_key:
                    wr = data.get("wr", 0)
                    if wr >= 60 and data.get("pnl", 0) > 0:
                        mult = min(1.5, data.get("size_multiplier", 1.0))
                        _log(f"✅ PROVEN PATTERN: {symbol} {direction} (WR={wr}%, mult={mult})")
                        return True, f"proven_pattern_{pattern_key}", mult
        
        if accuracy >= ELITE_ACCURACY_THRESHOLD:
            mult = 1.3
            _log(f"🔥 ELITE COIN: {symbol} ({accuracy*100:.0f}% accuracy, mult={mult})")
            return True, "elite_accuracy", mult
        
        elif accuracy >= HIGH_ACCURACY_THRESHOLD:
            mult = 1.15
            _log(f"✅ HIGH ACCURACY: {symbol} ({accuracy*100:.0f}% accuracy, mult={mult})")
            return True, "high_accuracy", mult
        
        elif accuracy >= MIN_DIRECTION_ACCURACY:
            mult = 1.0
            _log(f"📊 STANDARD: {symbol} ({accuracy*100:.0f}% accuracy)")
            return True, "standard_accuracy", mult
        
        else:
            mult = 0.5
            _log(f"⚠️ LOW ACCURACY: {symbol} ({accuracy*100:.0f}% - sizing down)")
            return True, "low_accuracy_reduced", mult
    
    def get_best_coins(self, n: int = 5, direction: str = None) -> List[Dict]:
        """Get the top N coins to trade right now."""
        candidates = []
        
        for ranking in self.coin_rankings:
            symbol = ranking["symbol"]
            tier = ranking["tier"]
            
            if tier == "SKIP":
                continue
            
            if direction:
                has_pattern = any(
                    f"sym={symbol}" in k and f"dir={direction}" in k
                    for k in self.profitable_patterns.keys()
                )
                if has_pattern:
                    ranking["has_proven_pattern"] = True
            
            candidates.append(ranking)
        
        candidates_with_patterns = [c for c in candidates if c.get("has_proven_pattern")]
        candidates_without = [c for c in candidates if not c.get("has_proven_pattern")]
        
        final = candidates_with_patterns + candidates_without
        return final[:n]
    
    def get_direction_bias(self, symbol: str) -> Tuple[str, float]:
        """
        Get the preferred direction for a coin based on learning.
        
        Returns:
            (preferred_direction, confidence)
        """
        long_score = 0
        short_score = 0
        
        for pattern_key, data in self.profitable_patterns.items():
            if f"sym={symbol}" not in pattern_key:
                continue
            
            pnl = data.get("pnl", 0)
            wr = data.get("wr", 0)
            ev = data.get("ev", 0)
            
            score = (pnl * 0.3) + (wr * 0.01) + (ev * 0.5)
            
            if "dir=LONG" in pattern_key:
                long_score += score
            elif "dir=SHORT" in pattern_key:
                short_score += score
        
        if long_score > short_score and long_score > 0:
            confidence = min(0.9, long_score / (long_score + abs(short_score) + 0.1))
            return "LONG", confidence
        elif short_score > long_score and short_score > 0:
            confidence = min(0.9, short_score / (short_score + abs(long_score) + 0.1))
            return "SHORT", confidence
        else:
            return "NEUTRAL", 0.5
    
    def score_opportunity(self, symbol: str, direction: str, ofi_bucket: str, 
                          ensemble_bucket: str, session: str) -> Dict:
        """
        Score a trading opportunity based on all learned factors.
        
        Returns comprehensive scoring for entry decision.
        """
        score = 0
        factors = []
        
        accuracy = self.direction_accuracy.get(symbol, 0.5)
        if accuracy >= ELITE_ACCURACY_THRESHOLD:
            score += 30
            factors.append(f"elite_accuracy_{accuracy*100:.0f}pct")
        elif accuracy >= HIGH_ACCURACY_THRESHOLD:
            score += 20
            factors.append(f"high_accuracy_{accuracy*100:.0f}pct")
        elif accuracy >= MIN_DIRECTION_ACCURACY:
            score += 10
            factors.append("standard_accuracy")
        else:
            score -= 10
            factors.append("low_accuracy_penalty")
        
        pattern_key_partial = f"sym={symbol}|dir={direction}"
        for key, data in self.profitable_patterns.items():
            if pattern_key_partial in key:
                pnl = data.get("pnl", 0)
                wr = data.get("wr", 0)
                if pnl > 5 and wr >= 50:
                    score += 25
                    factors.append(f"strong_pattern_{key}")
                elif pnl > 0:
                    score += 15
                    factors.append(f"positive_pattern_{key}")
        
        ofi_pattern = f"sym={symbol}|ofi={ofi_bucket}"
        for key, data in self.profitable_patterns.items():
            if ofi_pattern in key and data.get("pnl", 0) > 0:
                score += 10
                factors.append(f"ofi_match_{ofi_bucket}")
                break
        
        ens_pattern = f"sym={symbol}|ens={ensemble_bucket}"
        for key, data in self.profitable_patterns.items():
            if ens_pattern in key and data.get("pnl", 0) > 0:
                score += 10
                factors.append(f"ensemble_match_{ensemble_bucket}")
                break
        
        dir_bias, dir_conf = self.get_direction_bias(symbol)
        if dir_bias == direction and dir_conf > 0.6:
            score += 15
            factors.append(f"direction_aligned_{dir_conf:.2f}")
        elif dir_bias != "NEUTRAL" and dir_bias != direction:
            score -= 15
            factors.append(f"direction_conflict_{dir_bias}")
        
        grade = "F"
        size_mult = 0.5
        if score >= 60:
            grade = "A"
            size_mult = 1.4
        elif score >= 45:
            grade = "B"
            size_mult = 1.2
        elif score >= 30:
            grade = "C"
            size_mult = 1.0
        elif score >= 15:
            grade = "D"
            size_mult = 0.75
        else:
            grade = "F"
            size_mult = 0.5
        
        result = {
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "grade": grade,
            "size_multiplier": size_mult,
            "factors": factors,
            "direction_accuracy": accuracy,
            # Allow all grades to trade but with reduced sizing - we need live data to learn
            # Grade A/B/C: full confidence, Grade D: reduced, Grade F: minimum size
            "should_trade": True,  # Always allow - size multiplier controls risk
            "ts": _now()
        }
        
        _append_jsonl(SELECTION_LOG_PATH, result)
        
        return result
    
    def get_focus_list(self) -> Dict:
        """
        Get the current focus list - coins we should prioritize.
        
        This is the CEO view: which coins should we be watching?
        """
        focus = {
            "elite_coins": [],
            "high_accuracy": [],
            "proven_patterns": [],
            "avoid_list": [],
            "direction_biases": {},
            "generated_at": _now()
        }
        
        for ranking in self.coin_rankings:
            symbol = ranking["symbol"]
            tier = ranking["tier"]
            
            if tier == "ELITE":
                focus["elite_coins"].append({
                    "symbol": symbol,
                    "accuracy": ranking["direction_accuracy"],
                    "profit_score": ranking["profit_score"]
                })
            elif tier == "HIGH":
                focus["high_accuracy"].append({
                    "symbol": symbol,
                    "accuracy": ranking["direction_accuracy"]
                })
            elif tier == "SKIP":
                focus["avoid_list"].append({
                    "symbol": symbol,
                    "accuracy": ranking["direction_accuracy"],
                    "reason": "below_threshold"
                })
            
            dir_bias, conf = self.get_direction_bias(symbol)
            if dir_bias != "NEUTRAL":
                focus["direction_biases"][symbol] = {
                    "direction": dir_bias,
                    "confidence": conf
                }
        
        for pattern_key, data in self.profitable_patterns.items():
            if data.get("wr", 0) >= 60 and data.get("pnl", 0) > 3:
                focus["proven_patterns"].append({
                    "pattern": pattern_key,
                    "win_rate": data.get("wr"),
                    "pnl": data.get("pnl"),
                    "ev": data.get("ev")
                })
        
        _write_json(SELECTION_STATE_PATH, focus)
        
        return focus
    
    def print_rankings(self):
        """Print current coin rankings for visibility."""
        print("\n" + "="*60)
        print("🎯 COIN SELECTION ENGINE - CURRENT RANKINGS")
        print("="*60)
        
        for i, r in enumerate(self.coin_rankings[:10], 1):
            tier_emoji = {"ELITE": "🔥", "HIGH": "✅", "STANDARD": "📊", "SKIP": "⚠️"}.get(r["tier"], "❓")
            print(f"{i:2}. {tier_emoji} {r['symbol']:12} | Accuracy: {r['direction_accuracy']*100:5.1f}% | "
                  f"Profit: {r['profit_score']:.2f} | Tier: {r['tier']}")
        
        print("-"*60)
        
        print("\n📈 DIRECTION BIASES:")
        for symbol in [r["symbol"] for r in self.coin_rankings[:8]]:
            bias, conf = self.get_direction_bias(symbol)
            if bias != "NEUTRAL":
                print(f"   {symbol}: {bias} (confidence: {conf:.0%})")
        
        print("="*60 + "\n")


_engine_instance: Optional[CoinSelectionEngine] = None

def get_engine() -> CoinSelectionEngine:
    """Get or create the singleton engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = CoinSelectionEngine()
    return _engine_instance

def refresh_engine():
    """Reload all data into the engine."""
    global _engine_instance
    _engine_instance = CoinSelectionEngine()
    return _engine_instance


def should_trade_coin(symbol: str, direction: str = None) -> Tuple[bool, str, float]:
    """Quick check if we should trade this coin."""
    return get_engine().should_trade_coin(symbol, direction)


def score_opportunity(symbol: str, direction: str, ofi_bucket: str = "moderate",
                      ensemble_bucket: str = "neutral", session: str = "us_morning") -> Dict:
    """Score a trading opportunity."""
    return get_engine().score_opportunity(symbol, direction, ofi_bucket, ensemble_bucket, session)


def get_focus_list() -> Dict:
    """Get the current focus list."""
    return get_engine().get_focus_list()


def get_best_coins(n: int = 5, direction: str = None) -> List[Dict]:
    """Get top N coins to trade."""
    return get_engine().get_best_coins(n, direction)


if __name__ == "__main__":
    engine = CoinSelectionEngine()
    engine.print_rankings()
    
    print("\n🎯 FOCUS LIST:")
    focus = engine.get_focus_list()
    
    print(f"\nElite Coins: {[c['symbol'] for c in focus['elite_coins']]}")
    print(f"High Accuracy: {[c['symbol'] for c in focus['high_accuracy']]}")
    print(f"Avoid List: {[c['symbol'] for c in focus['avoid_list']]}")
    
    print("\n📊 Sample Opportunity Scoring:")
    for symbol in ["DOTUSDT", "AVAXUSDT", "BTCUSDT"]:
        result = engine.score_opportunity(symbol, "SHORT", "strong", "strong_bear", "us_morning")
        print(f"   {symbol} SHORT: Grade={result['grade']}, Score={result['score']}, "
              f"SizeMult={result['size_multiplier']:.2f}")
