#!/usr/bin/env python3
"""
Droplet Client - Enables Cursor to interact with the droplet via SSH
This removes the copy/paste middleman and allows natural language interaction.
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Optional, Dict, List, Any
import sys

# Droplet configuration
DROPLET_IP = "159.65.168.230"
DROPLET_USER = "root"
DROPLET_PATH_DEFAULT = "/root/trading-bot-current"  # Use symlink to active slot
DROPLET_PATH_A = "/root/trading-bot-A"
DROPLET_PATH_B = "/root/trading-bot-B"
SSH_KEY_PATH = os.path.expanduser("~/.ssh/id_rsa")  # Adjust if using different key


class DropletClient:
    """Client for executing commands on the droplet via SSH"""
    
    def __init__(self, ip: str = DROPLET_IP, user: str = DROPLET_USER, 
                 key_path: Optional[str] = None, path: Optional[str] = None, 
                 auto_detect: bool = True):
        self.ip = ip
        self.user = user
        self.key_path = key_path or SSH_KEY_PATH
        # Default to current (active slot), but allow override
        if path:
            self.base_path = path
        elif auto_detect:
            # Try to detect active slot, fallback to default
            try:
                self.base_path = self._detect_active_slot()
            except:
                self.base_path = DROPLET_PATH_DEFAULT
        else:
            self.base_path = DROPLET_PATH_DEFAULT
        
    def _detect_active_slot(self) -> str:
        """Detect which slot is currently active"""
        # Use a fixed path to avoid recursion
        ssh_cmd = self._build_ssh_command("readlink -f /root/trading-bot-current")
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                resolved = result.stdout.strip()
                if "trading-bot-A" in resolved:
                    return "/root/trading-bot-A"
                elif "trading-bot-B" in resolved:
                    return "/root/trading-bot-B"
        except:
            pass
        # Fallback: try to detect from systemd service
        ssh_cmd = self._build_ssh_command("systemctl show tradingbot -p WorkingDirectory --value")
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass
        return DROPLET_PATH_DEFAULT
    
    def use_active_slot(self):
        """Switch to the currently active slot"""
        self.base_path = self._detect_active_slot()
        
    def _build_ssh_command(self, command: str) -> List[str]:
        """Build SSH command with optional key"""
        ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
        
        if os.path.exists(self.key_path):
            ssh_cmd.extend(["-i", self.key_path])
        
        ssh_cmd.append(f"{self.user}@{self.ip}")
        ssh_cmd.append(command)
        return ssh_cmd
    
    def execute(self, command: str, cwd: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a command on the droplet
        
        Args:
            command: Command to execute
            cwd: Working directory (defaults to DROPLET_PATH)
            
        Returns:
            Dict with 'success', 'stdout', 'stderr', 'returncode'
        """
        if cwd:
            full_command = f"cd {cwd} && {command}"
        else:
            full_command = f"cd {self.base_path} && {command}"
        
        ssh_cmd = self._build_ssh_command(full_command)
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "command": command
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command timed out after 60 seconds",
                "returncode": -1,
                "command": command
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "command": command
            }
    
    def git_status(self) -> Dict[str, Any]:
        """Get git status from droplet"""
        return self.execute("git status")
    
    def git_pull(self) -> Dict[str, Any]:
        """Pull latest changes from GitHub"""
        return self.execute("git pull origin main")
    
    def git_log(self, n: int = 10) -> Dict[str, Any]:
        """Get recent git log"""
        return self.execute(f"git log --oneline -n {n}")
    
    def get_file(self, remote_path: str, local_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Copy a file from droplet to local machine
        
        Args:
            remote_path: Path on droplet (relative to DROPLET_PATH or absolute)
            local_path: Local destination path (defaults to same filename in current dir)
        """
        if not remote_path.startswith("/"):
            remote_path = f"{self.base_path}/{remote_path}"
        
        if not local_path:
            local_path = os.path.basename(remote_path)
        
        scp_cmd = ["scp", "-o", "StrictHostKeyChecking=no"]
        if os.path.exists(self.key_path):
            scp_cmd.extend(["-i", self.key_path])
        
        scp_cmd.append(f"{self.user}@{self.ip}:{remote_path}")
        scp_cmd.append(local_path)
        
        try:
            result = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=30)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "local_path": local_path
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "local_path": local_path
            }
    
    def read_file(self, remote_path: str) -> Dict[str, Any]:
        """Read file content from droplet"""
        if not remote_path.startswith("/"):
            remote_path = f"{self.base_path}/{remote_path}"
        
        return self.execute(f"cat {remote_path}")
    
    def list_files(self, remote_path: str = ".") -> Dict[str, Any]:
        """List files in a directory on droplet"""
        if not remote_path.startswith("/"):
            remote_path = f"{self.base_path}/{remote_path}"
        
        return self.execute(f"ls -lah {remote_path}")
    
    def tail_log(self, log_file: str, lines: int = 50) -> Dict[str, Any]:
        """Tail a log file on droplet"""
        if not log_file.startswith("/"):
            log_file = f"{self.base_path}/logs/{log_file}"
        
        return self.execute(f"tail -n {lines} {log_file}")
    
    def check_service_status(self, service: str = "tradingbot") -> Dict[str, Any]:
        """Check systemd service status"""
        return self.execute(f"systemctl status {service}")
    
    def restart_service(self, service: str = "tradingbot") -> Dict[str, Any]:
        """Restart a systemd service"""
        return self.execute(f"systemctl restart {service}")
    
    def run_script(self, script_path: str, *args) -> Dict[str, Any]:
        """Run a Python script on the droplet"""
        if not script_path.startswith("/"):
            script_path = f"{self.base_path}/{script_path}"
        
        cmd = f"cd {self.base_path} && source venv/bin/activate && python3 {script_path}"
        if args:
            cmd += " " + " ".join(args)
        
        return self.execute(cmd)


def main():
    """CLI interface for droplet client"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Interact with trading bot droplet")
    parser.add_argument("command", choices=[
        "status", "pull", "log", "read", "list", "tail", 
        "service-status", "restart", "run", "execute"
    ])
    parser.add_argument("--file", help="File path for read/list/tail commands")
    parser.add_argument("--lines", type=int, default=50, help="Number of lines for tail")
    parser.add_argument("--service", default="tradingbot", help="Service name")
    parser.add_argument("--script", help="Script path for run command")
    parser.add_argument("--args", nargs="*", help="Arguments for script")
    parser.add_argument("--custom", help="Custom command to execute")
    
    args = parser.parse_args()
    
    # Auto-detect active slot by default
    client = DropletClient(auto_detect=True)
    
    if args.command == "status":
        result = client.git_status()
    elif args.command == "pull":
        result = client.git_pull()
    elif args.command == "log":
        result = client.git_log()
    elif args.command == "read":
        if not args.file:
            print("Error: --file required for read command")
            sys.exit(1)
        result = client.read_file(args.file)
    elif args.command == "list":
        result = client.list_files(args.file or ".")
    elif args.command == "tail":
        if not args.file:
            print("Error: --file required for tail command")
            sys.exit(1)
        result = client.tail_log(args.file, args.lines)
    elif args.command == "service-status":
        result = client.check_service_status(args.service)
    elif args.command == "restart":
        result = client.restart_service(args.service)
    elif args.command == "run":
        if not args.script:
            print("Error: --script required for run command")
            sys.exit(1)
        result = client.run_script(args.script, *(args.args or []))
    elif args.command == "execute":
        if not args.custom:
            print("Error: --custom required for execute command")
            sys.exit(1)
        result = client.execute(args.custom)
    
    # Print result
    if result["success"]:
        print(result["stdout"])
        if result["stderr"]:
            print("STDERR:", result["stderr"], file=sys.stderr)
        sys.exit(0)
    else:
        print("ERROR:", result["stderr"], file=sys.stderr)
        sys.exit(result["returncode"])


if __name__ == "__main__":
    main()

