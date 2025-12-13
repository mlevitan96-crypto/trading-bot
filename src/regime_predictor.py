import random
import numpy as np


def predict_next_regime():
    """
    Predict market regime based on volatility, trend strength, and sentiment.
    Returns: Volatile, Trending, Stable, Ranging, or Unknown
    """
    volatility = random.uniform(0, 1)
    trend_strength = random.uniform(0, 1)
    sentiment_score = random.uniform(-1, 1)
    
    if volatility > 0.7 and sentiment_score < 0:
        return "Volatile"
    elif trend_strength > 0.6:
        return "Trending"
    elif sentiment_score > 0.5 and volatility < 0.3:
        return "Stable"
    elif sentiment_score < 0.2 and trend_strength < 0.4:
        return "Ranging"
    else:
        return "Unknown"
