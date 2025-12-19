# Symbol Normalization Verification

## Overview

This document confirms that the **Expansive Multi-Dimensional Profitability Analyzer** correctly handles symbol formats with the Kraken integration.

## Symbol Format Standards

### Internal Storage Format (Canonical)
- **Format**: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` (no dashes, no prefixes)
- **Used in**:
  - `positions_futures.json` (all positions)
  - `enriched_decisions.jsonl` (signal outcomes)
  - `signals.jsonl` (all signals)
  - `config/asset_universe.json` (canonical source of truth)
  - Feature store files (`BTCUSDT_intel.json`, etc.)

### Exchange Formats
- **Kraken**: `PI_XBTUSD`, `PI_ETHUSD`, `PF_SOLUSD` (PI_ for inverse, PF_ for linear)
- **Blofin**: `BTC-USDT`, `ETH-USDT` (dash format)

### Normalization Flow

```
API Call (Exchange)          Internal Storage          Analysis
─────────────────────────────────────────────────────────────────
Kraken: PI_XBTUSD     →     BTCUSDT      →     BTCUSDT
Blofin: BTC-USDT      →     BTCUSDT      →     BTCUSDT
```

**Key Point**: Symbols are **always normalized to internal format (`BTCUSDT`)** before storage. The analyzer works with internal format.

## Verification in Analyzer

### 1. Symbol Normalization Function
The analyzer includes `_normalize_symbol_for_matching()` which:
- Converts Kraken format (`PI_XBTUSD`) → Internal (`BTCUSDT`)
- Removes dashes (`BTC-USDT`) → Internal (`BTCUSDT`)
- Leaves internal format unchanged (`BTCUSDT` → `BTCUSDT`)

### 2. Normalization Applied At:
- **Data Loading**: When loading positions from `positions_futures.json`
- **Signal Matching**: When matching enriched decisions to positions
- **Symbol Matching**: When matching signals to trades
- **Analysis**: When grouping trades by symbol
- **Pattern Discovery**: When creating pattern keys

### 3. Consistency Guarantees

**Position Data** (`positions_futures.json`):
- Stored in internal format (`BTCUSDT`) - verified in `position_manager.py`
- Analyzer normalizes on load to handle any edge cases

**Signal Data** (`signals.jsonl`, `enriched_decisions.jsonl`):
- Stored in internal format (`BTCUSDT`)
- Analyzer normalizes when matching to positions

**Pattern Keys**:
- All patterns use normalized symbols
- Ensures consistent grouping across all analysis dimensions

## Testing Scenarios

### Scenario 1: Normal Operation (Internal Format)
- Position has: `symbol: "BTCUSDT"`
- Signal has: `symbol: "BTCUSDT"`
- **Result**: ✅ Matches correctly

### Scenario 2: Kraken Format (Edge Case)
- Position has: `symbol: "PI_XBTUSD"` (shouldn't happen, but handled)
- **Result**: ✅ Normalized to `BTCUSDT` for analysis

### Scenario 3: Blofin Format (Edge Case)
- Position has: `symbol: "BTC-USDT"` (shouldn't happen, but handled)
- **Result**: ✅ Normalized to `BTCUSDT` for analysis

### Scenario 4: Mixed Formats (Edge Case)
- Position has: `symbol: "BTCUSDT"`
- Signal has: `symbol: "PI_XBTUSD"`
- **Result**: ✅ Both normalized to `BTCUSDT`, matches correctly

## Integration Points

### 1. Exchange Utils Integration
```python
from src.exchange_utils import normalize_from_kraken
```
- Used for Kraken → Internal conversion
- Fallback included if module not available

### 2. Position Manager
- Stores symbols in internal format (`BTCUSDT`)
- No conversion needed, but analyzer normalizes as safety measure

### 3. Signal Tracker
- Logs symbols in internal format (`BTCUSDT`)
- Analyzer normalizes when matching

### 4. Data Registry
- All data sources use internal format
- Analyzer normalizes for consistency

## Conclusion

✅ **The analyzer is fully compatible with Kraken integration:**
- Handles internal format (`BTCUSDT`) correctly
- Normalizes Kraken format (`PI_XBTUSD`) if encountered
- Normalizes Blofin format (`BTC-USDT`) if encountered
- Ensures consistent symbol matching across all data sources
- Works with all existing code that uses internal format

**No breaking changes** - the analyzer enhances symbol matching robustness without affecting existing functionality.
