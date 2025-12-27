# Golden Hour Performance Review Setup

**Date:** 2025-12-27  
**Status:** ✅ Complete

---

## Overview

Created a comprehensive Golden Hour performance review system that generates daily and weekly reports with both summary and detailed analysis.

---

## What Was Created

### 1. Performance Review Generator
**File:** `src/golden_hour_performance_review.py`

A Python script that:
- Analyzes Golden Hour trades (09:00-16:00 UTC) vs Non-Golden Hour
- Generates daily reports (last 24 hours)
- Generates weekly reports (last 7 days)
- Creates both summary and detailed markdown reports
- Saves JSON data for programmatic access
- All files are git-tracked for external review

### 2. Reports Directory
**Directory:** `reports/`

Contains:
- `README.md` - Documentation for the reports
- Daily summary reports: `golden_hour_daily_summary_YYYY-MM-DD.md`
- Daily detailed reports: `golden_hour_daily_detailed_YYYY-MM-DD.md`
- Daily data files: `golden_hour_daily_data_YYYY-MM-DD.json`
- Weekly summary reports: `golden_hour_weekly_summary_YYYY-MM-DD.md`
- Weekly detailed reports: `golden_hour_weekly_detailed_YYYY-MM-DD.md`
- Weekly data files: `golden_hour_weekly_data_YYYY-MM-DD.json`

---

## Report Contents

### Summary Reports Include:
- Executive summary comparing Golden Hour vs Non-Golden Hour
- Key performance metrics (win rate, P&L, profit factor)
- Top performing symbols (top 10)
- Top performing strategies (top 10)
- Quick insights and conclusions

### Detailed Reports Include:
- Complete performance metrics (all statistics)
- Detailed breakdown by symbol (all symbols)
- Detailed breakdown by strategy (all strategies)
- Performance comparison tables
- Hold time analysis
- All supporting statistics

---

## Usage

### Generate Reports Manually

```bash
python3 src/golden_hour_performance_review.py
```

This generates both daily and weekly reports for the current date.

### Automated Daily Generation

Add to cron or systemd timer:

```bash
# Daily at 00:00 UTC
0 0 * * * cd /root/trading-bot-current && python3 src/golden_hour_performance_review.py && cd /root/trading-bot-current && git add reports/ && git commit -m "Daily Golden Hour performance review" && git push origin main
```

Or create a systemd timer:

```ini
# /etc/systemd/system/golden-hour-review.timer
[Unit]
Description=Golden Hour Performance Review Timer
After=network.target

[Timer]
OnCalendar=daily
OnCalendar=00:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/golden-hour-review.service
[Unit]
Description=Golden Hour Performance Review
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/root/trading-bot-current
ExecStart=/usr/bin/python3 /root/trading-bot-current/src/golden_hour_performance_review.py
ExecStartPost=/usr/bin/git -C /root/trading-bot-current add reports/
ExecStartPost=/usr/bin/git -C /root/trading-bot-current commit -m "Daily Golden Hour performance review"
ExecStartPost=/usr/bin/git -C /root/trading-bot-current push origin main
```

---

## External Review

All reports are:
- ✅ Git-tracked (committed to repository)
- ✅ Available for download from GitHub
- ✅ Version controlled for historical tracking
- ✅ Ready to share with external reviewers

### Sharing Reports

1. **Download from GitHub:**
   - Navigate to `reports/` directory in the repository
   - Download individual markdown files
   - Or download the entire `reports/` directory

2. **Clone Repository:**
   ```bash
   git clone <repository-url>
   cd trading-bot/reports
   ls -la
   ```

3. **View Online:**
   - GitHub renders markdown files automatically
   - View reports directly in the browser

---

## Report Structure

### Daily Reports
- **Period:** Last 24 hours
- **Files:** Generated daily with current date
- **Naming:** `golden_hour_daily_*_YYYY-MM-DD.*`

### Weekly Reports
- **Period:** Last 7 days
- **Files:** Generated daily with current date (shows week range)
- **Naming:** `golden_hour_weekly_*_YYYY-MM-DD.*`

---

## Data Source

Reports use the canonical data source:
- **File:** `logs/positions_futures.json`
- **Source:** `closed_positions` array
- **Golden Hour Window:** 09:00-16:00 UTC (based on `closed_at` timestamp)

---

## Metrics Calculated

### Trade Statistics
- Total trades
- Wins / Losses
- Win rate

### P&L Metrics
- Total P&L
- Average P&L
- Gross profit / Gross loss
- Profit factor
- Average win / Average loss
- Max win / Max loss

### Timing Metrics
- Average hold time
- Total hold time
- Shortest / Longest hold

### Breakdowns
- By symbol (all symbols with stats)
- By strategy (all strategies with stats)

---

## Next Steps

1. ✅ Script created and tested
2. ✅ Reports directory created
3. ✅ Initial reports generated
4. ⏳ Set up automated daily generation (optional)
5. ⏳ Review reports and adjust format if needed

---

## Status: ✅ **COMPLETE**

The Golden Hour performance review system is ready for use. Reports are generated, git-tracked, and available for external review.

