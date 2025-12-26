# Standard Deployment Procedure

## Overview

This project uses **A/B slot-based deployment** for zero-downtime updates with easy rollback capability.

**IMPORTANT**: The bot **MUST always run under systemd** (`tradingbot.service`). Never run the bot manually in production.

## Architecture

- **`/root/trading-bot-A`** - Slot A
- **`/root/trading-bot-B`** - Slot B  
- **`/root/trading-bot-current`** - Symlink pointing to active slot
- **`/root/trading-bot-tools/`** - Deployment tools

Only one slot is active at a time via the symlink. Deployments update the inactive slot, then switch.

## Standard Deployment Process

### Step 1: Commit and Push Changes Locally

On your local machine:

```bash
cd /path/to/trading-bot
git add .
git commit -m "Description of changes"
git push origin main
```

### Step 2: Deploy to Droplet

SSH into your droplet using `ssh kraken` and run:

```bash
/root/trading-bot-tools/deploy.sh
```

**What the script does:**
1. ✅ Determines active slot (A or B)
2. ✅ Pulls latest code into inactive slot
3. ✅ Creates/updates virtual environment
4. ✅ Installs dependencies
5. ✅ Runs health checks (if available)
6. ✅ Stops service
7. ✅ Switches symlink to updated slot
8. ✅ Starts service

### Step 3: Verify Deployment

```bash
# Check service status (MANDATORY - bot MUST run via systemd)
systemctl status tradingbot

# Check which slot is active
ls -la /root/trading-bot-current

# Check recent logs via systemd journal
journalctl -u tradingbot -f
journalctl -u tradingbot -n 100

# Verify code version
cd /root/trading-bot-current
git log --oneline -1
```

**⚠️ CRITICAL**: Always use `systemctl status tradingbot` and `journalctl -u tradingbot` to check bot status. The bot MUST run under systemd service management, never manually.

## Rollback Procedure

If something goes wrong, quickly rollback:

```bash
# Determine which slot is currently active
CURRENT=$(readlink -f /root/trading-bot-current)

# Switch to other slot
if [[ "$CURRENT" == "/root/trading-bot-A" ]]; then
    systemctl stop tradingbot
    ln -sfn /root/trading-bot-B /root/trading-bot-current
    systemctl start tradingbot
else
    systemctl stop tradingbot
    ln -sfn /root/trading-bot-A /root/trading-bot-current
    systemctl start tradingbot
fi
```

## Health Checks

The deployment script runs health checks if `health_check.sh` exists:

```bash
/root/trading-bot-tools/health_check.sh /root/trading-bot-A
```

Create this file to add pre-deployment validation.

## Manual Deployment (Alternative)

If you need to deploy manually:

```bash
# 1. Determine active slot
ACTIVE=$(readlink -f /root/trading-bot-current)

# 2. Set inactive slot
if [[ "$ACTIVE" == "/root/trading-bot-A" ]]; then
    INACTIVE="/root/trading-bot-B"
else
    INACTIVE="/root/trading-bot-A"
fi

# 3. Pull changes into inactive slot
cd "$INACTIVE"
git pull origin main

# 4. Install dependencies
"$INACTIVE/venv/bin/pip" install -r requirements.txt

# 5. Switch (with service restart)
systemctl stop tradingbot
ln -sfn "$INACTIVE" /root/trading-bot-current
systemctl start tradingbot
```

## Best Practices

1. **Always use the deploy script** - It handles edge cases and ensures consistency
2. **Test locally first** - Verify changes work before deploying
3. **Check logs after deployment** - Ensure no errors on startup
4. **Monitor dashboard** - Verify all systems are green
5. **Keep both slots updated** - Helps with quick rollback

## Troubleshooting

### Service won't start
```bash
systemctl status tradingbot
journalctl -u tradingbot -n 50
```

### Dependencies missing
```bash
cd /root/trading-bot-current
venv/bin/pip install -r requirements.txt
```

### Wrong slot active
```bash
# Check current
ls -la /root/trading-bot-current

# Switch manually (see rollback procedure above)
```

## Notes

- The deployment script uses `set -euo pipefail` for safety
- Service is stopped briefly during symlink switch (minimal downtime)
- Health checks are optional but recommended
- Both slots should remain git repositories for easy switching
