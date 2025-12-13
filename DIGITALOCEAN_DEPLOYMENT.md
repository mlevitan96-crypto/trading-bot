# Digital Ocean Deployment Guide

## Prerequisites
- Python 3.11+
- Digital Ocean Droplet (Ubuntu 22.04 recommended)
- Minimum 2GB RAM, 1 CPU

## Quick Setup

### 1. Upload Files
Upload the `migration_package/` folder to your droplet:
```bash
scp -r migration_package/ root@your-droplet-ip:/opt/trading-bot/
```

### 2. Install Dependencies
```bash
cd /opt/trading-bot
apt update && apt install -y python3.11 python3.11-venv python3-pip
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
nano .env  # Edit with your API credentials
```

### 4. Load Environment Variables
Add to your `.bashrc` or create a systemd service:
```bash
export $(cat .env | xargs)
```

### 5. Run the Bot
```bash
# Test run
python run.py

# Or use the supervisor script
chmod +x start_bot.sh
./start_bot.sh
```

## Systemd Service (Recommended)

Create `/etc/systemd/system/trading-bot.service`:
```ini
[Unit]
Description=Crypto Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading-bot
EnvironmentFile=/opt/trading-bot/.env
ExecStart=/opt/trading-bot/venv/bin/python /opt/trading-bot/run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
systemctl daemon-reload
systemctl enable trading-bot
systemctl start trading-bot
```

## Dashboard Access
The P&L dashboard runs on port 5000. Configure nginx or expose port 5000:
```bash
ufw allow 5000
```
Access at: `http://your-droplet-ip:5000`

## Monitoring
```bash
# View logs
journalctl -u trading-bot -f

# Check status
systemctl status trading-bot
```

## File Structure
```
/opt/trading-bot/
├── run.py              # Main entry point
├── start_bot.sh        # Supervisor script
├── requirements.txt    # Python dependencies
├── live_config.json    # Runtime configuration
├── .env                # API credentials (create from .env.example)
├── src/                # Core source code
├── config/             # Static configuration
├── configs/            # Runtime configs
├── data/               # SQLite database
├── logs/               # Trading state & logs
└── feature_store/      # ML features
```

## Important Notes
1. **Paper Trading**: Bot starts in paper trading mode by default
2. **Database**: SQLite database is in `data/trading_system.db`
3. **Positions**: Open positions tracked in `logs/positions_futures.json`
4. **Backups**: Recommend daily backup of `data/` and `logs/` directories
