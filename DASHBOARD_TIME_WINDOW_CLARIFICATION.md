# Dashboard Time Window Clarification

## Understanding the Time Windows

### 1. **24-Hour Rolling Window** (Last 24 Hours)
- **Definition**: ALL trades that occurred in the last 24 hours
- **Includes**: 
  - Trades during Golden Hour (09:00-16:00 UTC) in the last 24h
  - Trades outside Golden Hour in the last 24h
- **Example**: If it's currently 20:00 UTC, this includes trades from 20:00 UTC yesterday to now
- **Current Dashboard**: "Daily Summary (Last 24 Hours - All Trades)"

### 2. **Golden Hour Window** (09:00-16:00 UTC)
- **Definition**: Trades that occurred during 09:00-16:00 UTC
- **Current Display**: All-time comprehensive data (from GOLDEN_HOUR_ANALYSIS.json)
- **Could Also Show**: Last 24h of Golden Hour trades (subset of 24h window)
- **Example**: If a trade closed at 10:00 UTC today and another at 22:00 UTC yesterday
  - Both are in the 24h window
  - Only the 10:00 UTC trade is in Golden Hour
  - The 22:00 UTC trade is NOT in Golden Hour

## Relationship

```
24-Hour Window (ALL trades)
├── Golden Hour trades in last 24h (09:00-16:00 UTC, last 24h)
└── Non-Golden Hour trades in last 24h (outside 09:00-16:00 UTC, last 24h)
```

**Key Point**: Golden Hour trades (in last 24h) are a SUBSET of the 24-hour window.

## Current Dashboard Implementation

### Daily Summary Tab

1. **Daily Summary (Last 24 Hours - All Trades)**
   - Shows: ALL trades in last 24 hours
   - Includes: Golden Hour + Non-Golden Hour trades
   - Source: `positions_futures.json` filtered by timestamp

2. **Golden Hour Trading (All-Time Analysis)**
   - Shows: All-time comprehensive Golden Hour stats
   - Includes: All trades during 09:00-16:00 UTC (historical)
   - Source: `GOLDEN_HOUR_ANALYSIS.json`

### Potential Enhancement

Could add a third summary card:
- **Golden Hour Trading (Last 24 Hours)**
  - Shows: Trades during 09:00-16:00 UTC in the last 24h
  - This is the SUBSET of "Daily Summary (Last 24 Hours)"
  - Source: `positions_futures.json` filtered by timestamp AND hour

## Verification

The current implementation correctly distinguishes:
- ✅ 24h window = ALL trades (includes Golden Hour + non-Golden Hour)
- ✅ Golden Hour = Only 09:00-16:00 UTC (currently all-time, but could show 24h)

## Question for User

Do you want:
1. Keep current: Golden Hour shows all-time data only
2. Add: Golden Hour (Last 24 Hours) card showing 24h rolling Golden Hour trades
3. Replace: Change Golden Hour to show 24h rolling instead of all-time

