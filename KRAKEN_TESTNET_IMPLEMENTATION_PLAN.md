# Kraken Testnet Implementation Plan

**Date:** December 18, 2025  
**Status:** Review & Prioritization  
**Goal:** Ensure bot is fully aligned with Kraken Futures, avoid Blofin-era assumptions

---

## Executive Summary

**Critical Items (Must Do During Testnet):** 3 items  
**High Priority (Should Do During Testnet):** 5 items  
**Medium Priority (Nice to Have):** 2 items  
**Low Priority (Can Wait):** 1 item

**Recommendation:** Implement Critical + High Priority items during testnet. This will ensure the bot is production-ready when switching to live.

---

## Item-by-Item Review

### 🔴 CRITICAL - Must Implement During Testnet

#### 1. Symbol Universe Validation ✅ HIGHEST PRIORITY

**Current State:**
- ✅ Symbols loaded from `config/asset_universe.json`
- ❌ No validation that symbols exist on Kraken
- ❌ No liquidity/spread checks
- ❌ No orderbook validation
- ⚠️ Some symbols in config may not exist on Kraken (e.g., PEPEUSDT, ARBUSDT need verification)

**Why Critical:**
- Trading non-existent symbols will cause runtime errors
- Poor liquidity = bad fills and slippage
- Must know which symbols are actually tradeable before live

**Implementation Plan:**
```
1. Create: src/venue_symbol_validator.py
   - Validates each symbol exists on Kraken testnet
   - Checks orderbook depth (bids/asks)
   - Validates OHLCV data availability
   - Calculates spread and depth metrics
   - Auto-suppresses failing symbols

2. Create: feature_store/venue_symbol_status.json
   - Stores validation status per symbol
   - Last validation timestamp
   - Validation errors/reasons

3. Integration:
   - Run validation on bot startup
   - Run validation daily (4 AM UTC)
   - Update asset_universe.json "enabled" field based on validation
   - Log suppressed symbols to dashboard

4. Dashboard:
   - Show symbol validation status
   - Show which symbols are suppressed and why
```

**Effort:** 4-6 hours  
**Risk:** Low - Validation only, doesn't affect trading logic  
**Priority:** ✅ **DO FIRST**

---

#### 3. Venue-Aware Learning State (Reset Blofin Learnings) ✅ CRITICAL

**Current State:**
- ❌ Learning files not venue-tagged
- ❌ Blofin learnings will be applied to Kraken (wrong!)
- ❌ Signal weights trained on Blofin data will mislead Kraken trading
- ⚠️ No mechanism to reset/decay learnings on venue change

**Why Critical:**
- Blofin and Kraken have different:
  - Market microstructure
  - Spreads and liquidity
  - Fee structures
  - Order book dynamics
- Using Blofin-learned weights on Kraken = trading with wrong assumptions
- Could lead to poor performance or losses

**Implementation Plan:**
```
1. Add venue tag to all learning files:
   - feature_store/signal_weights.json → add "_venue": "kraken"
   - feature_store/learning_state.json → add "_venue": "kraken"
   - feature_store/hold_time_policy.json → add "_venue": "kraken"
   - feature_store/profit_policy.json → add "_venue": "kraken"
   - feature_store/daily_learning_rules.json → add "_venue": "kraken"

2. Create: src/learning_venue_migration.py
   - Detects venue change (Blofin → Kraken)
   - Resets or heavily decays old learnings
   - Creates new venue-specific learning state
   - Preserves structure but resets values

3. Modify learning systems:
   - All learning reads check venue tag
   - If venue mismatch → use defaults or decay
   - First 7-14 days: Clamp adjustments (±10% max)
   - Lower leverage caps initially (max 5x → 3x)
   - Smaller position sizes initially ($200-$500)

4. Reset logic:
   - signal_weights.json → Reset to default weights (or 50% decay)
   - learning_state.json → Reset counters to 0
   - hold_time_policy.json → Reset to conservative defaults
   - profit_policy.json → Reset to base thresholds
```

**Effort:** 6-8 hours  
**Risk:** Medium - Must ensure learning still works correctly  
**Priority:** ✅ **DO SECOND** (after symbol validation)

---

#### 2. Contract Size, Tick Size, and Notional Alignment ✅ CRITICAL

**Current State:**
- ❌ No contract size handling (Kraken uses contract multipliers)
- ❌ No tick size enforcement (Kraken has specific tick sizes per symbol)
- ❌ Position sizing may produce invalid order sizes
- ❌ No rounding to valid tick sizes

**Why Critical:**
- Kraken will reject orders with invalid sizes
- Tick size violations = rejected orders
- Contract size mismatches = wrong position sizes
- Must fix before any real trading

**Implementation Plan:**
```
1. Create: src/kraken_contract_specs.py
   - Defines contract size, tick size, min size per symbol
   - PI_XBTUSD: contract_size=1, tick_size=0.5, min_size=1
   - PI_ETHUSD: contract_size=1, tick_size=0.01, min_size=1
   - (Need to verify exact specs for each symbol)

2. Create: src/canonical_sizing_helper.py
   - Function: normalize_position_size(symbol, target_usd, price, exchange)
   - Enforces min contract size
   - Rounds to tick size
   - Validates notional (min/max)
   - Returns (contracts, adjusted_usd, adjustments_dict)
   - Logs adjustments to logs/size_adjustments.jsonl

3. Integration points:
   - All position sizing functions must use helper
   - Order placement must use helper
   - Position management must validate sizes

4. Files to update:
   - src/kelly_sizing.py
   - src/predictive_sizing.py
   - src/edge_weighted_sizer.py
   - src/alpha_to_execution_adapter.py
   - src/bot_cycle.py (order placement)
```

**Effort:** 6-8 hours  
**Risk:** Medium - Must not break existing sizing logic  
**Priority:** ✅ **DO THIRD**

---

### 🟠 HIGH PRIORITY - Should Implement During Testnet

#### 4. Symbol Allocation Intelligence: Minimum Sample Requirements ✅ HIGH PRIORITY

**Current State:**
- ⚠️ Symbol allocation may happen too early (not enough data)
- ❌ No minimum trade count requirement
- ❌ No minimum days of data requirement
- ⚠️ Could suppress/boost symbols prematurely

**Why High Priority:**
- Prevents premature optimization
- Ensures statistical significance
- Prevents false positives/negatives
- Better learning integrity

**Implementation Plan:**
```
1. Modify: src/symbol_allocation_intelligence.py
   - Add: MIN_TRADES_REQUIRED = 30
   - Add: MIN_DAYS_REQUIRED = 7
   - Check thresholds before reallocation
   - Track metrics: trade_count, days_active, sample_readiness

2. Add metrics tracking:
   - Per-symbol: trade_count, first_trade_date, last_trade_date
   - Calculate: days_active, sample_readiness_pct
   - Store in: feature_store/symbol_allocation_state.json

3. Dashboard:
   - Show per-symbol sample readiness
   - Highlight symbols below thresholds
   - Show when symbols will be "ready" for allocation
```

**Effort:** 3-4 hours  
**Risk:** Low  
**Priority:** ✅ **HIGH**

---

#### 5. Self-Healing: Add Escalation Layer ✅ HIGH PRIORITY

**Current State:**
- ✅ Self-healing exists and works
- ❌ No escalation for repeated failures
- ❌ No tracking of heal patterns
- ❌ Could mask structural issues

**Why High Priority:**
- Prevents infinite heal loops
- Detects structural problems early
- Enables soft kill-switch activation
- Better operational safety

**Implementation Plan:**
```
1. Enhance: src/healing_operator.py
   - Track heal counts in 24h rolling window
   - Categories: files_created, files_repaired, locks_cleared, etc.
   - If any category > threshold (3-5) → raise alert
   - Activate soft kill-switch (block entries, continue exits)

2. Create: logs/healing_escalation_log.jsonl
   - Log all escalation events
   - Track heal counts per category
   - Store escalation triggers

3. Dashboard:
   - Show healing escalation status
   - Alert when thresholds exceeded
   - Show heal pattern trends
```

**Effort:** 4-5 hours  
**Risk:** Low  
**Priority:** ✅ **HIGH**

---

#### 6. Kraken-Specific Health Checks ✅ HIGH PRIORITY

**Current State:**
- ❌ No exchange liveness gate
- ❌ Balance endpoint errors not handled gracefully
- ❌ No exchange-specific health monitoring
- ⚠️ Could continue trading with broken exchange connection

**Why High Priority:**
- Prevents trading with broken API
- Better error handling
- Operational safety

**Implementation Plan:**
```
1. Create: src/exchange_health_monitor.py
   - Tracks consecutive API failures
   - If > 3 failures → mark exchange as DEGRADED
   - Block new entries when degraded
   - Continue managing exits
   - Auto-recover when API responsive again

2. Update: src/kraken_futures_client.py
   - Explicitly handle balance endpoint limitations
   - Log: "Balance endpoint unsupported on testnet; skipping"
   - Don't treat balance errors as critical

3. Integration:
   - Check exchange health before order placement
   - Update dashboard with exchange status
   - Log health state to logs/exchange_health.jsonl
```

**Effort:** 3-4 hours  
**Risk:** Low  
**Priority:** ✅ **HIGH**

---

#### 9. Deployment Safety Checks ✅ HIGH PRIORITY

**Current State:**
- ❌ No pre-deployment validation
- ❌ Could deploy broken code
- ❌ No API key validation before switch

**Why High Priority:**
- Prevents broken deployments
- Catches issues before going live
- Operational safety

**Implementation Plan:**
```
1. Enhance: /root/trading-bot-tools/deploy.sh
   - Before slot switch:
     - Test: EXCHANGE env var exists
     - Test: API keys present (KRAKEN_FUTURES_API_KEY)
     - Test: Venue symbol validation passes
     - Test: Exchange connectivity works
   - Abort deployment if any check fails
   - Log validation results

2. Create: src/deployment_validator.py
   - Centralized validation logic
   - Reusable by deploy script and health checks
```

**Effort:** 2-3 hours  
**Risk:** Low  
**Priority:** ✅ **HIGH**

---

#### 10. Digest & Dashboard Enhancements ✅ HIGH PRIORITY

**Current State:**
- ✅ Dashboard exists
- ❌ No venue symbol validation visibility
- ❌ No self-heal escalation counts
- ❌ No sample size readiness metrics

**Why High Priority:**
- Better operational visibility
- Easier debugging
- Better decision-making

**Implementation Plan:**
```
1. Update: src/pnl_dashboard.py
   - Add section: "Venue Symbol Validation"
     - Show validation status per symbol
     - Show suppressed symbols and reasons
   - Add section: "Self-Heal Escalation"
     - Show heal counts per category
     - Alert if thresholds exceeded
   - Add section: "Symbol Sample Readiness"
     - Show per-symbol: trade_count, days_active, readiness_pct
   - Add section: "Exchange Health"
     - Show exchange liveness status
     - Show last API call timestamp
```

**Effort:** 4-5 hours  
**Risk:** Low  
**Priority:** ✅ **HIGH**

---

### 🟡 MEDIUM PRIORITY - Nice to Have

#### 7. Venue-Local Microstructure Signals ✅ MEDIUM PRIORITY

**Current State:**
- ✅ OFI calculation exists (uses orderbook)
- ❌ Not venue-aware (may use wrong orderbook source)
- ❌ No spread/depth gate
- ❌ No Kraken-specific OFI pulse

**Why Medium Priority:**
- Improves entry timing
- Better liquidity awareness
- Higher quality signals
- But existing signals work, this is enhancement

**Implementation Plan:**
```
1. Create: src/venue_microstructure_gates.py
   - Spread gate: bid_ask_spread_pct, if > threshold → downweight
   - Depth gate: orderbook_depth_usd, if < threshold → reduce size
   - Kraken OFI pulse: Use only Kraken orderbook deltas

2. Integration:
   - Add to conviction gate evaluation
   - Adjust position size based on liquidity
   - Log microstructure metrics
```

**Effort:** 5-6 hours  
**Risk:** Medium - Could affect signal quality  
**Priority:** 🟡 **MEDIUM** (can do later)

---

#### 11. General Codebase Review ✅ MEDIUM PRIORITY

**Current State:**
- ⚠️ Many Blofin references still exist
- ⚠️ Some hardcoded assumptions
- ⚠️ May have venue-specific logic that needs updating

**Why Medium Priority:**
- Important for correctness
- But can be done incrementally
- Some items may be non-critical

**Implementation Plan:**
```
1. Systematic review:
   - Search for "blofin" / "BLOFIN" references
   - Identify hardcoded assumptions
   - Check all execution paths use exchange_gateway
   - Verify all gates are venue-aware

2. Fix incrementally:
   - Critical fixes first (if any)
   - Non-critical fixes in batches
```

**Effort:** 8-12 hours (ongoing)  
**Risk:** Low (if done incrementally)  
**Priority:** 🟡 **MEDIUM** (can do incrementally)

---

### 🟢 LOW PRIORITY - Can Wait

#### 8. CI Integration Tests ✅ LOW PRIORITY

**Current State:**
- ❌ No automated tests
- ✅ Manual testing works

**Why Low Priority:**
- Good practice but not critical
- Manual testing sufficient for now
- Can add later when more mature

**Implementation Plan:**
```
1. Create: .github/workflows/kraken_integration_test.yml
   - Test ExchangeGateway with Kraken
   - Test: get_price(), fetch_ohlcv(), get_orderbook()
   - Assert: Price > 0, Orderbook non-empty, OHLCV valid
   - Run: Manual trigger, nightly, pre-deploy
```

**Effort:** 3-4 hours  
**Risk:** Low  
**Priority:** 🟢 **LOW** (can wait)

---

## Recommended Implementation Order

### Phase 1: Critical Foundations (Week 1)
1. ✅ **Symbol Universe Validation** (Day 1-2)
2. ✅ **Venue-Aware Learning State** (Day 2-3)
3. ✅ **Contract Size & Tick Size** (Day 3-4)

### Phase 2: Safety & Visibility (Week 1-2)
4. ✅ **Symbol Allocation Sample Requirements** (Day 5)
5. ✅ **Self-Healing Escalation** (Day 6)
6. ✅ **Kraken Health Checks** (Day 7)
7. ✅ **Deployment Safety Checks** (Day 8)

### Phase 3: Enhancements (Week 2)
8. ✅ **Dashboard Enhancements** (Day 9-10)
9. 🟡 **Microstructure Signals** (Week 2-3, optional)
10. 🟡 **Codebase Review** (Ongoing, incremental)

### Phase 4: Nice-to-Have (Later)
11. 🟢 **CI Integration Tests** (When ready)

---

## Estimated Total Effort

- **Critical Items:** 16-22 hours
- **High Priority Items:** 16-21 hours
- **Medium Priority:** 13-18 hours (optional)
- **Low Priority:** 3-4 hours (later)

**Total for Critical + High:** ~32-43 hours (~1-1.5 weeks)

---

## Risk Assessment

| Item | Risk Level | Mitigation |
|------|-----------|------------|
| Symbol Validation | Low | Validation only, doesn't change trading |
| Learning Reset | Medium | Test thoroughly, preserve structure |
| Contract Size | Medium | Test with small orders first |
| Sample Requirements | Low | Conservative thresholds |
| Self-Heal Escalation | Low | Adds safety, doesn't break existing |
| Health Checks | Low | Adds monitoring only |
| Deployment Checks | Low | Prevents bad deploys |
| Dashboard | Low | UI only |
| Microstructure | Medium | Test signal impact |
| Codebase Review | Low | Incremental |

---

## Success Criteria

**Before Going Live:**
- ✅ All symbols validated and confirmed tradeable
- ✅ Learning state reset/decayed for Kraken
- ✅ Contract sizes validated for all symbols
- ✅ Exchange health monitoring active
- ✅ Deployment checks passing
- ✅ Dashboard shows all new metrics

**Testnet Validation:**
- ✅ Bot trades successfully on testnet
- ✅ All symbols execute orders correctly
- ✅ No rejected orders due to size/tick issues
- ✅ Learning systems working with Kraken data
- ✅ Health checks detecting issues correctly

---

## Next Steps

1. **Review this plan** - Confirm priorities
2. **Start with Symbol Validation** - Most critical, lowest risk
3. **Test incrementally** - Each item individually
4. **Validate on testnet** - Before moving to next item
5. **Document findings** - Update this plan with learnings

---

**Ready to start?** Begin with Item #1 (Symbol Universe Validation) - it's the foundation for everything else.
