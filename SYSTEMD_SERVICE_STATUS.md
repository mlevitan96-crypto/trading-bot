# Systemd Service Status

## ✅ Service is Running

**Service Name**: `tradingbot.service` (not `trading-bot.service`)

### Current Status

- **Status**: ✅ Active (running)
- **Enabled**: ✅ Yes (will start on boot)
- **Started**: Running since Dec 26 16:49:56 UTC
- **Main PID**: 649137
- **Memory Usage**: 2.2GB
- **Worker Processes**: 6 processes (main + 5 workers)

### Service Configuration

**Service File**: `/etc/systemd/system/tradingbot.service`

```ini
[Unit]
Description=Crypto Trading Bot
After=network.target

[Service]
EnvironmentFile=/root/trading-bot-current/.env
Type=simple
User=root
WorkingDirectory=/root/trading-bot-current
ExecStart=/root/trading-bot-current/venv/bin/python3 /root/trading-bot-current/run.py
Restart=always
RestartSec=5
Environment="COINGLASS_API_KEY=6128970c03fe4b72976ceece9a445088"

[Install]
WantedBy=multi-user.target
```

### Key Points

1. **Service is active and running** ✅
2. **Auto-restart enabled** (Restart=always, RestartSec=5)
3. **Running from**: `/root/trading-bot-current` (symlink to active slot)
4. **Environment loaded from**: `/root/trading-bot-current/.env`
5. **CoinGlass API key configured** in service environment

### Management Commands

```bash
# Check status
systemctl status tradingbot

# View logs
journalctl -u tradingbot -f
journalctl -u tradingbot -n 100

# Restart service
systemctl restart tradingbot

# Stop service
systemctl stop tradingbot

# Start service
systemctl start tradingbot

# Enable/disable auto-start on boot
systemctl enable tradingbot
systemctl disable tradingbot
```

### Worker Processes

The bot runs multiple worker processes:
- Main process (PID 649137)
- 5 worker processes (PIDs 649145, 649146, 649147, 649148, 649175)

All processes are managed by systemd under the `tradingbot.service` unit.

---

**Last Checked**: $(date)
**Status**: ✅ **SERVICE IS RUNNING AND MANAGED BY SYSTEMD**

