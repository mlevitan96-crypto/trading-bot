# Droplet Quick Reference
## Quick commands for Cursor to interact with droplet

### Basic Commands

```bash
# Git status
python3 tools/droplet_client.py status

# Pull latest
python3 tools/droplet_client.py pull

# View logs (last 50 lines)
python3 tools/droplet_client.py tail --file bot_out.log --lines 50

# Service status
python3 tools/droplet_client.py service-status

# Restart service
python3 tools/droplet_client.py restart

# Read file
python3 tools/droplet_client.py read --file logs/positions_futures.json

# Run script
python3 tools/droplet_client.py run --script analyze_today_performance.py
```

### Quick Commands (Simpler Interface)

```bash
# Status
python3 tools/droplet_quick_commands.py status

# Pull
python3 tools/droplet_quick_commands.py pull

# Logs (last 50 lines)
python3 tools/droplet_quick_commands.py logs

# Logs (last 100 lines)
python3 tools/droplet_quick_commands.py logs 100

# Service status
python3 tools/droplet_quick_commands.py service

# Restart
python3 tools/droplet_quick_commands.py restart

# Positions
python3 tools/droplet_quick_commands.py positions

# Run script
python3 tools/droplet_quick_commands.py run analyze_today_performance.py
```

### Natural Language Examples for Cursor

- "Check git status on droplet" → `python3 tools/droplet_client.py status`
- "Pull latest from droplet" → `python3 tools/droplet_client.py pull`
- "Show me bot logs from droplet" → `python3 tools/droplet_client.py tail --file bot_out.log`
- "What's the service status?" → `python3 tools/droplet_client.py service-status`
- "Restart the bot on droplet" → `python3 tools/droplet_client.py restart`
- "Read positions file from droplet" → `python3 tools/droplet_client.py read --file logs/positions_futures.json`
- "Run performance analysis on droplet" → `python3 tools/droplet_client.py run --script analyze_today_performance.py`

### Setup (One-Time)

1. **On droplet**, configure git:
   ```bash
   ssh kraken
   cd /root/trading-bot-B
   # Follow DROPLET_GIT_SYNC_SETUP.md
   ```

2. **Test connection locally**:
   ```bash
   python3 tools/droplet_client.py status
   ```

### See Also

- `DROPLET_GIT_SYNC_SETUP.md` - Complete setup guide
- `CURSOR_DROPLET_INTEGRATION.md` - Full integration guide
- `tools/droplet_client.py` - Full client implementation



