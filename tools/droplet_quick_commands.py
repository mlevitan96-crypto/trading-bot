#!/usr/bin/env python3
"""
Quick command shortcuts for common droplet operations
Use this for natural language interactions with Cursor
"""

import sys
from pathlib import Path

# Add parent directory to path to import droplet_client
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.droplet_client import DropletClient

def print_result(result, show_command=False):
    """Print command result in a readable format"""
    if show_command:
        print(f"Command: {result.get('command', 'N/A')}")
        print("-" * 60)
    
    if result["success"]:
        if result["stdout"]:
            print(result["stdout"])
        if result["stderr"]:
            print(f"Note: {result['stderr']}", file=sys.stderr)
    else:
        print(f"❌ Error: {result['stderr']}", file=sys.stderr)
        sys.exit(1)

def main():
    """Quick command interface"""
    if len(sys.argv) < 2:
        print("Usage: python3 droplet_quick_commands.py <command> [args...]")
        print("\nCommands:")
        print("  status          - Git status on droplet")
        print("  pull            - Pull latest from GitHub")
        print("  logs [N]        - Show last N lines of bot_out.log (default 50)")
        print("  service         - Check tradingbot service status")
        print("  restart         - Restart tradingbot service")
        print("  positions       - Read positions file")
        print("  run <script>    - Run a Python script on droplet")
        sys.exit(1)
    
    client = DropletClient()
    command = sys.argv[1].lower()
    
    if command == "status":
        result = client.git_status()
        print_result(result)
    
    elif command == "pull":
        result = client.git_pull()
        print_result(result)
    
    elif command == "logs":
        lines = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        result = client.tail_log("bot_out.log", lines)
        print_result(result)
    
    elif command == "service":
        result = client.check_service_status()
        print_result(result)
    
    elif command == "restart":
        result = client.restart_service()
        print_result(result)
    
    elif command == "positions":
        result = client.read_file("logs/positions_futures.json")
        print_result(result)
    
    elif command == "run":
        if len(sys.argv) < 3:
            print("Error: Script name required")
            print("Usage: python3 droplet_quick_commands.py run <script.py>")
            sys.exit(1)
        script = sys.argv[2]
        args = sys.argv[3:] if len(sys.argv) > 3 else []
        result = client.run_script(script, *args)
        print_result(result)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()



