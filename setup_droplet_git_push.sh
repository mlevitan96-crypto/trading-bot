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
echo ""
echo "⚠️  IMPORTANT: When pushing, use:"
echo "   Username: mlevitan96 (NOT your email!)"
echo "   Password: (paste your GitHub Personal Access Token)"
echo ""
echo "GitHub no longer accepts passwords - you MUST use a token as the password."
echo ""
echo "EASIER OPTION: Use token in URL (no prompts):"
echo "  git remote set-url origin https://mlevitan96:YOUR_TOKEN@github.com/mlevitan96-crypto/trading-bot.git"
echo "  (Replace YOUR_TOKEN with your actual token)"
echo ""
echo "To cache credentials for future pushes (optional):"
echo "  git config --global credential.helper store"
echo "  (then do one push with username/token, it will be saved)"
echo ""
echo "Done! You can now push from droplet."

