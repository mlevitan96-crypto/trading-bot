# Droplet Git Workflow Guide

## Standard Workflow (Recommended)

**Local → GitHub → Droplet**

1. Make changes locally
2. Commit and push to GitHub
3. Pull on droplet

This ensures code is tested locally first and reviewed before deployment.

---

## Pushing from Droplet (Alternative)

For generated reports or analysis files, you CAN push from the droplet if needed.

### Option 1: SSH Key (Recommended)

**Setup (one-time):**

```bash
# On droplet, generate SSH key if you don't have one
ssh-keygen -t ed25519 -C "your-email@example.com"

# Copy public key
cat ~/.ssh/id_ed25519.pub

# Add this key to GitHub:
# 1. Go to GitHub → Settings → SSH and GPG keys
# 2. Click "New SSH key"
# 3. Paste the public key
```

**Configure Git (if not already done):**

```bash
git config --global user.name "Your Name"
git config --global user.email "your-email@example.com"

# Change remote URL to use SSH (if currently using HTTPS)
cd /root/trading-bot-B
git remote -v  # Check current remote
# If it shows https://, change to SSH:
git remote set-url origin git@github.com:mlevitan96-crypto/trading-bot.git
```

**Then you can push:**

```bash
cd /root/trading-bot-B
git add performance_summary_report.md EXTERNAL_REVIEW_SUMMARY.md
git commit -m "Add generated performance reports"
git push origin main
```

### Option 2: HTTPS with Personal Access Token

```bash
# Use GitHub Personal Access Token as password
git remote set-url origin https://github.com/mlevitan96-crypto/trading-bot.git

# When pushing, use token as password:
git push origin main
# Username: your-github-username
# Password: <your-personal-access-token>
```

---

## For Your Specific Case (Generated Reports)

Since you want to download the generated reports from GitHub:

**Option A: Push from Droplet (Quick)**
```bash
cd /root/trading-bot-B
git pull origin main  # Get latest first
python3 generate_performance_summary.py  # Generate reports
git add performance_summary_report.md performance_summary_report.json
git commit -m "Add performance summary reports for external review"
git push origin main
```

Then download from GitHub (clone or download raw files).

**Option B: Use SCP (Already Working)**
```bash
# On your local machine
scp root@159.65.168.230:/root/trading-bot-B/performance_summary_report.md .
scp root@159.65.168.230:/root/trading-bot-B/EXTERNAL_REVIEW_SUMMARY.md .
```

**Option C: Copy/Paste Content**
If the files aren't too large, you can just `cat` them on the server and copy/paste.

---

## Important Notes

1. **For code changes**: Always use local → GitHub → droplet workflow
2. **For generated reports**: Pushing from droplet is acceptable
3. **Never edit code directly on droplet** - always commit locally first
4. **Test locally** before pushing to GitHub when possible

---

## Quick Check: Can Droplet Push to GitHub?

Test if you can push:

```bash
cd /root/trading-bot-B
git status
git remote -v

# Try a test push (will fail if no credentials, but shows what's needed)
git push origin main --dry-run
```

If it fails, you'll need to set up credentials (SSH key or PAT).

