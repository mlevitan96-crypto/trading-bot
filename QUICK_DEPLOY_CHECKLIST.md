# Quick Deployment Checklist

## Pre-Deployment ✅
- [x] All code committed to GitHub
- [x] All integration patterns verified
- [x] All dependencies documented in requirements.txt
- [x] Deployment documentation created

## On Droplet - Execute These Commands

```bash
# 1. Navigate to project directory
cd /root/trading-bot-current

# 2. Pull latest code
git pull origin main

# 3. Activate virtual environment
source venv/bin/activate

# 4. Install/update dependencies
pip install -r requirements.txt

# 5. Verify integration patterns (no imports needed)
python verify_integration_code.py

# 6. Check service status
systemctl status trading-bot

# 7. Restart service
systemctl restart trading-bot

# 8. Monitor logs for startup
journalctl -u trading-bot -f --lines=100
```

## Expected Log Messages

Look for these in the logs:
```
✅ [SHADOW] Shadow portfolio comparison started (4-hour cycle)
✅ [POLICY-TUNER] Policy optimizer started (daily at 3 AM UTC)
✅ [DRIFT] Feature drift detection started (6-hour cycle)
```

## Verification Checklist

- [ ] Code pulled successfully
- [ ] Dependencies installed (numpy, hmmlearn, optuna)
- [ ] Verification script passed (12/12 checks)
- [ ] Service started without errors
- [ ] All three schedulers started
- [ ] No import errors in logs
- [ ] Integration markers visible in logs

## If Something Fails

1. Check logs: `journalctl -u trading-bot --no-pager | tail -100`
2. Run verification: `python verify_integration_code.py`
3. Check dependencies: `pip list | grep -E "numpy|hmmlearn|optuna"`
4. Review DEPLOY_TO_DROPLET.md for troubleshooting

