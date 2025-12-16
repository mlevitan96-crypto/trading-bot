# CoinGlass Rate Limit Analysis & Optimization
## Ensuring We Stay Within 30 Requests/Minute

**Current Status:** ⚠️ **NEEDS OPTIMIZATION**

---

## Current Configuration

### Rate Limit Settings
- **Limit:** 30 requests/minute (Hobbyist plan)
- **Current Delay:** 2.5 seconds between calls
- **Theoretical Max:** 24 requests/minute (with 2.5s delay)

### Current Usage

#### 1. Intelligence Poller (`intelligence_gate.py`)
- **Interval:** 60 seconds
- **Calls per poll:** ~10-12 calls
  - 8 symbols × taker buy/sell = 8 calls
  - 1 liquidation call (bulk)
  - 1 fear & greed call
  - **Total:** ~10 calls per minute
- **Status:** ✅ SAFE (10 calls/min < 30 limit)

#### 2. Market Intelligence (`market_intelligence.py`)
- **Rate limit delay:** 2.5 seconds
- **Symbols:** 8 symbols (BTC, ETH, SOL, XRP, DOGE, BNB, AVAX, ADA)
- **Calls per function:**
  - `get_taker_buy_sell()`: 8 calls (one per symbol)
  - `get_liquidations()`: 1 call (bulk)
  - `get_fear_greed()`: 1 call
  - **Total per poll:** ~10 calls

#### 3. CoinGlass Intelligence (`coinglass_intelligence.py`)
- **Poll interval:** 300 seconds (5 minutes) - if enabled
- **Calls per poll:** 4 endpoints × N symbols
- **Sleep between calls:** 0.15 seconds (TOO FAST!)
- **Status:** ⚠️ **RISKY** if enabled (could exceed limit)

---

## Problem Analysis

### Issue 1: Multiple Pollers
- Intelligence poller: 60s interval = 10 calls/min
- CoinGlass intelligence: 300s interval = ~20 calls/min (if enabled)
- **Total:** Could exceed 30 calls/min if both run

### Issue 2: Insufficient Delay
- `coinglass_intelligence.py` uses 0.15s delay (TOO FAST)
- Should be 2.5s minimum to respect 30 req/min limit

### Issue 3: Symbol Count
- Currently tracking 8 symbols
- Each symbol requires multiple calls
- More symbols = more calls = higher risk

---

## Recommended Configuration

### Optimal Setup (Stays Under 30 req/min)

#### Option 1: Single Poller (Recommended)
- **Use:** Intelligence Poller only (60s interval)
- **Calls:** ~10 calls/minute
- **Margin:** 20 calls/minute headroom
- **Status:** ✅ SAFE

#### Option 2: Dual Poller (If Needed)
- **Intelligence Poller:** 60s interval = 10 calls/min
- **CoinGlass Intelligence:** 600s interval (10 min) = ~2 calls/min
- **Total:** ~12 calls/min
- **Status:** ✅ SAFE

### Rate Limit Settings

**Minimum delay between calls:**
- **Current:** 2.5 seconds
- **Recommended:** 2.5 seconds (keep as is)
- **Calculation:** 60 seconds / 30 requests = 2.0 seconds minimum
- **Safety margin:** 2.5 seconds provides 20% buffer

**Poll intervals:**
- **Intelligence Poller:** 60 seconds (current) ✅
- **CoinGlass Intelligence:** 300 seconds minimum (if enabled)

---

## Configuration Changes Needed

### 1. Fix `coinglass_intelligence.py` Rate Limiting
**Current:** 0.15s delay (TOO FAST)
**Fix:** Use 2.5s delay minimum

### 2. Ensure Only One Active Poller
**Current:** Multiple pollers possible
**Fix:** Disable CoinGlass Intelligence polling if Intelligence Poller is active

### 3. Optimize Symbol List
**Current:** 8 symbols
**Options:**
- Keep 8 symbols (safe)
- Reduce to 6 symbols (safer)
- Increase to 10 symbols (risky, need careful timing)

---

## Implementation

I'll create a centralized CoinGlass rate limiter and optimize the configuration.

