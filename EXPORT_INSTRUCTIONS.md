# Simple Export Instructions

## Step 1: Run the Analysis (if you haven't already)

```bash
cd /root/trading-bot-current
python3 analyze_signal_components.py
```

This creates: `/root/trading-bot-B/feature_store/signal_component_analysis.json`

## Step 2: Run the Export Script

```bash
cd /root/trading-bot-current
python3 export_signal_analysis.py
```

This creates two files:
1. `/root/trading-bot-B/feature_store/signal_analysis_export.csv`
2. `/root/trading-bot-B/feature_store/signal_analysis_summary.json`

## Step 3: Get the Files (Choose One Method)

### Option A: View on Server (Easiest)
```bash
# View the CSV (first 20 lines)
head -20 /root/trading-bot-B/feature_store/signal_analysis_export.csv

# View the summary
cat /root/trading-bot-B/feature_store/signal_analysis_summary.json | python3 -m json.tool
```

### Option B: Copy to Home Directory (Easy Download)
```bash
# Copy files to your home directory
cp /root/trading-bot-B/feature_store/signal_analysis_export.csv ~/
cp /root/trading-bot-B/feature_store/signal_analysis_summary.json ~/

# Then download via SFTP/FTP client, or use:
ls -lh ~/signal_analysis_export.csv
ls -lh ~/signal_analysis_summary.json
```

### Option C: Download via SCP (from your local computer)
```bash
# Replace YOUR_SERVER_IP with your actual server IP
scp root@YOUR_SERVER_IP:/root/trading-bot-B/feature_store/signal_analysis_export.csv .
scp root@YOUR_SERVER_IP:/root/trading-bot-B/feature_store/signal_analysis_summary.json .
```

### Option D: Create a Web-Accessible Link (if you have a web server)
```bash
# Copy to web directory (if you have one)
cp /root/trading-bot-B/feature_store/signal_analysis_export.csv /var/www/html/
cp /root/trading-bot-B/feature_store/signal_analysis_summary.json /var/www/html/

# Then access via: http://your-server-ip/signal_analysis_export.csv
```

### Option E: Email the Files (if mail is configured)
```bash
# Attach files to email (if mailx is installed)
echo "Signal analysis export" | mailx -s "Trading Bot Analysis" -a /root/trading-bot-B/feature_store/signal_analysis_export.csv -a /root/trading-bot-B/feature_store/signal_analysis_summary.json your-email@example.com
```

## Quick One-Liner to See File Locations

```bash
echo "CSV: /root/trading-bot-B/feature_store/signal_analysis_export.csv"
echo "JSON: /root/trading-bot-B/feature_store/signal_analysis_summary.json"
ls -lh /root/trading-bot-B/feature_store/signal_analysis_export.csv
ls -lh /root/trading-bot-B/feature_store/signal_analysis_summary.json
```

## What Each File Contains

**CSV File** (`signal_analysis_export.csv`):
- All trades with columns for easy analysis in Excel/Google Sheets
- Can be opened in any spreadsheet program
- Contains: trade details, P&L, signals, components, regime

**Summary JSON** (`signal_analysis_summary.json`):
- High-level findings
- Hypothesis test results
- Data availability stats
- Key findings automatically extracted

## Troubleshooting

**If files don't exist:**
```bash
# Check if analysis was run
ls -lh /root/trading-bot-B/feature_store/signal_component_analysis.json

# If missing, run:
python3 analyze_signal_components.py
python3 export_signal_analysis.py
```

**To see what's in the files:**
```bash
# Count lines in CSV (should be 1500+ trades)
wc -l /root/trading-bot-B/feature_store/signal_analysis_export.csv

# View first few trades
head -5 /root/trading-bot-B/feature_store/signal_analysis_export.csv
```
