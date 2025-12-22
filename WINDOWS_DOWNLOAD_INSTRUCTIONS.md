# How to Download Files from Your Server (Windows)

## Your Server Details:
- **Server IP:** 174.22.247.105
- **Username:** root
- **Files Location:** `/root/trading-bot-B/feature_store/`

---

## Method 1: Using SCP (Command Line) - Complete Command

Open PowerShell or Command Prompt and run this **complete command on one line**:

```powershell
scp root@174.22.247.105:/root/trading-bot-B/feature_store/signal_analysis_export.csv .
scp root@174.22.247.105:/root/trading-bot-B/feature_store/signal_analysis_summary.json .
```

**Important:** 
- The command must be on **one line** (not split)
- The `.` at the end means "current directory" (wherever you ran the command)
- You'll be prompted for your password

**If you get "command not found":**
- Windows 10/11 should have `scp` built-in
- If not, install OpenSSH: Settings → Apps → Optional Features → Add OpenSSH Client

---

## Method 2: Using WinSCP (Easiest - GUI Tool)

1. **Download WinSCP:** https://winscp.net/eng/download.php
2. **Install and open WinSCP**
3. **Connect:**
   - Host name: `174.22.247.105`
   - Username: `root`
   - Password: (your server password)
   - Click "Login"
4. **Navigate to:** `/root/trading-bot-B/feature_store/`
5. **Download files:**
   - Right-click `signal_analysis_export.csv` → Download
   - Right-click `signal_analysis_summary.json` → Download

---

## Method 3: Using VS Code Remote Extension

If you use VS Code:

1. **Install "Remote - SSH" extension**
2. **Connect to server:**
   - Press `F1` → Type "Remote-SSH: Connect to Host"
   - Enter: `root@174.22.247.105`
3. **Open folder:** `/root/trading-bot-B/feature_store/`
4. **Right-click files → Download**

---

## Method 4: Using FileZilla (SFTP Client)

1. **Download FileZilla:** https://filezilla-project.org/download.php?type=client
2. **Connect:**
   - Host: `sftp://174.22.247.105`
   - Username: `root`
   - Password: (your server password)
   - Port: `22`
3. **Navigate to:** `/root/trading-bot-B/feature_store/`
4. **Drag files to your local computer**

---

## Method 5: Copy Files to Web-Accessible Location (Then Download via Browser)

**On your server, run:**
```bash
# Copy files to a web directory (if you have one)
cp /root/trading-bot-B/feature_store/signal_analysis_export.csv /var/www/html/
cp /root/trading-bot-B/feature_store/signal_analysis_summary.json /var/www/html/
```

**Then download from browser:**
- `http://174.22.247.105/signal_analysis_export.csv`
- `http://174.22.247.105/signal_analysis_summary.json`

---

## Method 6: Email the Files (If Mail is Configured)

**On your server:**
```bash
echo "Trading bot analysis export" | mailx -s "Analysis Export" -a /root/trading-bot-B/feature_store/signal_analysis_export.csv -a /root/trading-bot-B/feature_store/signal_analysis_summary.json your-email@example.com
```

---

## Quick Test: Verify Files Exist on Server

**SSH into your server and run:**
```bash
ls -lh /root/trading-bot-B/feature_store/signal_analysis_export.csv
ls -lh /root/trading-bot-B/feature_store/signal_analysis_summary.json
```

This will show you the file sizes and confirm they exist.

---

## Recommended: Use WinSCP (Method 2)

**WinSCP is the easiest for Windows users** - it's like Windows Explorer but for remote servers. Just drag and drop files.

---

## Troubleshooting SCP on Windows

**If SCP asks for a password and you don't have one:**
- You might need to use an SSH key file
- Command with key: `scp -i C:\path\to\your\key.pem root@174.22.247.105:/root/trading-bot-B/feature_store/signal_analysis_export.csv .`

**If you get "Permission denied":**
- Make sure you're using the correct password
- Or set up SSH key authentication

**If files don't exist:**
- SSH into server: `ssh root@174.22.247.105`
- Run: `python3 export_signal_analysis.py`
- Then try downloading again
