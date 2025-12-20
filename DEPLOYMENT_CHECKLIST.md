# Quick Deployment Checklist

## 🚀 Standard Deployment (Use Every Time)

### 1. Local Development & Testing
```bash
# Test imports
python3 -c "from src.pnl_dashboard_v2 import start_pnl_dashboard; print('OK')"

# Verify logic (if applicable)
# Test error handling with missing data
```

### 2. Git Deployment
```bash
git add <changed-files>
git commit -m "Descriptive commit message"
git push origin main
```

### 3. Droplet Deployment
```bash
# Navigate and pull (if already on server, skip SSH)
cd /root/trading-bot-current
git pull origin main

# Restart service
sudo systemctl restart tradingbot

# Wait and verify
sleep 30
sudo systemctl status tradingbot
curl -I http://localhost:8050/
```

### 4. Post-Deployment Verification
```bash
# Check logs
journalctl -u tradingbot --since "2 minutes ago" | grep -E "DASHBOARD-V2|ERROR|Traceback" | tail -20

# Test in browser
# Go to: http://159.65.168.230:8050/
# Login and verify dashboard loads
```

---

## ✅ Verification Commands

### Service Health
```bash
sudo systemctl status tradingbot
# Should show: active (running)
```

### Dashboard Access
```bash
curl -I http://localhost:8050/
# Should return: HTTP/1.1 200 OK or 302 FOUND
```

### Error Check
```bash
journalctl -u tradingbot --since "5 minutes ago" | grep -E "ERROR|Traceback|SIGKILL|OOM"
# Should return: nothing (no errors)
```

### Dashboard Logs
```bash
journalctl -u tradingbot --since "5 minutes ago" | grep "DASHBOARD-V2"
# Should show: initialization, building, success messages
```

---

## 🚨 Emergency Rollback

If deployment breaks the dashboard:

```bash
# On droplet
cd /root/trading-bot-current
git log --oneline -5  # Find previous working commit
git checkout <previous-commit-hash>
sudo systemctl restart tradingbot
```

Or revert last commit:
```bash
git revert HEAD
git push origin main
# Then redeploy
```
