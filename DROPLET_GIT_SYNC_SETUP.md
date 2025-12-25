# Droplet Git Sync Setup Guide
## Enable Cursor to See Everything on Droplet

This guide sets up automatic git syncing between your droplet and GitHub, allowing Cursor to see all changes that happen on the droplet without manual copy/paste.

---

## 🎯 Goal

- **Remove copy/paste middleman**: Cursor can directly access droplet changes
- **Automatic syncing**: Changes on droplet automatically appear in GitHub
- **Natural language interface**: Use Cursor to interact with droplet via natural language

---

## 📋 Prerequisites

1. **SSH access to droplet** (already configured)
2. **Git credentials on droplet** (see `setup_droplet_git_push.sh`)
3. **GitHub Personal Access Token** (for pushing from droplet)

---

## 🚀 Setup Steps

### Step 1: Configure Git on Droplet (One-Time)

SSH into your droplet and run:

```bash
ssh root@159.65.168.230
cd /root/trading-bot-B

# Configure git (if not already done)
git config --global user.name "Mark Levitan"
git config --global user.email "mlevitan96@gmail.com"

# Set up remote with token (replace YOUR_TOKEN)
git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git

# Or use SSH (recommended if you have SSH key set up)
# git remote set-url origin git@github.com:mlevitan96-crypto/trading-bot.git

# Test push capability
git push origin main --dry-run
```

### Step 2: Install Git Hooks for Auto-Push

On the droplet, set up a post-commit hook:

```bash
cd /root/trading-bot-B

# Create post-commit hook
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

### Step 3: Set Up File Watcher (Optional but Recommended)

Create a systemd service to watch for generated files and auto-commit:

```bash
# On droplet, create the watcher script
cat > /root/trading-bot-B/tools/droplet_auto_sync.sh << 'EOF'
#!/bin/bash
# Auto-sync generated reports to git

DROPLET_PATH="/root/trading-bot-B"
cd "$DROPLET_PATH" || exit 1

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

# Create systemd service
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

# Enable and start
systemctl daemon-reload
systemctl enable droplet-git-sync
systemctl start droplet-git-sync
systemctl status droplet-git-sync
```

### Step 4: Test Local Droplet Client

On your local machine, test the droplet client:

```bash
# Make sure droplet_client.py is executable
chmod +x tools/droplet_client.py

# Test connection
python3 tools/droplet_client.py status

# Test pulling latest
python3 tools/droplet_client.py pull

# Test reading a file
python3 tools/droplet_client.py read --file logs/positions_futures.json

# Test tailing logs
python3 tools/droplet_client.py tail --file bot_out.log --lines 20
```

---

## 💬 Using Cursor with Droplet

Now you can use natural language with Cursor to interact with the droplet:

### Example Commands:

**"Check the git status on the droplet"**
```bash
python3 tools/droplet_client.py status
```

**"Pull the latest changes from droplet"**
```bash
python3 tools/droplet_client.py pull
```

**"Show me the last 50 lines of bot_out.log from droplet"**
```bash
python3 tools/droplet_client.py tail --file bot_out.log --lines 50
```

**"What's the service status on droplet?"**
```bash
python3 tools/droplet_client.py service-status
```

**"Run the performance analysis script on droplet"**
```bash
python3 tools/droplet_client.py run --script analyze_today_performance.py
```

**"Read the positions file from droplet"**
```bash
python3 tools/droplet_client.py read --file logs/positions_futures.json
```

---

## 🔄 Workflow Examples

### Example 1: Generate Reports and Auto-Sync

1. **On droplet**, run:
   ```bash
   cd /root/trading-bot-B
   source venv/bin/activate
   python3 generate_and_push_reports.py
   ```

2. **The file watcher automatically**:
   - Detects new/changed report files
   - Commits them to git
   - Pushes to GitHub

3. **In Cursor**, you can now:
   - Pull the latest changes: `python3 tools/droplet_client.py pull`
   - Read the reports directly from the repo
   - Analyze the data without copy/paste

### Example 2: Check Droplet Status via Cursor

Just ask Cursor:
- "What's the git status on droplet?"
- "Show me recent logs from droplet"
- "Is the trading bot service running on droplet?"

Cursor can run the appropriate `droplet_client.py` commands.

### Example 3: Deploy Changes

1. **Make changes locally** in Cursor
2. **Commit and push to GitHub**:
   ```bash
   git add .
   git commit -m "Your changes"
   git push origin main
   ```

3. **Pull on droplet** (via Cursor):
   ```bash
   python3 tools/droplet_client.py pull
   ```

4. **Restart service** (via Cursor):
   ```bash
   python3 tools/droplet_client.py restart
   ```

---

## 📁 Files That Auto-Sync

The following files are automatically committed and pushed:

- `reports/*.md` and `reports/*.json`
- `logs/performance_summary_report.*`
- `logs/EXTERNAL_REVIEW_SUMMARY.md`
- `logs/GOLDEN_HOUR_ANALYSIS.*`
- Any other `.md` or `.json` files in tracked directories

**Note**: Code changes should still follow the standard workflow: local → GitHub → droplet.

---

## 🛠️ Troubleshooting

### Droplet Client Can't Connect

1. **Check SSH access**:
   ```bash
   ssh root@159.65.168.230
   ```

2. **Check SSH key**:
   ```bash
   ls -la ~/.ssh/id_rsa
   ```

3. **Test SSH manually**:
   ```bash
   ssh -i ~/.ssh/id_rsa root@159.65.168.230 "echo 'Connection works'"
   ```

### Git Push Fails on Droplet

1. **Check git credentials**:
   ```bash
   ssh root@159.65.168.230
   cd /root/trading-bot-B
   git remote -v
   ```

2. **Test push manually**:
   ```bash
   git push origin main
   ```

3. **If using token, verify it's in the URL**:
   ```bash
   git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
   ```

### File Watcher Not Working

1. **Check service status**:
   ```bash
   systemctl status droplet-git-sync
   ```

2. **Check logs**:
   ```bash
   journalctl -u droplet-git-sync -f
   ```

3. **Restart service**:
   ```bash
   systemctl restart droplet-git-sync
   ```

---

## ✅ Verification Checklist

- [ ] Git configured on droplet with credentials
- [ ] Post-commit hook installed and executable
- [ ] File watcher service running (optional)
- [ ] Local `droplet_client.py` can connect
- [ ] Test commit/push works on droplet
- [ ] Cursor can pull changes from GitHub

---

## 🎉 Benefits

✅ **No more copy/paste**: Cursor sees all droplet changes automatically  
✅ **Natural language**: Ask Cursor to interact with droplet  
✅ **Automatic syncing**: Generated reports appear in GitHub automatically  
✅ **Full visibility**: Cursor can read logs, check status, run scripts  
✅ **Streamlined workflow**: Deploy and monitor from Cursor  

---

## 📚 Related Files

- `tools/droplet_client.py` - Python client for droplet interaction
- `setup_droplet_git_push.sh` - Initial git setup script
- `DROPLET_INTERACTION_GUIDE.md` - Manual droplet interaction guide
- `DROPLET_GIT_WORKFLOW.md` - Git workflow documentation

---

**Next Steps**: Run the setup commands above, then test with `python3 tools/droplet_client.py status`



