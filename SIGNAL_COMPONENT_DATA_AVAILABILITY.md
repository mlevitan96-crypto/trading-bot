# Signal Component Data Availability Report
## What Data We Have vs What We Need for Hypothesis Testing

**Date:** December 22, 2025  
**Purpose:** Determine if we have the data needed to test volatility and signal component hypotheses

---

## Requested Metrics

### 1. Volatility at Entry
**Requested:** ATR (Average True Range) or Volume metrics at exact time of trade

**Current Status:**
- ✅ **Volatility field exists** in `signal_ctx.volatility` (but may be 0 for many trades)
- ⚠️ **ATR not calculated at entry** - would need to compute from price history
- ⚠️ **Volume available** in `signal_ctx.volume` (but may be missing)

**Where it's stored:**
- `enriched_decisions.jsonl` → `signal_ctx.volatility`
- `enriched_decisions.jsonl` → `signal_ctx.volume`
- `positions_futures.json` → `volatility` (when position opened)

**Enhancement needed:**
- Calculate ATR at entry time from price history
- Ensure volatility is always populated when position opens

### 2. Signal Component Breakdown
**Requested:** Individual scores for:
- Liquidation Cascade
- Funding Rate
- Whale Flow
- (Instead of just "Ensemble Score")

**Current Status:**
- ✅ **Components ARE generated** in `predictive_flow_engine.py`
- ✅ **Components ARE logged** to `logs/predictive_signals.jsonl`
- ❌ **Components NOT extracted** in `data_enrichment_layer.py`
- ⚠️ **Components stored in positions** but not in enriched_decisions.jsonl

**Where components are generated:**
```python
# src/predictive_flow_engine.py
signals['liquidation'] = self.liquidation_detector.compute_signal(...)
signals['funding'] = self.funding_signal.compute_signal(funding_rate)
signals['whale_flow'] = self.whale_flow.compute_signal(...)
```

**Where components are logged:**
- `logs/predictive_signals.jsonl` → `signals.liquidation`, `signals.funding`, `signals.whale_flow`
- `positions_futures.json` → `signal_components` (when position opened)

**Enhancement needed:**
- Match trades with `predictive_signals.jsonl` by symbol+timestamp
- Extract components into `enriched_decisions.jsonl.signal_ctx.signal_components`

### 3. Market Regime Classification
**Requested:** What regime did the bot think it was at entry?

**Current Status:**
- ✅ **Regime IS stored** in `signal_ctx.regime`
- ✅ **Available in enriched_decisions.jsonl**

**Where it's stored:**
- `enriched_decisions.jsonl` → `signal_ctx.regime`
- Values: "Stable", "Volatile", "Trending", "unknown"

**No enhancement needed** - this data is available.

---

## Data Sources

### Primary Source: `logs/enriched_decisions.jsonl`
**What it contains:**
- ✅ Signal context (OFI, Ensemble, Regime)
- ✅ Outcomes (P&L, fees, prices)
- ⚠️ Signal components (NOT extracted yet)
- ⚠️ Volatility/ATR (may be missing)

**Created by:** `src/data_enrichment_layer.py`

### Secondary Source: `logs/predictive_signals.jsonl`
**What it contains:**
- ✅ Full signal component breakdown
- ✅ Liquidation cascade details
- ✅ Funding rate details
- ✅ Whale flow details
- ✅ OI velocity, fear/greed, etc.

**Created by:** `src/predictive_flow_engine.py`

**Problem:** Not matched with trades in enriched_decisions.jsonl

### Tertiary Source: `logs/positions_futures.json`
**What it contains:**
- ✅ Signal components (when position opened)
- ✅ Volatility (when position opened)
- ✅ All position metadata

**Problem:** Not in enriched_decisions.jsonl format

---

## Enhancement Plan

### Step 1: Enhance `data_enrichment_layer.py` (COMPLETED)
**Changes made:**
1. ✅ Load `predictive_signals.jsonl`
2. ✅ Match trades with predictive signals by symbol+timestamp
3. ✅ Extract signal components into `signal_ctx.signal_components`
4. ✅ Extract volatility/volume from trades

**Result:** Next time `enrich_recent_decisions()` runs, it will include:
- `signal_ctx.signal_components.liquidation_cascade`
- `signal_ctx.signal_components.funding_rate`
- `signal_ctx.signal_components.whale_flow`
- `signal_ctx.volatility`
- `signal_ctx.volume`

### Step 2: Add ATR Calculation (RECOMMENDED)
**Enhancement needed:**
- Calculate ATR at entry time from price history
- Store in `signal_ctx.atr` and `signal_ctx.atr_pct`

**Implementation:**
```python
def calculate_atr_at_entry(symbol, entry_ts, window=14):
    # Load price history
    # Calculate True Range for last window candles
    # Return ATR and ATR as % of price
```

### Step 3: Run Data Enrichment
**Command:**
```bash
python -c 'from src.data_enrichment_layer import enrich_recent_decisions, persist_enriched_data; persist_enriched_data(enrich_recent_decisions(168))'
```

This will:
- Re-enrich all trades from last 7 days
- Include signal components from predictive_signals.jsonl
- Include volatility/volume from positions

---

## Testing the Hypotheses

### Hypothesis 1: Volatility at Entry
**Test:** Do losses correlate with Low Volatility (Chopping) or Extreme Volatility (Crash/Wick)?

**Data needed:**
- ATR at entry (or volatility metric)
- Win/Loss outcome

**Status:** ⚠️ **PARTIALLY AVAILABLE**
- Volatility field exists but may be 0
- ATR not calculated (needs enhancement)

**Action:** Run enhanced enrichment, then analyze with `analyze_signal_components.py`

### Hypothesis 2: Signal Component Breakdown
**Test:** 
- Do "Liquidation Cascade" signals cause losses?
- Is "Whale Flow" actually accurate?

**Data needed:**
- Individual component scores (liquidation, funding, whale_flow)
- Win/Loss outcome

**Status:** ✅ **AVAILABLE AFTER ENHANCEMENT**
- Components generated in predictive_signals.jsonl
- Now extracted in enriched_decisions.jsonl (after enhancement)

**Action:** Run enhanced enrichment, then analyze

### Hypothesis 3: Regime Classification
**Test:** Does bot fail to detect "Stable/Chop" regimes accurately?

**Data needed:**
- Regime at entry
- Win/Loss outcome

**Status:** ✅ **AVAILABLE**
- Regime stored in signal_ctx.regime

**Action:** Can analyze immediately

---

## How to Get the Data

### Option 1: Re-enrich Existing Trades (RECOMMENDED)
```bash
# On your server
cd /root/trading-bot-current
python3 -c 'from src.data_enrichment_layer import enrich_recent_decisions, persist_enriched_data; persist_enriched_data(enrich_recent_decisions(168))'
```

This will:
- Re-process last 7 days of trades
- Match with predictive_signals.jsonl
- Extract signal components
- Create new enriched_decisions.jsonl with all components

### Option 2: Run Analysis Script
```bash
# On your server
cd /root/trading-bot-current
python3 analyze_signal_components.py
```

This will:
- Check what data is available
- Match trades with predictive signals
- Test all 3 hypotheses
- Export detailed JSON for review

### Option 3: Manual Extraction
If you want to extract data manually:

1. **Get enriched_decisions.jsonl:**
   ```bash
   # Should be at: logs/enriched_decisions.jsonl
   ```

2. **Get predictive_signals.jsonl:**
   ```bash
   # Should be at: logs/predictive_signals.jsonl
   ```

3. **Match them:**
   - Match by `symbol` + `timestamp` (within 5 minutes)
   - Extract `signals.liquidation`, `signals.funding`, `signals.whale_flow`

---

## Expected Data Structure After Enhancement

```json
{
  "ts": 1234567890,
  "symbol": "BTCUSDT",
  "strategy": "trend-conservative",
  "signal_ctx": {
    "ofi": 0.604,
    "ensemble": 0.051,
    "regime": "Stable",
    "side": "LONG",
    "volatility": 0.02,
    "volume": 1000000,
    "signal_components": {
      "liquidation_cascade": {
        "cascade_active": false,
        "confidence": 0.3,
        "direction": "NEUTRAL",
        "total_1h": 0
      },
      "funding_rate": {
        "rate": 0.0001,
        "confidence": 0.5,
        "direction": "LONG"
      },
      "whale_flow": {
        "net_flow_usd": 500000,
        "confidence": 0.7,
        "direction": "LONG"
      }
    }
  },
  "outcome": {
    "pnl_usd": -0.52,
    "entry_price": 45000,
    "exit_price": 44950
  }
}
```

---

## Next Steps

1. **Run enhanced enrichment** (re-processes trades with components)
2. **Run analysis script** (tests hypotheses)
3. **Review results** (see what's actually causing losses)
4. **Implement fixes** (based on findings)

---

## Files Modified

1. ✅ `src/data_enrichment_layer.py` - Enhanced to extract signal components
2. ✅ `analyze_signal_components.py` - Created analysis script

## Files to Review

- `logs/enriched_decisions.jsonl` - After re-enrichment
- `logs/predictive_signals.jsonl` - Source of component data
- `feature_store/signal_component_analysis.json` - Analysis results




