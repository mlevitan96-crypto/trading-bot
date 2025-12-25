# Droplet Git Setup - Complete Step-by-Step Guide
## Fix Everything and Make It Work

This guide will help you set up everything step-by-step, troubleshoot issues, and make it work with all directories (A, B, and current).

---

## 🔍 FIRST: Check What's Currently Working

**Step 1:** Test if you can connect to the droplet from your computer:

```bash
python3 tools/droplet_client.py status
```

**What you should see:**
- If it works: You'll see git status from the droplet
- If it fails: You'll see an error message

**If it fails**, the connection isn't set up. Skip to "Fix Connection Issues" below.

**If it works**, continue to Step 2.

---

## 📋 COMPLETE SETUP STEPS

### Part 1: Connect to Your Droplet

**Step 2:** Open your terminal (PowerShell on Windows)

**Step 3:** Connect to your droplet:
```bash
ssh kraken
```

**What you should see:**
- A password prompt, OR
- You're immediately connected (if SSH key is set up)

**If you see a password prompt:**
- Enter your droplet password
- You should see: `root@your-droplet:~#`

**If connection fails:**
- Check your internet connection
- Verify the IP address is correct: `159.65.168.230`
- You may need to set up SSH keys (see troubleshooting below)

---

### Part 2: Check Which Directories Exist

**Step 4:** Once connected, check what directories you have:
```bash
ls -la /root/ | grep trading-bot
```

**What you should see:**
- `trading-bot-A` (Slot A)
- `trading-bot-B` (Slot B)  
- `trading-bot-current` (Symlink to active slot)

**Step 5:** Check which slot is currently active:
```bash
readlink -f /root/trading-bot-current
```

**What you should see:**
- Either `/root/trading-bot-A` or `/root/trading-bot-B`

**Write down which one is active** - you'll need this later.

---

### Part 3: Set Up Git on ALL Directories

You need to set up git in BOTH slots (A and B) so it works no matter which one is active.

**Step 6:** Set up Git in Slot A:
```bash
cd /root/trading-bot-A
git config user.name "Mark Levitan"
git config user.email "mlevitan96@gmail.com"
```

**Step 7:** Set up Git in Slot B:
```bash
cd /root/trading-bot-B
git config user.name "Mark Levitan"
git config user.email "mlevitan96@gmail.com"
```

**Step 8:** Get your GitHub Personal Access Token:
1. Go to: https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Name it: "Droplet Access"
4. Check the box for **"repo"** (this gives full repository access)
5. Click "Generate token" at the bottom
6. **COPY THE TOKEN** - it starts with `ghp_` and you won't see it again!

**Step 9:** Set up Git remote in Slot A (replace `YOUR_TOKEN` with the token you copied):
```bash
cd /root/trading-bot-A
git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
```

**Step 10:** Set up Git remote in Slot B (same token):
```bash
cd /root/trading-bot-B
git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
```

**Step 11:** Test that pushing works in Slot A:
```bash
cd /root/trading-bot-A
git push origin main --dry-run
```

**What you should see:**
- "Everything up-to-date" or similar (no errors)

**Step 12:** Test that pushing works in Slot B:
```bash
cd /root/trading-bot-B
git push origin main --dry-run
```

**What you should see:**
- "Everything up-to-date" or similar (no errors)

**If you see errors:**
- Double-check the token (no extra spaces)
- Make sure the token has "repo" permissions
- Try the token in a browser first: `https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git`

---

### Part 4: Set Up Auto-Push Hooks in BOTH Slots

**Step 13:** Create auto-push hook in Slot A:
```bash
cd /root/trading-bot-A
cat > .git/hooks/post-commit << 'EOF'
#!/bin/bash
cd /root/trading-bot-A
# Auto-push after commit (only for generated reports)
if git diff --cached --name-only | grep -E "\.(md|json)$|reports/|logs/.*\.(md|json)$"; then
    git push origin main || true
fi
EOF
chmod +x .git/hooks/post-commit
```

**Step 14:** Create auto-push hook in Slot B:
```bash
cd /root/trading-bot-B
cat > .git/hooks/post-commit << 'EOF'
#!/bin/bash
cd /root/trading-bot-B
# Auto-push after commit (only for generated reports)
if git diff --cached --name-only | grep -E "\.(md|json)$|reports/|logs/.*\.(md|json)$"; then
    git push origin main || true
fi
EOF
chmod +x .git/hooks/post-commit
```

---

### Part 5: Set Up File Watcher (Works for Both Slots)

**Step 15:** Create the watcher script (this works for whichever slot is active):
```bash
mkdir -p /root/trading-bot-B/tools
cat > /root/trading-bot-B/tools/droplet_auto_sync.sh << 'EOF'
#!/bin/bash
# Auto-sync generated reports to git - works with active slot

# Detect active slot
ACTIVE_SLOT=$(readlink -f /root/trading-bot-current 2>/dev/null || echo "/root/trading-bot-B")
cd "$ACTIVE_SLOT" || exit 1

while true; do
    sleep 300  # Check every 5 minutes
    
    # Check for new/changed report files
    if git status --porcelain | grep -E "reports/|logs/.*\.(md|json)$"; then
        # Add report files
        git add reports/*.md reports/*.json 2>/dev/null
        git add logs/performance_summary_report.* logs/EXTERNAL_REVIEW_SUMMARY.md logs/GOLDEN_HOUR_ANALYSIS.* 2>/dev/null
        
        # Commit and push if there are changes
        if ! git diff --cached --quiet; then
            git commit -m "Auto-commit: Generated reports [$(date +%Y-%m-%d\ %H:%M:%S)]" || true
            git push origin main || true
        fi
    fi
done
EOF
chmod +x /root/trading-bot-B/tools/droplet_auto_sync.sh
```

**Step 16:** Create systemd service to run the watcher:
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

**Step 17:** Start the watcher service:
```bash
systemctl daemon-reload
systemctl enable droplet-git-sync
systemctl start droplet-git-sync
systemctl status droplet-git-sync
```

**What you should see:**
- "active (running)" in green

**If it's not running:**
- Check logs: `journalctl -u droplet-git-sync -n 50`
- Look for error messages

**Step 18:** Disconnect from droplet:
```bash
exit
```

---

### Part 6: Test From Your Computer

**Step 19:** Test connection from your computer:
```bash
python3 tools/droplet_client.py status
```

**What you should see:**
- Git status from the droplet (showing which slot is active)

**Step 20:** Test pulling:
```bash
python3 tools/droplet_client.py pull
```

**What you should see:**
- "Already up to date" or similar

---

## 🛠️ TROUBLESHOOTING

### Issue 1: Can't Connect to Droplet

**Symptom:** `python3 tools/droplet_client.py status` fails with connection error

**Fix:**

1. **Test SSH manually:**
   ```bash
   ssh kraken
   ```

2. **If SSH asks for password:**
   - That's fine, but you'll need to enter it each time
   - Better: Set up SSH keys (see below)

3. **Set up SSH keys (optional but recommended):**
   ```bash
   # On your computer, generate SSH key if you don't have one
   ssh-keygen -t ed25519 -C "your-email@example.com"
   # Press Enter to accept default location
   # Press Enter twice for no passphrase (or set one)
   
   # Copy key to droplet (use actual IP for ssh-copy-id)
   ssh-copy-id root@159.65.168.230
   # Enter password when prompted
   
   # Test connection (should not ask for password)
   ssh kraken
   ```

### Issue 2: Git Push Fails

**Symptom:** `git push origin main` fails with authentication error

**Fix:**

1. **Check if token is correct:**
   ```bash
   # On droplet
   cd /root/trading-bot-B
   git remote -v
   # Should show your token in the URL
   ```

2. **If token is missing or wrong:**
   ```bash
   # Get new token from GitHub
   # Then update remote:
   git remote set-url origin https://mlevitan96:YOUR_NEW_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
   ```

3. **Test push:**
   ```bash
   git push origin main --dry-run
   ```

### Issue 3: File Watcher Not Working

**Symptom:** Generated reports aren't being auto-committed

**Fix:**

1. **Check if service is running:**
   ```bash
   ssh kraken
   systemctl status droplet-git-sync
   ```

2. **If not running, check logs:**
   ```bash
   journalctl -u droplet-git-sync -n 50
   ```

3. **Restart service:**
   ```bash
   systemctl restart droplet-git-sync
   systemctl status droplet-git-sync
   ```

4. **Test manually:**
   ```bash
   cd /root/trading-bot-B  # or current active slot
   # Create a test file
   echo "test" > reports/test.md
   # Wait 5 minutes, then check:
   git log --oneline -1
   # Should see auto-commit
   ```

### Issue 4: Client Points to Wrong Directory

**Symptom:** Commands work but on wrong slot

**Fix:**

The client now automatically detects the active slot. But you can also specify:

```bash
# Use specific slot
python3 -c "from tools.droplet_client import DropletClient; c = DropletClient(path='/root/trading-bot-A'); print(c.git_status()['stdout'])"
```

Or update the default in `tools/droplet_client.py` line 17.

---

## ✅ VERIFICATION CHECKLIST

After setup, verify everything works:

- [ ] Can connect to droplet: `python3 tools/droplet_client.py status`
- [ ] Git configured in Slot A: `cd /root/trading-bot-A && git config user.name`
- [ ] Git configured in Slot B: `cd /root/trading-bot-B && git config user.name`
- [ ] Can push from Slot A: `cd /root/trading-bot-A && git push origin main --dry-run`
- [ ] Can push from Slot B: `cd /root/trading-bot-B && git push origin main --dry-run`
- [ ] Post-commit hook exists in Slot A: `ls -la /root/trading-bot-A/.git/hooks/post-commit`
- [ ] Post-commit hook exists in Slot B: `ls -la /root/trading-bot-B/.git/hooks/post-commit`
- [ ] File watcher service running: `systemctl status droplet-git-sync`
- [ ] Can pull from computer: `python3 tools/droplet_client.py pull`

---

## 🎯 WHAT THIS SETUP DOES

1. **Git works in both slots** - No matter which slot is active, git is configured
2. **Auto-push hooks** - When you commit reports, they automatically push to GitHub
3. **File watcher** - Every 5 minutes, checks for new reports and auto-commits them
4. **Cursor can see everything** - All changes appear in GitHub automatically
5. **Works with active slot** - Automatically uses whichever slot is currently active

---

## 📞 NEXT STEPS

Once everything is set up:

1. **Test it:**
   - Generate a report on droplet
   - Wait 5 minutes
   - Check GitHub - the report should be there automatically

2. **Use with Cursor:**
   - Ask Cursor: "Check git status on droplet"
   - Ask Cursor: "Show me bot logs from droplet"
   - Cursor can now interact with droplet directly!

---

**If you get stuck at any step, tell me which step and what error you see, and I'll help you fix it!**



