# Expansive Analyzer Self-Healing & Monitoring

## Overview

The **Expansive Multi-Dimensional Profitability Analyzer** includes comprehensive self-healing and monitoring capabilities to ensure robust, autonomous operation.

## Self-Healing Features

### 1. Error Handling with Graceful Degradation

**Partial Results Generation:**
- If one analysis component fails, others continue
- Returns partial results instead of complete failure
- Tracks which components succeeded vs failed
- Reports errors without crashing entire analysis

**Example:**
```python
# If "by_symbol" fails but "by_strategy" succeeds:
{
    "status": "partial_success",
    "by_symbol": {"error": "...", "status": "failed"},
    "by_strategy": {...},  # Full results
    "components_completed": ["by_strategy", ...],
    "components_failed": ["by_symbol"]
}
```

### 2. Data Loading Error Recovery

**Corrupted File Handling:**
- Invalid JSON lines skipped with warnings logged
- Missing files handled gracefully (empty lists)
- Corrupted files detected and reported
- Analysis continues with available data

**File Validation:**
- Checks file existence before reading
- Validates JSON structure
- Handles encoding errors
- Logs specific line numbers for debugging

### 3. Symbol Normalization Robustness

**Multi-Format Support:**
- Handles internal format (`BTCUSDT`)
- Handles Kraken format (`PI_XBTUSD`)
- Handles Blofin format (`BTC-USDT`)
- Normalizes for consistent matching

**Fallback Mechanisms:**
- Uses `exchange_utils` when available
- Falls back to built-in normalization if module missing
- Handles edge cases (None, empty strings, malformed)

### 4. Health Status Tracking

**Status File:**
- Location: `feature_store/expansive_analyzer_status.json`
- Updated after each analysis run
- Tracks:
  - Last run timestamp
  - Success/failure status
  - Components completed/failed
  - Error count
  - Execution time

**Health Log:**
- Location: `logs/expansive_analyzer_health.jsonl`
- Logs every analysis run
- Keeps last 1000 events (prevents log bloat)
- Includes errors, warnings, performance metrics

## Monitoring Integration

### 1. Healing Operator Integration

**Automatic Monitoring:**
- Healing Operator checks analyzer health every 60 seconds
- Detects stale status files (>72 hours)
- Detects high error counts (>5 errors)
- Detects corrupted status files (auto-recreates)

**Healing Actions:**
- Recreates corrupted status files
- Detects and reports stale status
- Monitors error trends
- Provides status for dashboard

### 2. Learning Health Monitor Integration

**Health Check Method:**
```python
ExpansiveMultiDimensionalProfitabilityAnalyzer.check_health()
```

**Returns:**
- `green`: All components successful
- `yellow`: Partial success or stale status
- `red`: Unhealthy or status unknown

**Health Check Details:**
- Last run timestamp
- Components completed/failed
- Error count
- Execution time
- Staleness detection

### 3. Status Monitoring

**Status Levels:**
- `success`: All components completed successfully
- `partial_success`: Some components failed but analysis ran
- `failed`: Critical failure or all components failed
- `unknown`: Status file missing or unparseable

**Staleness Detection:**
- Flags status older than 48 hours as stale
- Healing Operator flags status older than 72 hours
- Triggers alerts if analyzer hasn't run recently

## Best Practices Implemented

### 1. Comprehensive Logging

**Logging Levels:**
- `ERROR`: Critical failures (logged with traceback)
- `WARNING`: Non-critical issues (corrupted lines, missing data)
- `INFO`: Normal operation (component completion)

**Log Locations:**
- `logs/expansive_analyzer_health.jsonl`: Health events
- Python logger: Error details with tracebacks
- Console output: User-friendly progress messages

### 2. Error Recovery

**Try-Except Blocks:**
- Each analysis component wrapped in try-except
- Data loading wrapped in try-except
- File operations wrapped in try-except
- Graceful fallbacks for all operations

**Error Reporting:**
- Errors collected in analysis dict
- Errors logged to health log
- Errors included in status file
- No silent failures

### 3. Performance Monitoring

**Execution Time Tracking:**
- Records total execution time
- Logged in status file
- Logged in health events
- Can identify performance degradation

**Memory Safety:**
- Processes data in batches where possible
- Limits log file size (1000 events)
- Handles large datasets efficiently

### 4. Data Integrity

**File Integrity Checks:**
- Validates JSON structure before processing
- Handles corrupted lines gracefully
- Skips invalid records with warnings
- Continues processing valid data

**Data Validation:**
- Validates symbol formats
- Validates timestamp formats
- Validates numeric values
- Handles missing/null values

## Health Check API

### For Monitoring Systems

```python
from src.expansive_multi_dimensional_profitability_analyzer import ExpansiveMultiDimensionalProfitabilityAnalyzer

# Get health status
health = ExpansiveMultiDimensionalProfitabilityAnalyzer.check_health()

# Returns:
{
    "status": "healthy" | "degraded" | "unhealthy" | "unknown",
    "details": {
        "last_run": "2025-12-15T10:00:00Z",
        "status": "success",
        "components_completed": 16,
        "components_failed": 0,
        "error_count": 0,
        "execution_time_seconds": 45.2,
        "age_hours": 2.5,
        "is_stale": False
    }
}
```

### For Healing Operator

```python
# Healing operator format
health = ExpansiveMultiDimensionalProfitabilityAnalyzer.check_health()
healing_status = {
    "status": "green" | "yellow" | "red",
    "message": "Status description",
    "last_run": "...",
    "components_completed": 16,
    "components_failed": 0,
    "errors": 0
}
```

## Failure Modes & Recovery

### Scenario 1: Missing Data Files

**Detection:**
- File existence checks before reading
- Empty result sets detected

**Recovery:**
- Returns empty results for affected components
- Continues with other analyses
- Reports missing files in warnings

**Status:** `partial_success` or `success` (if other data available)

### Scenario 2: Corrupted Data Files

**Detection:**
- JSON parsing errors
- Invalid structure errors

**Recovery:**
- Skips corrupted lines
- Logs line numbers for debugging
- Continues processing valid lines
- Reports corruption in warnings

**Status:** `partial_success`

### Scenario 3: Analysis Component Failure

**Detection:**
- Exception caught during component execution
- Error logged with traceback

**Recovery:**
- Component marked as failed
- Other components continue
- Partial results returned
- Error details included in response

**Status:** `partial_success`

### Scenario 4: Critical System Failure

**Detection:**
- Exception in main analysis function
- All components fail

**Recovery:**
- Minimal error response returned
- Error logged with full traceback
- Status file updated with failure
- Health log records failure

**Status:** `failed`

### Scenario 5: Stale Status

**Detection:**
- Status file age > 48 hours
- Healing Operator detects > 72 hours

**Recovery:**
- Healing Operator reports staleness
- Dashboard shows warning
- No auto-run (analysis runs on schedule)
- Status cleared when analyzer runs again

**Status:** `yellow` (stale but not broken)

## Integration Points

### 1. Nightly Learning Cycle

The analyzer runs as part of the **Profitability Trader Persona** nightly cycle:
- Called at scheduled time (10:30 UTC)
- Errors don't stop other learning systems
- Results integrated into profitability analysis
- Health status tracked

### 2. Healing Operator

Monitors analyzer every 60 seconds:
- Checks status file freshness
- Detects corruption
- Reports health to dashboard
- Auto-recreates corrupted status files

### 3. Learning Health Monitor

Includes analyzer in learning system health checks:
- Reports analyzer health
- Includes in overall learning health status
- Tracks component failures
- Monitors execution performance

## Status Indicators

### Dashboard Integration

The analyzer health is visible in:
- Self-healing status (yellow if stale, red if unhealthy)
- Learning systems health
- System status overview

### Log Files

- `logs/expansive_analyzer_health.jsonl`: Every run logged
- `feature_store/expansive_analyzer_status.json`: Latest status
- Python logs: Error details with tracebacks

## Conclusion

✅ **The Expansive Analyzer is fully self-healing and monitored:**
- Comprehensive error handling
- Graceful degradation (partial results)
- Health status tracking
- Integration with healing systems
- Automatic recovery from common failures
- Performance monitoring
- Data integrity validation

**The analyzer will continue operating even when:**
- Some data files are missing
- Some files have corrupted lines
- Some analysis components fail
- Status files are corrupted

**The analyzer reports issues without crashing**, ensuring the bot's profitability analysis continues uninterrupted.
