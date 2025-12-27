# Golden Hour Performance Reports

This directory contains daily and weekly performance reviews for Golden Hour trading (09:00-16:00 UTC).

## Report Types

### Daily Reports
- **Summary:** `golden_hour_daily_summary_YYYY-MM-DD.md` - Executive summary with key metrics
- **Detailed:** `golden_hour_daily_detailed_YYYY-MM-DD.md` - Comprehensive analysis with full breakdowns
- **Data:** `golden_hour_daily_data_YYYY-MM-DD.json` - Raw analysis data in JSON format

### Weekly Reports
- **Summary:** `golden_hour_weekly_summary_YYYY-MM-DD.md` - Executive summary for the week
- **Detailed:** `golden_hour_weekly_detailed_YYYY-MM-DD.md` - Comprehensive weekly analysis
- **Data:** `golden_hour_weekly_data_YYYY-MM-DD.json` - Raw weekly analysis data

## Generating Reports

Run the performance review generator:

```bash
python3 src/golden_hour_performance_review.py
```

This will generate both daily and weekly reports for the current date.

## Report Contents

### Summary Reports Include:
- Executive summary comparing Golden Hour vs Non-Golden Hour performance
- Key performance metrics (win rate, P&L, profit factor)
- Top performing symbols and strategies
- Quick insights and conclusions

### Detailed Reports Include:
- Complete performance metrics
- Detailed breakdown by symbol
- Detailed breakdown by strategy
- Performance comparison tables
- Hold time analysis
- All supporting statistics

## Automation

To run daily, add to cron or systemd timer:

```bash
# Daily at 00:00 UTC
0 0 * * * cd /root/trading-bot-current && python3 src/golden_hour_performance_review.py
```

## External Review

All reports are git-tracked and can be:
- Downloaded from the repository
- Shared with external reviewers
- Version controlled for historical tracking

