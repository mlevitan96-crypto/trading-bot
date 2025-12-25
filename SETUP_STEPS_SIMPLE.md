# Simple Setup Steps - Everything You Need

## ✅ What We're Setting Up

1. Git works on droplet (both Slot A and Slot B)
2. Auto-commit and push generated reports
3. Cursor can see everything on droplet
4. Works no matter which slot is active

---

## 📋 ALL STEPS (Do These In Order)

### STEP 1: Test Connection
**On your computer**, run:
```bash
python3 tools/droplet_client.py status
```

**If it works:** You'll see git status. Go to Step 2.

**If it fails:** You need to set up SSH. See "Fix Connection" at the bottom.

---

### STEP 2: Connect to Droplet
**On your computer**, run:
```bash
ssh kraken
```

Enter password if asked. You should see: `root@your-droplet:~#`

---

### STEP 3: Check Which Slot is Active
**On droplet**, run:
```bash
readlink -f /root/trading-bot-current
```

**Write down the result** - it will be either:
- `/root/trading-bot-A` 
- `/root/trading-bot-B`

---

### STEP 4: Set Up Git in Slot A
**On droplet**, run these commands one at a time:
```bash
cd /root/trading-bot-A
git config user.name "Mark Levitan"
git config user.email "mlevitan96@gmail.com"
```

---

### STEP 5: Set Up Git in Slot B
**On droplet**, run these commands one at a time:
```bash
cd /root/trading-bot-B
git config user.name "Mark Levitan"
git config user.email "mlevitan96@gmail.com"
```

---

### STEP 6: Get GitHub Token
1. Go to: https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Name: "Droplet Access"
4. Check box: **"repo"** (full control)
5. Click "Generate token"
6. **COPY THE TOKEN** (starts with `ghp_`)

---

### STEP 7: Set Up Git Remote in Slot A
**On droplet**, replace `YOUR_TOKEN` with the token you copied:
```bash
cd /root/trading-bot-A
git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
```

---

### STEP 8: Set Up Git Remote in Slot B
**On droplet**, use the same token:
```bash
cd /root/trading-bot-B
git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
```

---

### STEP 9: Test Push in Slot A
**On droplet**:
```bash
cd /root/trading-bot-A
git push origin main --dry-run
```

**Should see:** "Everything up-to-date" or similar (no errors)

---

### STEP 10: Test Push in Slot B
**On droplet**:
```bash
cd /root/trading-bot-B
git push origin main --dry-run
```

**Should see:** "Everything up-to-date" or similar (no errors)

---

### STEP 11: Create Auto-Push Hook in Slot A
**On droplet**, copy and paste this entire block:
```bash
cd /root/trading-bot-A
cat > .git/hooks/post-commit << 'EOF'
#!/bin/bash
cd /root/trading-bot-A
if git diff --cached --name-only | grep -E "\.(md|json)$|reports/|logs/.*\.(md|json)$"; then
    git push origin main || true
fi
EOF
chmod +x .git/hooks/post-commit
```

---

### STEP 12: Create Auto-Push Hook in Slot B
**On droplet**, copy and paste this entire block:
```bash
cd /root/trading-bot-B
cat > .git/hooks/post-commit << 'EOF'
#!/bin/bash
cd /root/trading-bot-B
if git diff --cached --name-only | grep -E "\.(md|json)$|reports/|logs/.*\.(md|json)$"; then
    git push origin main || true
fi
EOF
chmod +x .git/hooks/post-commit
```

---

### STEP 13: Create File Watcher Script
**On droplet**, copy and paste this entire block:
```bash
mkdir -p /root/trading-bot-B/tools
cat > /root/trading-bot-B/tools/droplet_auto_sync.sh << 'EOF'
#!/bin/bash
ACTIVE_SLOT=$(readlink -f /root/trading-bot-current 2>/dev/null || echo "/root/trading-bot-B")
cd "$ACTIVE_SLOT" || exit 1

while true; do
    sleep 300
    if git status --porcelain | grep -E "reports/|logs/.*\.(md|json)$"; then
        git add reports/*.md reports/*.json 2>/dev/null
        git add logs/performance_summary_report.* logs/EXTERNAL_REVIEW_SUMMARY.md logs/GOLDEN_HOUR_ANALYSIS.* 2>/dev/null
        if ! git diff --cached --quiet; then
            git commit -m "Auto-commit: Generated reports [$(date +%Y-%m-%d\ %H:%M:%S)]" || true
            git push origin main || true
        fi
    fi
done
EOF
chmod +x /root/trading-bot-B/tools/droplet_auto_sync.sh
```

---

### STEP 14: Create Systemd Service
**On droplet**, copy and paste this entire block:
```bash
cat > /etc/systemd/system/droplet-git-sync.service << 'EOF'
[Unit]
Description=Auto-sync droplet generated files to git
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/trading-bot-B
ExecStart=/root/trading-bot-B/tools/droplet_auto_sync.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

---

### STEP 15: Start the Service
**On droplet**, run these commands one at a time:
```bash
systemctl daemon-reload
systemctl enable droplet-git-sync
systemctl start droplet-git-sync
systemctl status droplet-git-sync
```

**Should see:** "active (running)" in green

---

### STEP 16: Disconnect from Droplet
**On droplet**:
```bash
exit
```

---

### STEP 17: Test From Your Computer
**On your computer**, test everything:
```bash
python3 tools/droplet_client.py status
python3 tools/droplet_client.py pull
```

**Both should work without errors.**

---

## ✅ DONE!

Now:
- Git works in both slots
- Reports auto-commit and push
- Cursor can see everything
- Works with whichever slot is active

---

## 🛠️ IF SOMETHING DOESN'T WORK

### Can't Connect (Step 1 fails)

**Try this:**
```bash
ssh kraken
```

**If that works but the Python script doesn't:**
- You might need SSH keys set up
- Or the script needs the password

**Quick fix - set up SSH keys:**
```bash
# On your computer
ssh-keygen -t ed25519
# Press Enter 3 times
ssh-copy-id root@159.65.168.230
# Enter password when asked
```

---

### Git Push Fails (Steps 9 or 10 fail)

**Check:**
1. Token is correct (no extra spaces)
2. Token has "repo" permission
3. Try the token in browser: `https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git`

**Fix:**
```bash
# Get new token, then:
cd /root/trading-bot-A  # or B
git remote set-url origin https://mlevitan96:NEW_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
```

---

### Service Not Running (Step 15 fails)

**Check logs:**
```bash
journalctl -u droplet-git-sync -n 50
```

**Restart:**
```bash
systemctl restart droplet-git-sync
systemctl status droplet-git-sync
```

---

## 📞 NEED HELP?

Tell me:
1. Which step you're on
2. What command you ran
3. What error you see

And I'll help you fix it!



