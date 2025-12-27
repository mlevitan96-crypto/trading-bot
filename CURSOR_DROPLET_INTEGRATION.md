# Cursor + Droplet Integration Guide
## Natural Language Interface for Droplet Management

This guide explains how to use Cursor as your natural language interface for interacting with your trading bot droplet, eliminating the copy/paste middleman.

---

## 🎯 What This Enables

- **Natural Language Commands**: Ask Cursor to interact with droplet in plain English
- **Automatic Syncing**: Changes on droplet automatically appear in GitHub
- **Full Visibility**: Cursor can see logs, status, files, and run scripts on droplet
- **No Manual Steps**: No more SSH, copy/paste, or manual file transfers

---

## 🚀 Quick Start

### 1. Set Up Droplet Git Sync

Follow the instructions in `DROPLET_GIT_SYNC_SETUP.md` to:
- Configure git on droplet
- Set up auto-commit hooks
- Enable file watcher for generated reports

### 2. Test Connection

```bash
# Test that you can connect to droplet
python3 tools/droplet_client.py status
```

### 3. Use Natural Language with Cursor

Now you can simply ask Cursor:

- **"Check the git status on the droplet"**
- **"Show me the last 100 lines of bot logs from droplet"**
- **"What's the service status on droplet?"**
- **"Pull the latest changes from droplet"**
- **"Run the performance analysis on droplet"**

Cursor will automatically use `tools/droplet_client.py` to execute these commands.

---

## 💬 Example Interactions

### Checking Status

**You**: "What's the git status on droplet?"

**Cursor will run**:
```bash
python3 tools/droplet_client.py status
```

### Viewing Logs

**You**: "Show me the last 50 lines of bot logs from droplet"

**Cursor will run**:
```bash
python3 tools/droplet_client.py tail --file bot_out.log --lines 50
```

### Running Analysis

**You**: "Run the today's performance analysis on droplet"

**Cursor will run**:
```bash
python3 tools/droplet_client.py run --script analyze_today_performance.py
```

### Deploying Changes

**You**: "I made changes to position_manager.py, deploy them to droplet"

**Cursor will**:
1. Commit and push to GitHub
2. Pull on droplet: `python3 tools/droplet_client.py pull`
3. Restart service: `python3 tools/droplet_client.py restart`

### Reading Files

**You**: "What are the current positions on droplet?"

**Cursor will run**:
```bash
python3 tools/droplet_client.py read --file logs/positions_futures.json
```

---

## 📋 Available Commands

The `droplet_client.py` tool supports these operations:

| Command | Description | Example |
|---------|-------------|---------|
| `status` | Git status | `python3 tools/droplet_client.py status` |
| `pull` | Pull from GitHub | `python3 tools/droplet_client.py pull` |
| `log` | Git log | `python3 tools/droplet_client.py log` |
| `read` | Read file | `python3 tools/droplet_client.py read --file path/to/file` |
| `list` | List directory | `python3 tools/droplet_client.py list --file logs/` |
| `tail` | Tail log file | `python3 tools/droplet_client.py tail --file bot_out.log --lines 50` |
| `service-status` | Check service | `python3 tools/droplet_client.py service-status` |
| `restart` | Restart service | `python3 tools/droplet_client.py restart` |
| `run` | Run script | `python3 tools/droplet_client.py run --script analyze_today_performance.py` |
| `execute` | Custom command | `python3 tools/droplet_client.py execute --custom "ls -lah"` |

---

## 🔄 Workflow Patterns

### Pattern 1: Generate Reports and Analyze

1. **Ask Cursor**: "Generate performance reports on droplet"
   - Cursor runs: `python3 tools/droplet_client.py run --script generate_and_push_reports.py`

2. **File watcher automatically** commits and pushes to GitHub

3. **Ask Cursor**: "Analyze the performance reports"
   - Cursor pulls latest: `python3 tools/droplet_client.py pull`
   - Cursor reads the reports from local repo
   - Cursor provides analysis

### Pattern 2: Debugging Issues

1. **Ask Cursor**: "The bot seems stuck, check what's happening on droplet"
   - Cursor checks service status
   - Cursor tails recent logs
   - Cursor reads position files
   - Cursor provides diagnosis

2. **Ask Cursor**: "Restart the bot on droplet"
   - Cursor runs: `python3 tools/droplet_client.py restart`

### Pattern 3: Deploy and Verify

1. **Make changes locally** in Cursor

2. **Ask Cursor**: "Deploy these changes to droplet"
   - Cursor commits and pushes to GitHub
   - Cursor pulls on droplet
   - Cursor restarts service
   - Cursor verifies deployment

---

## 🛠️ Advanced Usage

### Custom Commands

You can execute any command on the droplet:

```bash
python3 tools/droplet_client.py execute --custom "df -h"
python3 tools/droplet_client.py execute --custom "ps aux | grep python"
```

### Reading Multiple Files

Ask Cursor to read multiple files and compare:

**You**: "Compare the positions file and the performance report from droplet"

Cursor will read both files and provide comparison.

### Monitoring

**You**: "Monitor the bot logs on droplet for the next minute"

Cursor can tail logs in real-time and alert on errors.

---

## 🔧 Configuration

### SSH Key Location

By default, the client looks for SSH key at `~/.ssh/id_rsa`. To use a different key:

```python
from tools.droplet_client import DropletClient

client = DropletClient(key_path="~/.ssh/my_custom_key")
```

### Droplet IP

Default IP is `159.65.168.230`. To change:

```python
client = DropletClient(ip="YOUR_IP", user="root")
```

---

## ✅ Benefits

✅ **Natural Language**: No need to remember SSH commands  
✅ **Automatic Syncing**: Generated reports appear in GitHub automatically  
✅ **Full Context**: Cursor sees everything that happens on droplet  
✅ **Streamlined**: Deploy, monitor, and debug from Cursor  
✅ **No Manual Steps**: Eliminates copy/paste workflow  

---

## 📚 Related Documentation

- `DROPLET_GIT_SYNC_SETUP.md` - Complete setup instructions
- `tools/droplet_client.py` - Python client implementation
- `DROPLET_INTERACTION_GUIDE.md` - Manual interaction guide
- `DROPLET_GIT_WORKFLOW.md` - Git workflow details

---

## 🎉 Next Steps

1. **Complete setup** from `DROPLET_GIT_SYNC_SETUP.md`
2. **Test connection** with `python3 tools/droplet_client.py status`
3. **Start using natural language** with Cursor to interact with droplet
4. **Enjoy** the streamlined workflow!

---

**Remember**: Cursor can now be your natural language interface for all droplet operations. Just ask!





