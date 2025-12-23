#!/bin/bash
# Setup script for pushing from droplet to GitHub
# Run this once on the droplet to configure git credentials

echo "Setting up Git for pushing from droplet to GitHub..."
echo ""

# Configure git user
git config --global user.name "Mark Levitan"
git config --global user.email "mlevitan96@gmail.com"

# Set remote URL to HTTPS (using token)
git remote set-url origin https://github.com/mlevitan96-crypto/trading-bot.git

echo "✅ Git configured"
echo ""
echo "⚠️  Note: GitHub token will be stored in git credential helper"
echo "   When you push, use token as password:"
echo "   Username: mlevitan96"
echo "   Password: (paste your token)"
echo ""
echo "To cache credentials for future pushes (optional):"
echo "  git config --global credential.helper store"
echo "  (then do one push with username/token, it will be saved)"
echo ""
echo "Done! You can now push from droplet."

