# Fix Git Authentication Issue

## The Problem

You entered `mlevitan96@gmail.com` as the username, but GitHub requires your **GitHub username** (`mlevitan96-crypto`), not your email.

## The Solution

When prompted for credentials:
- **Username:** `mlevitan96-crypto` (NOT the email)
- **Password:** (paste your GitHub Personal Access Token)

## Quick Fix: Use URL with Token (Easier)

Instead of entering credentials each time, embed the token in the URL:

```bash
cd /root/trading-bot-B

# Set remote URL with token embedded
git remote set-url origin https://mlevitan96-crypto:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git
# Replace YOUR_TOKEN with your actual GitHub Personal Access Token

# Now push (won't ask for credentials)
git push origin main
```

**Note:** The token in the URL will be saved in git config, so future pushes won't ask for credentials.

## Alternative: Use SSH (More Secure)

If you prefer SSH keys instead of tokens:

```bash
# Generate SSH key
ssh-keygen -t ed25519 -C "mlevitan96@gmail.com"
# Press Enter to accept default location
# Press Enter twice for no passphrase (or set one)

# Copy public key
cat ~/.ssh/id_ed25519.pub

# Add to GitHub:
# 1. Go to https://github.com/settings/keys
# 2. Click "New SSH key"
# 3. Paste the public key

# Change remote to SSH
git remote set-url origin git@github.com:mlevitan96-crypto/trading-bot.git

# Test connection
ssh -T git@github.com

# Now push
git push origin main
```

## Current Issue

The error happened because:
1. Username was entered as email (`mlevitan96@gmail.com`) instead of GitHub username (`mlevitan96-crypto`)
2. GitHub doesn't accept passwords anymore - only Personal Access Tokens
3. The token needs to be entered as the "password" field, not the username field

