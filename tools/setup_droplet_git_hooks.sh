#!/bin/bash
# Setup git hooks on droplet to auto-commit and push changes
# This allows Cursor to see all changes that happen on the droplet

echo "Setting up git hooks on droplet for automatic syncing..."
echo ""

# Configuration
DROPLET_IP="159.65.168.230"
DROPLET_USER="root"
DROPLET_PATH="/root/trading-bot-B"

# Files to auto-commit (generated reports, logs that should be tracked)
AUTO_COMMIT_PATTERNS=(
    "*.md"
    "*.json"
    "reports/*"
    "logs/performance_summary_report.*"
    "logs/EXTERNAL_REVIEW_SUMMARY.md"
    "logs/GOLDEN_HOUR_ANALYSIS.*"
)

echo "This script will set up git hooks on the droplet to automatically:"
echo "  1. Commit changes to generated reports and analysis files"
echo "  2. Push changes to GitHub"
echo "  3. Keep Cursor in sync with droplet activity"
echo ""
echo "⚠️  Note: This will auto-commit files matching:"
for pattern in "${AUTO_COMMIT_PATTERNS[@]}"; do
    echo "  - $pattern"
done
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Create post-commit hook script
cat > /tmp/droplet_git_hooks.sh << 'HOOK_SCRIPT'
#!/bin/bash
# Auto-commit and push hook for droplet

DROPLET_PATH="/root/trading-bot-B"
cd "$DROPLET_PATH" || exit 1

# Patterns to auto-commit
PATTERNS=(
    "*.md"
    "*.json"
    "reports/*"
    "logs/performance_summary_report.*"
    "logs/EXTERNAL_REVIEW_SUMMARY.md"
    "logs/GOLDEN_HOUR_ANALYSIS.*"
)

# Check if there are any changes matching our patterns
HAS_CHANGES=false
for pattern in "${PATTERNS[@]}"; do
    if git ls-files --others --exclude-standard | grep -q "$pattern" || \
       ! git diff --quiet -- "$pattern" 2>/dev/null; then
        HAS_CHANGES=true
        break
    fi
done

if [ "$HAS_CHANGES" = true ]; then
    # Add matching files
    for pattern in "${PATTERNS[@]}"; do
        git add "$pattern" 2>/dev/null
    done
    
    # Commit if there are staged changes
    if ! git diff --cached --quiet; then
        git commit -m "Auto-commit: Generated reports and analysis files [$(date +%Y-%m-%d\ %H:%M:%S)]" || true
        git push origin main || true
    fi
fi
HOOK_SCRIPT

# Create file watcher script
cat > /tmp/droplet_file_watcher.sh << 'WATCHER_SCRIPT'
#!/bin/bash
# File watcher that auto-commits changes to generated files

DROPLET_PATH="/root/trading-bot-B"
cd "$DROPLET_PATH" || exit 1

# Watch for changes and auto-commit
while true; do
    sleep 300  # Check every 5 minutes
    
    # Check for new/changed report files
    if git status --porcelain | grep -E "\.(md|json)$|reports/|logs/.*\.(md|json)$"; then
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
WATCHER_SCRIPT

echo ""
echo "📋 Next steps:"
echo ""
echo "1. SSH into your droplet:"
echo "   ssh $DROPLET_USER@$DROPLET_IP"
echo ""
echo "2. Run these commands on the droplet:"
echo ""
echo "   cd $DROPLET_PATH"
echo ""
echo "   # Install git hooks"
echo "   mkdir -p .git/hooks"
echo "   cat > .git/hooks/post-commit << 'EOF'"
echo "   #!/bin/bash"
echo "   cd $DROPLET_PATH"
echo "   # Auto-push after commit"
echo "   git push origin main || true"
echo "   EOF"
echo "   chmod +x .git/hooks/post-commit"
echo ""
echo "   # Optional: Set up file watcher as a systemd service"
echo "   # (See DROPLET_GIT_SYNC_SETUP.md for full instructions)"
echo ""
echo "3. Test the setup:"
echo "   python3 tools/droplet_client.py status"
echo ""
echo "✅ Setup instructions saved. See DROPLET_GIT_SYNC_SETUP.md for complete guide."





