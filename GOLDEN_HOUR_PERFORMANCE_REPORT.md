# Golden Hour Trading Performance Review
## Comprehensive Analysis & Recommendations

**Report Date:** December 26, 2025  
**Analysis Period:** All Historical Trades  
**Golden Hour Window:** 09:00-16:00 UTC (London Open to NY Close)  
**Data Source:** Live Trading Bot Production Data

---

## Executive Summary

Golden Hour trading demonstrates **significantly superior performance** compared to non-golden hour periods. The 09:00-16:00 UTC window restriction is **validated and should be maintained**.

### Key Performance Indicators

| Metric | Golden Hour | Non-Golden Hour | Improvement |
|--------|-------------|-----------------|-------------|
| **Win Rate** | **43.3%** | 37.3% | **+6.0 pp** ✅ |
| **Total P&L** | **+$28.78** | -$499.22 | **+$528.00** ✅ |
| **Profit Factor** | **1.07** | 0.51 | **+0.56** ✅ |
| **Trade Count** | 1,025 | 2,496 | -59% (focused) |
| **Avg Hold Time** | 0.53h | 0.67h | -21% (faster) |

**Bottom Line:** Golden Hour trading generates **positive returns** while non-golden hour trading generates **negative returns**. The restriction successfully filters for higher-quality trading opportunities.

---

## Detailed Performance Analysis

### Overall Metrics

#### Golden Hour (09:00-16:00 UTC)
- **Total Trades:** 1,025
- **Wins:** 444 (43.3%)
- **Losses:** 581 (56.7%)
- **Total P&L:** $28.78
- **Average P&L per Trade:** $0.03
- **Profit Factor:** 1.07
- **Average Hold Time:** 0.53 hours (1,895 seconds)

#### Non-Golden Hour (Outside 09:00-16:00 UTC)
- **Total Trades:** 2,496
- **Wins:** 931 (37.3%)
- **Losses:** 1,565 (62.7%)
- **Total P&L:** -$499.22
- **Average P&L per Trade:** -$0.20
- **Profit Factor:** 0.51
- **Average Hold Time:** 0.67 hours (2,396 seconds)

### Performance Differential

The golden hour window provides:
- **$528.00 better total P&L** ($28.78 vs -$499.22)
- **6.0 percentage points higher win rate** (43.3% vs 37.3%)
- **2.1x better profit factor** (1.07 vs 0.51)
- **21% faster exits** (0.53h vs 0.67h average hold time)

---

## Symbol Performance Breakdown

### Top Performers (Golden Hour)

| Symbol | Trades | Win Rate | Profit Factor | Total P&L | Status |
|--------|--------|----------|---------------|-----------|--------|
| **LINKUSDT** | 8 | **62.5%** | 6.32 | $8.23 | ⭐ Excellent |
| **BNBUSDT** | 8 | **50.0%** | 4.51 | $8.96 | ⭐ Excellent |
| **DOGEUSDT** | 17 | **58.8%** | 1.59 | $5.64 | ⭐ Strong |
| **AVAXUSDT** | 98 | **45.9%** | 1.98 | **$36.88** | ⭐ Strong |
| **SOLUSDT** | 228 | **47.8%** | 1.06 | $6.32 | ✅ Positive |
| **XRPUSDT** | 43 | **48.8%** | 1.05 | $0.83 | ✅ Positive |

**Key Insight:** AVAXUSDT is the highest absolute profit generator ($36.88) with solid win rate (45.9%). LINKUSDT has the highest win rate (62.5%) but low volume.

### Underperformers (Golden Hour)

| Symbol | Trades | Win Rate | Profit Factor | Total P&L | Status |
|--------|--------|----------|---------------|-----------|--------|
| **ADAUSDT** | 31 | **29.0%** | 0.59 | **-$12.10** | ❌ Poor |
| **BTCUSDT** | 280 | **39.6%** | 0.80 | **-$20.07** | ❌ Poor |
| **ETHUSDT** | 249 | **43.0%** | 0.96 | -$4.19 | ⚠️ Marginal |
| **DOTUSDT** | 51 | **37.3%** | 0.97 | -$1.04 | ⚠️ Marginal |

**Key Insight:** BTCUSDT is the largest loss generator (-$20.07) despite high volume (280 trades). ADAUSDT has the worst win rate (29.0%) and should be avoided.

### Symbol Recommendations

1. **INCREASE ALLOCATION:**
   - AVAXUSDT (highest profit, solid WR)
   - LINKUSDT (highest WR, excellent PF)
   - BNBUSDT (balanced performance)

2. **REDUCE OR ELIMINATE:**
   - ADAUSDT (29% WR, negative PF)
   - BTCUSDT (underperforming despite volume)

3. **MAINTAIN:**
   - SOLUSDT, XRPUSDT, DOGEUSDT (positive performance)
   - ETHUSDT (investigate further, marginal performance)

---

## Strategy Performance Breakdown

| Strategy | Trades | Win Rate | Total P&L | Avg P&L | Status |
|----------|--------|----------|-----------|---------|--------|
| **Sentiment-Fusion** | 465 | 43.2% | **$32.55** | $0.07 | ⭐ Best |
| **Breakout-Aggressive** | 220 | **47.3%** | $7.68 | $0.03 | ⭐ Strong |
| **Trend-Conservative** | 240 | 41.2% | $6.27 | $0.03 | ✅ Positive |
| **Reentry-Module** | 67 | 40.3% | -$8.17 | -$0.12 | ⚠️ Weak |
| **Alpha-OFI** | 33 | 39.4% | -$9.55 | -$0.29 | ⚠️ Weak |

### Strategy Recommendations

1. **PRIMARY STRATEGIES** (Maintain High Allocation):
   - **Sentiment-Fusion**: Highest absolute profit ($32.55), good win rate (43.2%)
   - **Breakout-Aggressive**: Best win rate (47.3%), positive P&L ($7.68)

2. **SECONDARY STRATEGY** (Maintain Current Allocation):
   - **Trend-Conservative**: Positive P&L ($6.27), acceptable win rate (41.2%)

3. **REDUCE ALLOCATION**:
   - **Alpha-OFI**: Negative P&L (-$9.55), below-average WR (39.4%)
   - **Reentry-Module**: Negative P&L (-$8.17), marginal WR (40.3%)

---

## Enhanced Logging Status

**Current Coverage:** 109/1,025 trades (10.6%)

### Status
- ✅ Enhanced logging is operational and capturing volatility snapshots
- ✅ New trades (post-December 2025) include complete volatility data
- ⏳ Historical coverage is 10.6% (expected, as logging was implemented in December 2025)

### Data Quality
- **ATR (14-period):** Captured for new trades
- **Volume (24h):** Captured for new trades
- **Regime at Entry:** Captured for new trades
- **Signal Components:** Captured for new trades

### Next Steps
- Monitor coverage increase as new trades execute
- Use enhanced data for deeper volatility/regime analysis once coverage >50%
- Current data sufficient for high-level performance analysis

---

## Trading Window Validation

### Golden Hour Window: 09:00-16:00 UTC

**Rationale:** London Open (08:00 UTC) to NY Close (16:00 UTC) - highest liquidity and institutional participation.

**Validation Results:**
- ✅ **+6.0% win rate improvement** (43.3% vs 37.3%)
- ✅ **$528.00 P&L improvement** (+$28.78 vs -$499.22)
- ✅ **Positive profit factor** (1.07 vs 0.51)
- ✅ **Faster execution** (0.53h vs 0.67h average hold time)

**Recommendation:** **MAINTAIN** the 09:00-16:00 UTC trading window restriction. The data clearly validates this strategy.

---

## Risk Management Observations

### Hold Time Analysis

- **Golden Hour:** 0.53 hours average (1,895 seconds)
- **Non-Golden Hour:** 0.67 hours average (2,396 seconds)
- **Difference:** -21% faster exits in golden hour

**Implication:** Shorter hold times during golden hour may contribute to better risk management and faster profit realization.

### Trade Frequency

- **Golden Hour:** 1,025 trades (29% of total)
- **Non-Golden Hour:** 2,496 trades (71% of total)

**Implication:** Golden hour restriction successfully focuses trading on higher-quality periods while reducing overall trade frequency.

---

## Recommendations Summary

### Immediate Actions

1. **✅ MAINTAIN** Golden Hour window (09:00-16:00 UTC)
   - Validated by +6% WR and $528 P&L improvement
   - Continue blocking new entries outside window

2. **🔧 OPTIMIZE** Symbol Allocation
   - **Increase:** AVAXUSDT, LINKUSDT, BNBUSDT
   - **Reduce/Eliminate:** ADAUSDT (29% WR, negative PF)
   - **Investigate:** BTCUSDT underperformance despite volume

3. **📊 ADJUST** Strategy Mix
   - **Maintain:** Sentiment-Fusion, Breakout-Aggressive (primary)
   - **Reduce:** Alpha-OFI, Reentry-Module allocation

### Medium-Term Actions

1. **Monitor** enhanced logging coverage increase
2. **Analyze** BTCUSDT underperformance (investigate market structure)
3. **Test** increased allocation to top performers (AVAXUSDT, LINKUSDT)

### Long-Term Actions

1. **Review** symbol performance quarterly
2. **Optimize** strategy allocation based on continued performance
3. **Consider** sub-window optimization (e.g., 09:00-12:00 vs 12:00-16:00 UTC)

---

## Data Quality & Methodology

### Data Sources
- **Primary:** `logs/positions_futures.json` (authoritative position data)
- **Secondary:** `logs/enriched_decisions.jsonl` (enhanced logging data)
- **Analysis Script:** `analyze_golden_hour_trades.py`

### Methodology
- All closed trades analyzed (open positions excluded from P&L)
- Golden hour defined as 09:00-16:00 UTC (inclusive start, exclusive end)
- Timestamps normalized to UTC for consistency
- Enhanced logging coverage calculated as trades with volatility snapshots

### Limitations
- Historical data includes trades from before enhanced logging implementation
- Coverage will increase as new trades execute
- Symbol performance may vary with market conditions

---

## Conclusion

Golden Hour trading (09:00-16:00 UTC) is **validated and effective**:

- ✅ **Superior performance** across all key metrics
- ✅ **Positive P&L** vs negative for non-golden hours
- ✅ **Better risk management** (faster exits, focused trading)
- ✅ **Clear symbol and strategy patterns** for optimization

**The restriction should be maintained and optimized based on symbol/strategy performance patterns identified in this analysis.**

---

**Report Generated:** December 26, 2025  
**Next Review:** After next 500 golden hour trades or quarterly, whichever comes first
