"""
Comprehensive codebase export for external review.
Exports entire trading bot system as structured JSON.
"""

import json
import os
import datetime
from pathlib import Path


def read_file_safe(filepath):
    """Safely read a file, return content or error message."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"[Error reading file: {str(e)}]"


def export_complete_codebase():
    """
    Export entire trading bot codebase and state.
    Returns comprehensive JSON structure.
    """
    
    export_data = {
        "export_metadata": {
            "timestamp": datetime.datetime.now().isoformat(),
            "export_type": "Complete Trading Bot Codebase",
            "version": "Phase 7.1 - Predictive Stability",
            "description": "Comprehensive export for external review"
        },
        
        "source_code": {},
        "configuration": {},
        "documentation": {},
        "system_state": {},
        "logs_sample": {}
    }
    
    # Source code files
    source_files = [
        "src/phase71_predictive_stability.py",
        "src/phase7_predictive_intelligence.py",
        "src/phase6_alpha_engine.py",
        "src/phase5_reliability.py",
        "src/phase4_watchdog.py",
        "src/phase3_edge_compounding.py",
        "src/phase2_capital_protection.py",
        "src/shadow_research.py",
        "src/dashboard_app.py",
        "src/health_check.py",
        "src/export_codebase.py",
        "run.py",
        "trading_bot/bot.py",
        "trading_bot/regime_detector.py",
        "trading_bot/risk_manager.py",
        "trading_bot/position_sizer.py",
        "trading_bot/adaptive_learning.py",
        "trading_bot/exchange_gateway.py",
        "trading_bot/portfolio_tracker.py",
        "trading_bot/elite_system.py",
        "trading_bot/strategy.py",
        "trading_bot/advanced_risk.py",
        "trading_bot/futures_manager.py",
        "trading_bot/data_fetcher.py"
    ]
    
    for filepath in source_files:
        if os.path.exists(filepath):
            export_data["source_code"][filepath] = read_file_safe(filepath)
    
    # Configuration files
    config_files = [
        "config/pair_overrides.json",
        "config/leverage_defaults.json",
        "config/futures_policy.json",
        "config/ladder_exit_policy.json",
        "config/promoter_learning_config.json",
        "config/shadow_xrp.json",
        "config/shadow_ada.json",
        "config/shadow_doge.json",
        "config/shadow_bnb.json",
        "config/shadow_matic.json"
    ]
    
    for filepath in config_files:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    export_data["configuration"][filepath] = json.load(f)
            except:
                export_data["configuration"][filepath] = read_file_safe(filepath)
    
    # Documentation
    doc_files = [
        "replit.md",
        "README.md"
    ]
    
    for filepath in doc_files:
        if os.path.exists(filepath):
            export_data["documentation"][filepath] = read_file_safe(filepath)
    
    # System state snapshots
    try:
        from src.phase71_predictive_stability import get_phase71
        p71 = get_phase71()
        export_data["system_state"]["phase71"] = p71.get_status()
    except Exception as e:
        export_data["system_state"]["phase71"] = {"error": str(e)}
    
    try:
        from src.phase7_predictive_intelligence import get_phase7
        p7 = get_phase7()
        export_data["system_state"]["phase7"] = p7.get_status()
    except Exception as e:
        export_data["system_state"]["phase7"] = {"error": str(e)}
    
    try:
        from src.phase6_alpha_engine import get_phase6
        p6 = get_phase6()
        export_data["system_state"]["phase6"] = p6.get_status()
    except Exception as e:
        export_data["system_state"]["phase6"] = {"error": str(e)}
    
    try:
        from src.shadow_research import get_shadow_research
        shadow = get_shadow_research()
        export_data["system_state"]["shadow_research"] = shadow.get_status()
    except Exception as e:
        export_data["system_state"]["shadow_research"] = {"error": str(e)}
    
    try:
        from src.health_check import run_health_check
        export_data["system_state"]["health_check"] = run_health_check()
    except Exception as e:
        export_data["system_state"]["health_check"] = {"error": str(e)}
    
    # Recent logs sample (last 100 lines from key log files)
    log_files = [
        "logs/portfolio_log.csv",
        "logs/position_log.csv",
        "logs/trade_log.csv"
    ]
    
    for filepath in log_files:
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    lines = f.readlines()
                    export_data["logs_sample"][filepath] = {
                        "total_lines": len(lines),
                        "last_100_lines": lines[-100:] if len(lines) > 100 else lines
                    }
            except Exception as e:
                export_data["logs_sample"][filepath] = {"error": str(e)}
    
    # File structure overview
    export_data["file_structure"] = {
        "directories": [],
        "total_files": 0
    }
    
    for root, dirs, files in os.walk('.'):
        if not any(skip in root for skip in ['.git', '__pycache__', 'node_modules', '.cache']):
            export_data["file_structure"]["directories"].append({
                "path": root,
                "files": files,
                "subdirs": dirs
            })
            export_data["file_structure"]["total_files"] += len(files)
    
    return export_data


def export_to_json_file(output_path=None):
    """Export codebase to JSON file."""
    data = export_complete_codebase()
    
    if output_path is None:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"trading_bot_export_{timestamp}.json"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return output_path


if __name__ == "__main__":
    output_file = export_to_json_file()
    print(f"✅ Codebase exported to: {output_file}")
