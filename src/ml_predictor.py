"""
ML PREDICTOR - Actual Machine Learning for Trade Direction
============================================================
Trains per-coin gradient boost classifiers on historical outcomes.
Uses market intelligence features to predict profitable trade direction.
"""

import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
import pickle

POSITIONS_FILE = "logs/positions_futures.json"
INTELLIGENCE_DIR = "feature_store/intelligence"
ANOMALY_FILE = "feature_store/anomaly_dates.json"
MODEL_DIR = "models"
TRAINING_DATA_FILE = "feature_store/training_dataset.json"


def load_anomaly_dates() -> set:
    """Load dates to exclude from training."""
    try:
        with open(ANOMALY_FILE, 'r') as f:
            data = json.load(f)
        return {a["date"] for a in data.get("anomalies", []) if a.get("action") == "exclude_from_analysis"}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def load_positions() -> List[Dict]:
    """Load closed positions excluding anomalies."""
    with open(POSITIONS_FILE, 'r') as f:
        data = json.load(f)
    
    closed = data.get('closed_positions', [])
    anomaly_dates = load_anomaly_dates()
    
    clean = []
    for pos in closed:
        size = pos.get('size', 0) or 0
        fees = pos.get('trading_fees', 0) or 0
        
        if not (0 < size < 1000 and fees < 10):
            continue
        
        opened = pos.get('opened_at', '')
        if opened:
            date = opened.split('T')[0]
            if date in anomaly_dates:
                continue
        
        clean.append(pos)
    
    return clean


def load_latest_intelligence(symbol: str) -> Optional[Dict]:
    """Load latest intelligence for a symbol."""
    base_symbol = symbol.replace("USDT", "")
    intel_file = f"{INTELLIGENCE_DIR}/{symbol}_intel.json"
    
    try:
        with open(intel_file, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def extract_features(pos: Dict, intel: Optional[Dict] = None) -> Dict:
    """Extract features for a trade."""
    features = {}
    
    opened = pos.get('opened_at', '')
    if opened and 'T' in opened:
        try:
            hour = int(opened.split('T')[1].split(':')[0])
            features['hour'] = hour
            features['hour_sin'] = __import__('math').sin(2 * __import__('math').pi * hour / 24)
            features['hour_cos'] = __import__('math').cos(2 * __import__('math').pi * hour / 24)
        except (ValueError, IndexError):
            features['hour'] = 12
            features['hour_sin'] = 0
            features['hour_cos'] = 1
    
    features['size'] = pos.get('size', 0) or 0
    features['leverage'] = pos.get('leverage', 1) or 1
    
    if intel:
        taker = intel.get('taker', {})
        features['buy_sell_ratio'] = taker.get('buy_sell_ratio', 1.0)
        features['buy_ratio'] = taker.get('buy_ratio', 0.5)
        features['sell_ratio'] = taker.get('sell_ratio', 0.5)
        
        liq = intel.get('liquidation', {})
        features['liq_ratio'] = liq.get('liq_ratio', 0.5)
        features['liq_long_24h'] = liq.get('liq_long_24h', 0) / 1e9
        features['liq_short_24h'] = liq.get('liq_short_24h', 0) / 1e9
        features['liq_1h_long'] = liq.get('liq_1h_long', 0) / 1e6
        features['liq_1h_short'] = liq.get('liq_1h_short', 0) / 1e6
        
        features['fear_greed'] = intel.get('fear_greed', 50) / 100.0
        
        signal = intel.get('signal', {})
        features['intel_confidence'] = signal.get('confidence', 0)
        features['intel_composite'] = signal.get('composite', 0)
    else:
        features['buy_sell_ratio'] = 1.0
        features['buy_ratio'] = 0.5
        features['sell_ratio'] = 0.5
        features['liq_ratio'] = 0.5
        features['liq_long_24h'] = 0
        features['liq_short_24h'] = 0
        features['liq_1h_long'] = 0
        features['liq_1h_short'] = 0
        features['fear_greed'] = 0.5
        features['intel_confidence'] = 0
        features['intel_composite'] = 0
    
    return features


def build_training_dataset() -> Dict:
    """Build labeled training dataset from historical trades."""
    print("=" * 80)
    print("BUILDING TRAINING DATASET")
    print("=" * 80)
    
    positions = load_positions()
    print(f"Loaded {len(positions)} clean positions")
    
    by_symbol = defaultdict(list)
    for pos in positions:
        symbol = pos.get('symbol', 'UNKNOWN')
        direction = pos.get('direction', 'UNKNOWN')
        
        net_pnl = pos.get('net_pnl', pos.get('pnl', 0)) or 0
        gross_pnl = net_pnl + (pos.get('trading_fees', 0) or 0)
        
        is_win = gross_pnl > 0
        
        intel = load_latest_intelligence(symbol)
        features = extract_features(pos, intel)
        
        features['direction'] = 1 if direction == 'LONG' else 0
        
        sample = {
            'symbol': symbol,
            'direction': direction,
            'features': features,
            'label': 1 if is_win else 0,
            'net_pnl': net_pnl,
            'gross_pnl': gross_pnl,
            'opened_at': pos.get('opened_at', '')
        }
        
        by_symbol[symbol].append(sample)
    
    dataset = {
        'created': datetime.utcnow().isoformat() + 'Z',
        'total_samples': len(positions),
        'by_symbol': {}
    }
    
    for symbol, samples in by_symbol.items():
        wins = sum(1 for s in samples if s['label'] == 1)
        total = len(samples)
        
        dataset['by_symbol'][symbol] = {
            'samples': samples,
            'total': total,
            'wins': wins,
            'win_rate': wins / total * 100 if total > 0 else 0
        }
        
        print(f"  {symbol}: {total} samples, {wins} wins ({wins/total*100:.1f}% WR)")
    
    with open(TRAINING_DATA_FILE, 'w') as f:
        json.dump(dataset, f, indent=2)
    
    print(f"\nDataset saved to {TRAINING_DATA_FILE}")
    
    return dataset


def train_models(dataset: Dict) -> Dict:
    """Train per-symbol gradient boost classifiers."""
    print("\n" + "=" * 80)
    print("TRAINING ML MODELS")
    print("=" * 80)
    
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score
        import numpy as np
    except ImportError:
        print("ERROR: scikit-learn not available. Installing...")
        return {"error": "sklearn not installed"}
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    feature_names = [
        'hour_sin', 'hour_cos', 'size', 'leverage',
        'buy_sell_ratio', 'buy_ratio', 'sell_ratio',
        'liq_ratio', 'liq_long_24h', 'liq_short_24h',
        'liq_1h_long', 'liq_1h_short', 'fear_greed',
        'intel_confidence', 'intel_composite', 'direction'
    ]
    
    results = {}
    
    for symbol, data in dataset.get('by_symbol', {}).items():
        samples = data.get('samples', [])
        
        if len(samples) < 30:
            print(f"  {symbol}: Skipping (only {len(samples)} samples, need 30+)")
            continue
        
        X = []
        y = []
        
        for sample in samples:
            features = sample.get('features', {})
            row = [features.get(f, 0) for f in feature_names]
            X.append(row)
            y.append(sample.get('label', 0))
        
        X = np.array(X)
        y = np.array(y)
        
        model = GradientBoostingClassifier(
            n_estimators=50,
            max_depth=3,
            min_samples_leaf=5,
            random_state=42
        )
        
        try:
            cv_scores = cross_val_score(model, X, y, cv=min(5, len(samples)//10 or 2), scoring='accuracy')
            mean_cv = cv_scores.mean()
            
            model.fit(X, y)
            
            train_preds = model.predict(X)
            train_acc = (train_preds == y).mean()
            
            feature_importance = dict(zip(feature_names, model.feature_importances_))
            top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:5]
            
            model_path = f"{MODEL_DIR}/{symbol}_model.pkl"
            with open(model_path, 'wb') as f:
                pickle.dump({'model': model, 'feature_names': feature_names}, f)
            
            results[symbol] = {
                'samples': len(samples),
                'base_win_rate': data.get('win_rate', 50),
                'cv_accuracy': round(mean_cv * 100, 2),
                'train_accuracy': round(train_acc * 100, 2),
                'improvement': round((mean_cv * 100) - data.get('win_rate', 50), 2),
                'top_features': top_features,
                'model_path': model_path
            }
            
            print(f"\n  {symbol}:")
            print(f"    Samples: {len(samples)}")
            print(f"    Base WR: {data.get('win_rate', 50):.1f}%")
            print(f"    CV Accuracy: {mean_cv*100:.1f}%")
            print(f"    Improvement: {(mean_cv*100) - data.get('win_rate', 50):+.1f}%")
            print(f"    Top features: {[f[0] for f in top_features[:3]]}")
            
        except Exception as e:
            print(f"  {symbol}: Training failed - {e}")
            results[symbol] = {'error': str(e)}
    
    summary_path = f"{MODEL_DIR}/training_summary.json"
    with open(summary_path, 'w') as f:
        json.dump({
            'trained_at': datetime.utcnow().isoformat() + 'Z',
            'results': results
        }, f, indent=2)
    
    return results


def predict(symbol: str, features: Dict) -> Tuple[str, float]:
    """Make prediction using trained model."""
    model_path = f"{MODEL_DIR}/{symbol}_model.pkl"
    
    if not os.path.exists(model_path):
        return 'UNKNOWN', 0.0
    
    try:
        import numpy as np
        
        with open(model_path, 'rb') as f:
            data = pickle.load(f)
        
        model = data['model']
        feature_names = data['feature_names']
        
        X = np.array([[features.get(f, 0) for f in feature_names]])
        
        prob = model.predict_proba(X)[0]
        pred = model.predict(X)[0]
        
        confidence = max(prob)
        direction = 'LONG' if pred == 1 else 'SHORT'
        
        return direction, confidence
        
    except Exception as e:
        return 'UNKNOWN', 0.0


def run_training_pipeline():
    """Run complete training pipeline."""
    print("=" * 80)
    print("ML PREDICTION TRAINING PIPELINE")
    print("=" * 80)
    print()
    
    dataset = build_training_dataset()
    
    results = train_models(dataset)
    
    print("\n" + "=" * 80)
    print("TRAINING SUMMARY")
    print("=" * 80)
    
    improvements = []
    for symbol, data in results.items():
        if 'improvement' in data:
            improvements.append((symbol, data['improvement'], data['cv_accuracy']))
    
    if improvements:
        avg_improvement = sum(i[1] for i in improvements) / len(improvements)
        avg_accuracy = sum(i[2] for i in improvements) / len(improvements)
        
        print(f"\nModels trained: {len(improvements)}")
        print(f"Average CV Accuracy: {avg_accuracy:.1f}%")
        print(f"Average Improvement over Base: {avg_improvement:+.1f}%")
        
        print("\nBest performers:")
        for symbol, imp, acc in sorted(improvements, key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {symbol}: {acc:.1f}% accuracy ({imp:+.1f}% vs base)")
    
    return results


SYNCHRONIZED_FEATURE_NAMES = [
    'ml_hour_sin', 'ml_hour_cos', 'ml_day_of_week',
    'ml_bid_ask_imbalance', 'ml_spread_bps', 'ml_depth_ratio',
    'ml_return_1m', 'ml_return_5m', 'ml_return_15m',
    'ml_volatility_1h', 'ml_price_trend',
    'ml_buy_sell_ratio', 'ml_buy_ratio', 'ml_liq_ratio',
    'ml_liq_long_1h', 'ml_liq_short_1h',
    'ml_fear_greed', 'ml_intel_direction', 'ml_intel_confidence',
    'ml_funding_rate', 'ml_funding_zscore',
    'ml_oi_delta_pct', 'ml_oi_current',
    'ml_long_short_ratio', 'ml_long_ratio', 'ml_short_ratio',
    'ml_recent_wins', 'ml_recent_losses', 'ml_streak_direction',
    'ml_streak_length', 'ml_recent_pnl',
    'ml_btc_return_15m', 'ml_btc_trend',
    'ml_eth_return_15m', 'ml_eth_trend', 'ml_btc_eth_aligned'
]


def build_synchronized_dataset() -> Dict:
    """
    Build training dataset from SYNCHRONIZED ml_ features captured at entry time.
    
    This uses the ml_ prefixed fields that were captured at the exact moment
    of trade entry, not stale data loaded after the fact.
    """
    print("=" * 80)
    print("BUILDING SYNCHRONIZED ML TRAINING DATASET")
    print("=" * 80)
    
    positions = load_positions()
    print(f"Loaded {len(positions)} clean positions")
    
    synced = [p for p in positions if p.get('ml_features') or p.get('ml_entry_ts')]
    print(f"Positions with synchronized features: {len(synced)}")
    
    if len(synced) < 20:
        print(f"WARNING: Only {len(synced)} positions have synchronized features.")
        print("Need more data before models can be trained effectively.")
        return {
            'created': datetime.utcnow().isoformat() + 'Z',
            'total_samples': len(synced),
            'synchronized': True,
            'by_symbol': {},
            'status': 'insufficient_data'
        }
    
    by_symbol = defaultdict(list)
    for pos in synced:
        symbol = pos.get('symbol', 'UNKNOWN')
        direction = pos.get('direction', 'UNKNOWN')
        
        net_pnl = pos.get('net_pnl', pos.get('pnl', 0)) or 0
        gross_pnl = net_pnl + (pos.get('trading_fees', 0) or 0)
        is_win = gross_pnl > 0
        
        features = {}
        for feat_name in SYNCHRONIZED_FEATURE_NAMES:
            features[feat_name] = pos.get(feat_name, 0) or 0
        
        features['direction'] = 1 if direction == 'LONG' else 0
        
        sample = {
            'symbol': symbol,
            'direction': direction,
            'features': features,
            'label': 1 if is_win else 0,
            'net_pnl': net_pnl,
            'gross_pnl': gross_pnl,
            'opened_at': pos.get('opened_at', ''),
            'synchronized': True
        }
        
        by_symbol[symbol].append(sample)
    
    dataset = {
        'created': datetime.utcnow().isoformat() + 'Z',
        'total_samples': len(synced),
        'synchronized': True,
        'feature_names': SYNCHRONIZED_FEATURE_NAMES + ['direction'],
        'by_symbol': {}
    }
    
    for symbol, samples in by_symbol.items():
        wins = sum(1 for s in samples if s['label'] == 1)
        total = len(samples)
        
        dataset['by_symbol'][symbol] = {
            'samples': samples,
            'total': total,
            'wins': wins,
            'win_rate': wins / total * 100 if total > 0 else 0
        }
        
        print(f"  {symbol}: {total} synced samples, {wins} wins ({wins/total*100:.1f}% WR)")
    
    sync_dataset_path = "feature_store/synchronized_training_dataset.json"
    os.makedirs(os.path.dirname(sync_dataset_path), exist_ok=True)
    with open(sync_dataset_path, 'w') as f:
        json.dump(dataset, f, indent=2)
    
    print(f"\nSynchronized dataset saved to {sync_dataset_path}")
    return dataset


def train_synchronized_models(dataset: Dict) -> Dict:
    """Train per-symbol models using synchronized entry-time features."""
    print("\n" + "=" * 80)
    print("TRAINING SYNCHRONIZED ML MODELS")
    print("=" * 80)
    
    if dataset.get('status') == 'insufficient_data':
        print("Skipping training - insufficient synchronized data")
        return {'status': 'insufficient_data', 'models_trained': 0}
    
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.model_selection import cross_val_score
        import numpy as np
    except ImportError:
        print("ERROR: scikit-learn not available")
        return {"error": "sklearn not installed"}
    
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    feature_names = SYNCHRONIZED_FEATURE_NAMES + ['direction']
    
    results = {}
    
    for symbol, data in dataset.get('by_symbol', {}).items():
        samples = data.get('samples', [])
        
        if len(samples) < 30:
            print(f"  {symbol}: Skipping (only {len(samples)} synced samples, need 30+)")
            continue
        
        X = []
        y = []
        
        for sample in samples:
            features = sample.get('features', {})
            row = [features.get(f, 0) for f in feature_names]
            X.append(row)
            y.append(sample.get('label', 0))
        
        X = np.array(X)
        y = np.array(y)
        
        y_unique = len(set(y))
        if y_unique < 2:
            print(f"  {symbol}: Skipping (only one class in labels)")
            continue
        
        model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=4,
            min_samples_leaf=5,
            learning_rate=0.1,
            random_state=42
        )
        
        try:
            n_splits = min(5, len(samples) // 10)
            if n_splits < 2:
                n_splits = 2
            
            cv_scores = cross_val_score(model, X, y, cv=n_splits, scoring='accuracy')
            mean_cv = cv_scores.mean()
            
            model.fit(X, y)
            
            train_preds = model.predict(X)
            train_acc = (train_preds == y).mean()
            
            feature_importance = dict(zip(feature_names, model.feature_importances_))
            top_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)[:5]
            
            model_path = f"{MODEL_DIR}/{symbol}_synced_model.pkl"
            with open(model_path, 'wb') as f:
                pickle.dump({
                    'model': model, 
                    'feature_names': feature_names,
                    'synchronized': True,
                    'trained_at': datetime.utcnow().isoformat() + 'Z',
                    'samples': len(samples)
                }, f)
            
            base_wr = data.get('win_rate', 50)
            improvement = (mean_cv * 100) - base_wr
            
            is_promotable = mean_cv >= 0.55 and improvement > 0
            
            results[symbol] = {
                'samples': len(samples),
                'base_win_rate': round(base_wr, 2),
                'cv_accuracy': round(mean_cv * 100, 2),
                'train_accuracy': round(train_acc * 100, 2),
                'improvement': round(improvement, 2),
                'top_features': [(f[0], round(f[1], 4)) for f in top_features],
                'model_path': model_path,
                'is_promotable': is_promotable,
                'synchronized': True
            }
            
            status = "PROMOTABLE" if is_promotable else "monitoring"
            print(f"\n  {symbol}: [{status}]")
            print(f"    Samples: {len(samples)}")
            print(f"    Base WR: {base_wr:.1f}%")
            print(f"    CV Accuracy: {mean_cv*100:.1f}%")
            print(f"    Improvement: {improvement:+.1f}%")
            print(f"    Top features: {[f[0] for f in top_features[:3]]}")
            
        except Exception as e:
            print(f"  {symbol}: Training failed - {e}")
            results[symbol] = {'error': str(e)}
    
    summary_path = f"{MODEL_DIR}/synchronized_training_summary.json"
    summary = {
        'trained_at': datetime.utcnow().isoformat() + 'Z',
        'synchronized': True,
        'models_trained': len([r for r in results.values() if 'cv_accuracy' in r]),
        'promotable_models': len([r for r in results.values() if r.get('is_promotable')]),
        'results': results
    }
    
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    return summary


def run_synchronized_training_pipeline() -> Dict:
    """
    Run complete synchronized ML training pipeline.
    
    This is the function to call from nightly learning:
    - Builds dataset from synchronized entry-time features
    - Trains per-coin gradient boost models
    - Evaluates for promotion (>55% accuracy, positive improvement)
    - Returns summary with promotable models
    """
    print("=" * 80)
    print("SYNCHRONIZED ML PREDICTION TRAINING PIPELINE")
    print("=" * 80)
    print("Using entry-time synchronized features (not stale data)")
    print()
    
    dataset = build_synchronized_dataset()
    
    if dataset.get('status') == 'insufficient_data':
        return {
            'status': 'insufficient_data',
            'total_samples': dataset.get('total_samples', 0),
            'message': 'Collecting more synchronized feature data before training'
        }
    
    results = train_synchronized_models(dataset)
    
    print("\n" + "=" * 80)
    print("SYNCHRONIZED TRAINING SUMMARY")
    print("=" * 80)
    
    models_trained = results.get('models_trained', 0)
    promotable = results.get('promotable_models', 0)
    
    print(f"\nModels trained: {models_trained}")
    print(f"Promotable models (>55% accuracy): {promotable}")
    
    model_results = results.get('results', {})
    if model_results:
        improvements = [(s, r['improvement'], r['cv_accuracy']) 
                       for s, r in model_results.items() 
                       if 'improvement' in r]
        
        if improvements:
            avg_improvement = sum(i[1] for i in improvements) / len(improvements)
            avg_accuracy = sum(i[2] for i in improvements) / len(improvements)
            
            print(f"Average CV Accuracy: {avg_accuracy:.1f}%")
            print(f"Average Improvement: {avg_improvement:+.1f}%")
            
            promotable_list = [(s, r['cv_accuracy'], r['improvement']) 
                              for s, r in model_results.items() 
                              if r.get('is_promotable')]
            
            if promotable_list:
                print("\nPROMOTABLE MODELS (ready for live trading):")
                for symbol, acc, imp in sorted(promotable_list, key=lambda x: x[1], reverse=True):
                    print(f"  {symbol}: {acc:.1f}% accuracy ({imp:+.1f}% vs base)")
    
    return results


if __name__ == "__main__":
    run_training_pipeline()
