# EXPANSIVE MULTI-DIMENSIONAL PROFITABILITY ANALYZER

## Overview

The **Expansive Multi-Dimensional Profitability Analyzer** is the most comprehensive profitability analysis system in the trading bot. It slices data in **EVERY possible way** to identify profitability patterns across all dimensions of trading.

## What Makes It "Expansive"

This analyzer doesn't just look at basic metrics—it analyzes **ALL data** from **ALL sources** in **ALL combinations**:

### Data Sources Analyzed

1. **Trade Data** (`positions_futures.json`)
   - Entry/exit prices, P&L, fees
   - Symbol, strategy, direction, leverage
   - Hold duration, timestamps

2. **Signal Data** (`enriched_decisions.jsonl`, `signals.jsonl`)
   - OFI scores, ensemble scores, MTF confidence
   - Regime classifications
   - Signal components and conviction levels

3. **CoinGlass Data** (from signals and positions)
   - Funding rates, OI delta, long/short ratios
   - Taker flow ratios, liquidation bias
   - Fear/greed indices

4. **ML Features** (50+ features captured at entry time)
   - **Orderbook**: bid/ask imbalance, spread, depth, sizes
   - **Momentum**: returns (1m, 5m, 15m), volatility, trend
   - **Intelligence**: buy/sell ratios, liquidations, fear/greed
   - **CoinGlass**: funding, OI, long/short ratios
   - **Streak**: recent wins/losses, streak direction/length
   - **Cross-Asset**: BTC/ETH returns, trends, alignment
   - **On-Chain**: whale flows, exchange flows (when available)
   - **Sentiment**: social signals, sentiment indicators

5. **Time Patterns**
   - Hour of day, day of week
   - Time since entry (hold duration buckets)

## Dimensions Analyzed

### 1. By Symbol
- Performance per symbol (win rate, expectancy, total P&L)
- Sub-analyzed by:
  - Strategy (which strategy works best per symbol)
  - Time of day (best hours per symbol)
  - OFI range (which OFI levels work per symbol)
  - Regime (which regimes are profitable per symbol)
  - CoinGlass alignment (does alignment matter per symbol)

### 2. By Strategy
- Performance per strategy
- Sub-analyzed by:
  - Symbol (which symbols work best per strategy)
  - OFI range (which OFI levels work per strategy)
  - Ensemble range (bull/bear/neutral signals per strategy)

### 3. By Time of Day
- Hour-by-hour profitability analysis
- Day-of-week patterns
- Best trading hours identified

### 4. By Signal Combinations
- Multi-factor analysis:
  - OFI + Ensemble + MTF + CoinGlass alignment
  - Identifies which signal combinations are most profitable

### 5. By CoinGlass Alignment
- Taker ratio alignment vs profitability
- Funding rate buckets (high positive, low positive, low negative, high negative)
- OI delta buckets (very positive, positive, neutral, negative, very negative)
- Liquidation bias buckets (strong long liq, long liq, balanced, short liq, strong short liq)

### 6. By Volume & Orderbook Regime
- **Volume regime**: High vs low volume (based on OI or volume data)
- **Orderbook depth**: High vs low depth ratio
- **Spread regime**: Tight vs wide spreads

### 7. By Price Momentum & Volatility
- **Volatility regime**: High vs low volatility at entry
- **Momentum buckets**: Strong uptrend, uptrend, neutral, downtrend, strong downtrend (based on 5m returns)

### 8. By Regime
- Trending vs choppy vs volatile
- Performance by market regime

### 9. By OFI Buckets
- Extreme (>0.8), Very Strong (>0.7), Strong (>0.5), Moderate (>0.3), Weak (<0.3)

### 10. By Ensemble Buckets
- Strong Bull (>0.3), Moderate Bull (>0.1), Neutral (-0.1 to 0.1), Moderate Bear (<-0.1), Strong Bear (<-0.3)

### 11. By Leverage
- Performance by leverage level (e.g., 2x, 5x, 10x)

### 12. By Hold Duration
- Flash (<1min), Quick (1-5min), Short (5-15min), Medium (15-60min), Extended (1-4hr), Long (>4hr)

### 13. Cross-Correlations
- OFI vs P&L correlation
- Ensemble vs P&L correlation
- Volume vs P&L correlation
- Identifies which factors are most predictive

### 14. Cross-Asset Patterns
- BTC/ETH alignment vs profitability
- BTC trend at entry (strong up, up, neutral, down, strong down)
- ETH trend at entry (strong up, up, neutral, down, strong down)

### 15. Signal Interactions
- OFI High + CoinGlass Aligned
- MTF Strong + OFI High
- Identifies synergistic signal combinations

### 16. Profitability Patterns
- Discovers high-performing patterns across ALL dimensions:
  - Symbol + Strategy + OFI level + Hour
  - Identifies patterns with >70% win rate or >$20/trade expectancy

## Integration

The Expansive Analyzer is integrated into the **Profitability Trader Persona** (`src/profitability_trader_persona.py`), which runs nightly and provides:

1. **Actionable Insights**: Key findings from all dimensions
2. **Optimization Recommendations**: Specific actions to improve profitability
3. **Pattern Discovery**: Top-performing combinations identified

## Output

The analyzer produces:

1. **Full Analysis JSON** (`reports/expansive_profitability_analysis.json`)
   - Complete multi-dimensional analysis
   - All slices, correlations, patterns

2. **Actionable Insights** (in Profitability Trader Persona output)
   - Key findings from all dimensions
   - Recommendations for improvements

3. **Optimization Recommendations**
   - Symbol allocation changes
   - Timing optimizations
   - Signal filter priorities

## Example Insights

The analyzer might discover:

- "BTC is highly profitable ($45.23/trade) - consider increasing allocation"
- "Best trading hours: 14:00, 15:00, 16:00 UTC - consider focusing activity during these times"
- "Best signal combo: OFI_high+ENS_moderate_bull+MTF_strong+CG_aligned ($32.15/trade, 78.5% WR)"
- "CoinGlass alignment matters: 68.3% WR aligned vs 52.1% misaligned"
- "Tight spreads perform better: 71.2% WR vs 54.8% for wide spreads"
- "BTC-aligned trades: 73.5% WR vs 51.2% for misaligned"

## Statistical Rigor

- Minimum 3-5 trades per slice for statistical significance
- Correlation calculations (Pearson correlation coefficient)
- Win rate, expectancy, and total P&L for every slice
- Identifies patterns that are both statistically significant AND profitable

## Why This Matters

The bot has **tons of intelligence built in**—signals, CoinGlass data, volume, time, price, relationships. This analyzer ensures we're using **ALL of it** to find profitability patterns that would otherwise be hidden.

**Every dimension matters.** The analyzer finds:
- Which symbols to trade more
- Which hours to focus on
- Which signal combinations work
- Which market conditions are favorable
- How factors interact with each other

This is **not generic**—it's tailored specifically to YOUR bot's data and YOUR bot's intelligence systems.

## Future Enhancements

The analyzer is designed to be expanded with new dimensions as they become available:
- Cross-asset correlations (when more data is available)
- Price level analysis (when historical price data is added)
- Additional ML features as they're captured
- Real-time pattern matching for live trading

---

**This is the most comprehensive profitability analysis possible—leaving no data unanalyzed, no dimension unexplored, no pattern undiscovered.**
