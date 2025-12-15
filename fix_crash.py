import sys
import os

file_path = "/root/trading-bot/src/run.py"

print(f"🔧 meaningful repairing {file_path}...")

try:
    with open(file_path, "r") as f:
        lines = f.readlines()

    new_lines = []
    is_deleting = False
    
    for line in lines:
        # Detect the start of the bad code block I gave you
        if "💰 PNL FIX" in line or "run_pnl_updater" in line:
            is_deleting = True
            
        # Detect the end of the bad block (where the crash is happening)
        if "✅ All systems initialized" in line:
            is_deleting = False
            
        # Keep the line if we are not in the "delete zone"
        # AND verify we aren't keeping the threading line which might hang around
        if not is_deleting and "PnL_Sidecar" not in line:
            new_lines.append(line)

    # Write the clean file back
    with open(file_path, "w") as f:
        f.writelines(new_lines)
        
    print("✅ Repair complete. Bad indentation block removed.")

except Exception as e:
    print(f"❌ Failed to fix file: {e}")
