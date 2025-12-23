# Git Push Commands - Copy/Paste

## Quick Push (If Already on Droplet)

```bash
cd /root/trading-bot-B
git pull origin main
git add backfill_volatility_snapshots.py PERFORMANCE_ANALYSIS_DEC23.md
git commit -m "Add backfill script and performance analysis"
git push origin main
```

## Analyze Why Logging Failed

```bash
cd /root/trading-bot-B
python3 backfill_volatility_snapshots.py --analyze
```

## Attempt Backfill (Optional - Modifies Data)

```bash
cd /root/trading-bot-B
python3 backfill_volatility_snapshots.py --backfill
# Type 'yes' when prompted
```

## Complete Workflow (Pull → Analyze → Commit → Push)

```bash
cd /root/trading-bot-B
git pull origin main
python3 backfill_volatility_snapshots.py --analyze
git add backfill_volatility_snapshots.py PERFORMANCE_ANALYSIS_DEC23.md
git commit -m "Add backfill script and performance analysis"
git push origin main
```

