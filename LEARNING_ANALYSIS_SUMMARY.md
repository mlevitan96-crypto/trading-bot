# Learning Analysis Summary - Last 300 Trades
**Generated:** 2025-12-22

## 📊 Key Findings

### Overall Performance
- **Total Trades Analyzed:** 536 executed trades
- **Total P&L:** $-88.36
- **Win Rate:** 36.9%
- **Blocked Signals:** 56

### Critical Insight: Direction Accuracy Issue
- **Direction Accuracy:** 36.9% (very low)
- **Opposite Direction Would Be:** +$88.36 (profitable!)
- **Recommendation:** Consider inverting signals for:
  - AVAXUSDT (37.2% accuracy, 43 trades)
  - BTCUSDT (35.3% accuracy, 167 trades)
  - DOTUSDT (30.8% accuracy, 13 trades)
  - XRPUSDT (36.4% accuracy, 11 trades)
  - ETHUSDT (36.2% accuracy, 149 trades)
  - SOLUSDT (39.9% accuracy, 153 trades)

### Strategy Performance (Signal Weight Matrix)

| Strategy | EV | Win Rate | Total Signals | Total P&L |
|----------|----|----------|---------------|-----------|
| **Sentiment-Fusion** | **-$0.2085** | **35.1%** | **211** | **-$44.00** |
| Breakout-Aggressive | -$0.1859 | 38.1% | 155 | -$28.81 |
| Trend-Conservative | -$0.0925 | 38.8% | 147 | -$13.60 |
| Reentry-Module | -$0.0846 | 34.8% | 23 | -$1.95 |

**Key Finding:** Sentiment-Fusion is the **biggest losing strategy** with:
- Lowest EV: -$0.2085 per trade
- Lowest Win Rate: 35.1%
- Highest volume: 211 trades
- Largest total loss: -$44.00

### Signal Component Performance

**Best Performers:**
- `hurst`: EV +22.13, Weight 13.93% (highest)
- `oi_velocity`: EV +14.43, Weight 13.87%

**Worst Performers:**
- `oi_divergence`: EV -52.70 (worst)
- `volatility_skew`: EV -31.71
- `funding`: EV -26.23

### Market Regime
- **Current Regime:** STRONG_LONG
- **LONG Performance:** +189,372.8 bps
- **SHORT Performance:** -8,458.5 bps

### Hour-Based Performance

**Best Hours (High Win Rate):**
- Hour 1: 71.43% win rate, EV +$0.20 → **Loosen gates**
- Hour 10: 64.52% win rate, EV +$0.19 → **Loosen gates**

**Worst Hours (Low Win Rate):**
- Hour 11: 15.38% win rate, EV -$0.27 → **Tighten gates**
- Hour 8: 25.0% win rate, EV -$0.20 → **Tighten gates**
- Hour 12: 20.83% win rate, EV -$0.16 → **Tighten gates**
- Hour 16: 23.81% win rate, EV -$0.69 → **Tighten gates**

## 🎯 Actionable Recommendations

### 1. Strategy Weight Adjustments (HIGH PRIORITY)
- **Reduce Sentiment-Fusion weight** significantly (currently losing -$0.21 per trade)
- **Reduce Breakout-Aggressive weight** (losing -$0.19 per trade)
- **Reduce Trend-Conservative weight** (losing -$0.09 per trade)

### 2. Direction Inversion (CRITICAL)
- **Consider inverting ALL symbol signals** - direction accuracy is only 36.9%
- Opposite direction would be profitable (+$88.36 vs -$88.36)
- This is the **biggest opportunity** for improvement

### 3. Hour-Based Gate Adjustments
- **Loosen gates** for hours 1 and 10 (high win rates)
- **Tighten gates** for hours 6, 8, 11, 12, 16, 17 (low win rates)

### 4. Signal Component Weights
- **Continue increasing** `hurst` and `oi_velocity` weights (already highest, performing well)
- **Continue decreasing** `oi_divergence`, `volatility_skew`, `funding` weights (performing poorly)

## 📈 Next Steps

1. **Apply Adjustments:**
   ```bash
   python3 run_learning_analysis.py --trades 300 --apply
   ```

2. **Review Strategy Weights:**
   - Check `configs/signal_policies.json` for strategy weight settings
   - Consider reducing Sentiment-Fusion allocation

3. **Investigate Direction Inversion:**
   - Review why direction accuracy is so low (36.9%)
   - Consider implementing direction inversion for underperforming symbols
   - Test with paper trading first

4. **Monitor Hour-Based Performance:**
   - Apply gate adjustments for best/worst hours
   - Monitor if win rates improve after adjustments

5. **Continue Learning:**
   - Run analysis weekly to track improvements
   - Monitor if Sentiment-Fusion performance improves after weight reduction
   - Track direction accuracy over time

## 🔍 Key Insights

1. **Sentiment-Fusion is the biggest problem** - 211 trades, -$44 total loss, 35.1% win rate
2. **Direction accuracy is critical** - Only 36.9% accuracy means we're often trading the wrong direction
3. **Market regime is STRONG_LONG** - LONG trades performing much better than SHORT
4. **Hour-based timing matters** - Some hours have 71% win rate, others have 15%
5. **Signal components are working** - hurst and oi_velocity are strong performers
