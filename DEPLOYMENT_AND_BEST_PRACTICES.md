# Deployment and Best Practices Guide
## Complete SDLC and Deployment Workflow

**Server IP:** `159.65.168.230`  
**Dashboard URL:** `http://159.65.168.230:8050/`

---

## 📋 Table of Contents

1. [Development Workflow (SDLC)](#development-workflow-sdlc)
2. [Git Deployment Process](#git-deployment-process)
3. [Droplet Deployment Process](#droplet-deployment-process)
4. [Regression Testing](#regression-testing)
5. [Best Practices](#best-practices)
6. [Troubleshooting](#troubleshooting)

---

## 🔄 Development Workflow (SDLC)

### Phase 1: Requirements Analysis
- ✅ Understand user requirements explicitly
- ✅ Document all changes and rationale
- ✅ Identify dependencies and potential impacts

### Phase 2: Design & Implementation
- ✅ Follow existing code patterns and architecture
- ✅ Use standardized field names and data structures
- ✅ Implement robust error handling
- ✅ Add comprehensive logging

### Phase 3: Testing (Before Git Push)
- ✅ **LOCAL TESTING:** Test changes locally when possible
- ✅ **LOGIC VALIDATION:** Verify business logic is correct
- ✅ **ERROR HANDLING:** Test with missing/empty data
- ✅ **MEMORY EFFICIENCY:** Ensure no memory leaks or OOM issues
- ✅ **IMPORT TESTING:** Verify all imports work correctly
- ✅ **CALLBACK TESTING:** For Dash apps, verify callbacks fire correctly

### Phase 4: Code Review & Documentation
- ✅ Self-review code before committing
- ✅ Check for hard-coded values that should be learned
- ✅ Verify error messages are helpful
- ✅ Document any breaking changes

### Phase 5: Git Deployment
- ✅ Commit with descriptive messages
- ✅ Push to `origin main`
- ✅ Verify push succeeded

### Phase 6: Droplet Deployment
- ✅ SSH to droplet
- ✅ Pull latest code
- ✅ Restart service
- ✅ Verify deployment

### Phase 7: Post-Deployment Verification
- ✅ Check service status
- ✅ Verify dashboard loads
- ✅ Test critical functionality
- ✅ Monitor logs for errors

---

## 📤 Git Deployment Process

### Step 1: Review Changes
```bash
# Check what files changed
git status

# Review the actual changes
git diff
```

### Step 2: Stage Changes
```bash
# Stage specific files (preferred)
git add src/pnl_dashboard_v2.py

# Or stage all changes (use with caution)
git add -A
```

### Step 3: Commit with Descriptive Message
```bash
git commit -m "Brief summary of what was changed

DETAILED DESCRIPTION:
- What was fixed/changed
- Why it was changed
- Any breaking changes
- Testing performed"
```

**Example:**
```bash
git commit -m "Fix dashboard memory issues and improve error handling

CRITICAL FIXES:
1. Limit closed positions to 500 to prevent OOM
2. Add timeout for ExchangeGateway initialization
3. Improve error handling in data loading functions
4. Add graceful degradation for missing data

TESTING:
- Verified dashboard loads with 1100+ positions
- Tested error handling with missing files
- Confirmed no SIGKILL errors"
```

### Step 4: Push to Remote
```bash
git push origin main
```

### Step 5: Verify Push
```bash
# Check remote status
git status

# Should show: "Your branch is up to date with 'origin/main'"
```

---

## 🚀 Droplet Deployment Process

### Server Information
- **IP Address:** `159.65.168.230`
- **SSH Command:** `ssh root@159.65.168.230`
- **Dashboard URL:** `http://159.65.168.230:8050/`
- **Service Name:** `tradingbot.service`

### A/B Slot Deployment System

The bot uses an A/B slot deployment system:
- `/root/trading-bot-A` - Slot A
- `/root/trading-bot-B` - Slot B  
- `/root/trading-bot-current` - Symlink to active slot
- `/root/trading-bot-tools/deploy.sh` - Deployment script (if exists)

**Current Active Slot:** Checked via `systemctl status tradingbot`

### Standard Deployment Steps

#### Step 1: Navigate to Active Slot
**Note:** If you're already on the server, skip the SSH step.
```bash
cd /root/trading-bot-current
```

#### Step 3: Pull Latest Code
```bash
git pull origin main
```

**Expected Output:**
```
remote: Enumerating objects: X, done.
remote: Counting objects: 100% (X/X), done.
remote: Compressing objects: 100% (X/X), done.
remote: Total X (delta X), reused X (delta X)
From https://github.com/mlevitan96-crypto/trading-bot
 * branch            main       -> FETCH_HEAD
   <commit-hash>..<commit-hash>  main -> origin/main
Updating <commit-hash>..<commit-hash>
Fast-forward
 <files changed>
```

#### Step 4: Restart Service
```bash
sudo systemctl restart tradingbot
```

#### Step 5: Verify Service Status
```bash
sudo systemctl status tradingbot
```

**Expected Output:**
```
● tradingbot.service - Crypto Trading Bot
   Loaded: loaded (/etc/systemd/system/tradingbot.service; enabled)
   Active: active (running) since <timestamp>
   Main PID: <pid> (python3)
```

#### Step 6: Wait for Initialization
```bash
# Wait 30 seconds for full startup
sleep 30
```

#### Step 7: Verify Dashboard
```bash
# Check HTTP response
curl -I http://localhost:8050/

# Expected: HTTP/1.1 302 FOUND (redirects to /login) or HTTP/1.1 200 OK
```

#### Step 8: Check Logs for Errors
```bash
# Check recent logs
journalctl -u tradingbot --since "2 minutes ago" | tail -50

# Check for errors
journalctl -u tradingbot --since "2 minutes ago" | grep -E "ERROR|Traceback|Exception|Failed" | tail -20

# Check dashboard-specific logs
journalctl -u tradingbot --since "2 minutes ago" | grep -E "DASHBOARD-V2|Dashboard" | tail -20
```

---

## 🧪 Regression Testing

### Pre-Deployment Testing (Before Git Push)

#### 1. Import Testing
```bash
# Test that all imports work
python3 -c "from src.pnl_dashboard_v2 import start_pnl_dashboard; print('✅ Import OK')"
```

#### 2. Build Testing
```bash
# Test that dashboard can be built
python3 -c "from src.pnl_dashboard_v2 import build_app; app = build_app(); print('✅ Build OK' if app else '❌ Build Failed')"
```

#### 3. Logic Testing
```bash
# Test business logic (example for summary calculation)
python3 -c "
total_trades = 0
total_pnl = 0.0
unrealized_pnl = 5.0
net_pnl = total_pnl + (unrealized_pnl if total_trades > 0 else 0.0)
assert net_pnl == 0.0, f'ERROR: Expected 0.0, got {net_pnl}'
print('✅ Logic test passed')
"
```

### Post-Deployment Testing (After Droplet Deployment)

#### 1. Service Health Check
```bash
sudo systemctl status tradingbot
# ✅ Should show "active (running)"
```

#### 2. Dashboard Accessibility
```bash
curl -I http://localhost:8050/
# ✅ Should return HTTP 200 or 302 (not 500 or 404)
```

#### 3. Functional Testing
- ✅ **Login Test:** Access `http://159.65.168.230:8050/` and verify login works
- ✅ **Daily Summary Tab:** Verify data loads, no errors in console
- ✅ **Executive Summary Tab:** Verify content displays
- ✅ **System Health:** Verify indicators show (not all ⚪)
- ✅ **Data Display:** Verify wallet balance, trades, positions display correctly

#### 4. Memory Check
```bash
# Check for OOM kills
journalctl -u tradingbot --since "5 minutes ago" | grep -E "SIGKILL|OOM|Worker.*killed"
# ✅ Should return no results
```

#### 5. Error Check
```bash
# Check for Python errors
journalctl -u tradingbot --since "5 minutes ago" | grep -E "Traceback|UnboundLocalError|AttributeError|TypeError"
# ✅ Should return no critical errors
```

---

## ✅ Best Practices

### Code Quality

1. **Error Handling**
   - Always use try/except blocks around data loading
   - Provide meaningful error messages
   - Log errors with context (flush=True for Dash apps)
   - Never let errors crash the entire dashboard

2. **Memory Management**
   - Limit data loading to reasonable amounts (500-1000 records max)
   - Use time-based filtering when possible (`hours=168` for 7 days)
   - Don't load all data if only recent data is needed
   - Clear large objects when done

3. **Performance**
   - Use caching for expensive operations (price lookups)
   - Limit API calls (use cached data when possible)
   - Use timeouts for network operations (2-3 seconds max)
   - Optimize database/JSON queries

4. **Maintainability**
   - Use standardized field names (from `positions_futures.json`)
   - Follow existing code patterns
   - Add comments for complex logic
   - Keep functions focused and small

5. **Testing**
   - Test locally before pushing
   - Test error conditions (missing files, empty data)
   - Test edge cases (0 trades, negative balances, etc.)
   - Verify no regressions in existing functionality

### Deployment Practices

1. **Always Deploy to Git First**
   - Never make direct changes on droplet
   - All changes go through git
   - Use descriptive commit messages

2. **Verify Before Restarting**
   - Check git pull shows expected changes
   - Verify files were updated correctly
   - Check for merge conflicts

3. **Gradual Rollout**
   - Deploy during low-traffic periods when possible
   - Monitor logs immediately after restart
   - Have rollback plan ready

4. **Documentation**
   - Document what changed and why
   - Update this guide if process changes
   - Keep deployment notes

---

## 🔧 Troubleshooting

### Dashboard Won't Load

**Check 1: Service Status**
```bash
sudo systemctl status tradingbot
```

**Check 2: Port Availability**
```bash
sudo lsof -i :8050
# or
sudo netstat -tlnp | grep 8050
```

**Check 3: Recent Errors**
```bash
journalctl -u tradingbot -n 100 | grep -E "ERROR|Traceback|Exception"
```

**Check 4: Dashboard Startup**
```bash
journalctl -u tradingbot --since "5 minutes ago" | grep -E "DASHBOARD-V2|Dashboard"
```

### Memory Issues (SIGKILL)

**Symptoms:** Worker killed, dashboard crashes

**Solution:**
- Limit data loading (max 500-1000 records)
- Use `DR.get_closed_positions(hours=168)` instead of loading all
- Add timeouts to prevent hanging operations
- Check logs for what was loading when killed

### Import Errors

**Symptoms:** `ModuleNotFoundError` or `ImportError`

**Solution:**
- Verify all imports are correct
- Check if module exists in codebase
- Use fallback imports with try/except
- Verify virtual environment is activated

### Data Not Showing

**Symptoms:** Dashboard loads but shows empty/zero data

**Solution:**
- Check if data files exist: `ls -la /root/trading-bot-current/logs/positions_futures.json`
- Verify DataRegistry can read files
- Check error logs for data loading failures
- Verify path resolution is correct

---

## 📝 Deployment Checklist

Use this checklist for every deployment:

### Pre-Deployment
- [ ] Code changes tested locally (if possible)
- [ ] Logic validated (no obvious bugs)
- [ ] Error handling added for edge cases
- [ ] Memory usage considered (data limits added)
- [ ] Documentation updated (if needed)

### Git Deployment
- [ ] `git status` shows expected changes
- [ ] `git diff` reviewed
- [ ] Commit message is descriptive
- [ ] `git push origin main` succeeded
- [ ] Verified push on GitHub (optional)

### Droplet Deployment
- [ ] SSH to droplet: `ssh root@159.65.168.230`
- [ ] Navigate: `cd /root/trading-bot-current`
- [ ] Pull: `git pull origin main` (verify changes pulled)
- [ ] Restart: `sudo systemctl restart tradingbot`
- [ ] Wait 30 seconds
- [ ] Verify status: `sudo systemctl status tradingbot`
- [ ] Check dashboard: `curl -I http://localhost:8050/`
- [ ] Check logs: `journalctl -u tradingbot --since "2 minutes ago" | tail -30`
- [ ] Verify no errors: Check for ERROR/Traceback in logs

### Post-Deployment
- [ ] Dashboard accessible via browser: `http://159.65.168.230:8050/`
- [ ] Login works
- [ ] Daily Summary tab loads data
- [ ] Executive Summary tab loads
- [ ] System Health shows status
- [ ] No SIGKILL/OOM errors
- [ ] No critical errors in logs

---

## 🎯 Quick Reference

### Server Details
```
IP: 159.65.168.230
Dashboard: http://159.65.168.230:8050/
SSH: ssh root@159.65.168.230
Service: tradingbot.service
Active Slot: /root/trading-bot-current
```

### Common Commands

**Deploy:**
```bash
ssh root@159.65.168.230
cd /root/trading-bot-current
git pull origin main
sudo systemctl restart tradingbot
sleep 30
curl -I http://localhost:8050/
```

**Check Status:**
```bash
sudo systemctl status tradingbot
journalctl -u tradingbot --since "2 minutes ago" | tail -30
```

**View Dashboard Logs:**
```bash
journalctl -u tradingbot --since "10 minutes ago" | grep -E "DASHBOARD-V2|Dashboard"
```

**Check for Errors:**
```bash
journalctl -u tradingbot --since "10 minutes ago" | grep -E "ERROR|Traceback|Exception|SIGKILL"
```

---

## 📌 Important Notes

1. **Always deploy to git first** - Never make direct changes on droplet
2. **Test before deploying** - Verify changes work locally when possible
3. **Monitor after deployment** - Check logs immediately after restart
4. **Use limits** - Always limit data loading to prevent OOM
5. **Handle errors gracefully** - Dashboard should always load, even with errors
6. **Log everything** - Use `flush=True` for Dash apps, add context to errors
7. **Document changes** - Commit messages should explain what and why

---

**Last Updated:** 2025-12-19  
**Maintainer:** AI Assistant  
**Review Frequency:** After each major change
