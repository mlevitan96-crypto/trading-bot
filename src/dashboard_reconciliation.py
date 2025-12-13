"""
Dashboard Reconciliation & Auto-Repair System
Automatically fixes data integrity issues detected by health monitor.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

LOGS = Path("logs")


class DashboardReconciliation:
    """
    Automated reconciliation and repair for dashboard data.
    """
    
    def __init__(self):
        self.fixes_applied = []
        self.errors = []
        
    def reconcile_all(self) -> Dict[str, Any]:
        """
        Run all reconciliation checks and apply fixes.
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "fixes_applied": [],
            "errors": [],
            "status": "SUCCESS"
        }
        
        # 1. Clean up stale futures positions
        stale_fix = self._cleanup_stale_futures_positions()
        if stale_fix:
            report["fixes_applied"].append(stale_fix)
        
        # 2. Remove orphaned position files
        orphan_fix = self._cleanup_orphaned_positions()
        if orphan_fix:
            report["fixes_applied"].append(orphan_fix)
        
        # 3. Verify portfolio consistency
        portfolio_fix = self._verify_portfolio_consistency()
        if portfolio_fix:
            report["fixes_applied"].append(portfolio_fix)
        
        # Aggregate errors
        report["errors"] = self.errors
        if self.errors:
            report["status"] = "PARTIAL"
        
        self._save_reconciliation_report(report)
        
        return report
    
    def _cleanup_stale_futures_positions(self) -> Dict[str, Any]:
        """
        Close genuinely stale futures positions based on age.
        Only closes positions that are:
        1. Older than 7 days (definitely abandoned)
        2. OR older than 48 hours AND missing critical data (current_price)
        
        NEVER closes fresh positions (< 1 hour) even if unrealized_pnl == 0.
        """
        try:
            from dateutil import parser
            
            positions_file = LOGS / "positions_futures.json"
            if not positions_file.exists():
                return None
            
            with open(positions_file, 'r') as f:
                positions = json.load(f)
            
            open_positions = positions.get("open_positions", [])
            closed_positions = positions.get("closed_positions", [])
            
            if not open_positions:
                return None
            
            # Find genuinely stale positions using age-based heuristics
            now = datetime.now()
            stale_positions = []
            cleaned_open = []
            
            for pos in open_positions:
                is_stale = False
                stale_reason = None
                
                try:
                    # Parse opened_at timestamp
                    opened_at_str = pos.get("opened_at")
                    if opened_at_str:
                        opened_at = parser.isoparse(opened_at_str)
                        # Make timezone-naive for comparison
                        if opened_at.tzinfo:
                            opened_at = opened_at.replace(tzinfo=None)
                        
                        age_hours = (now - opened_at).total_seconds() / 3600
                        
                        # Stale criteria (age-based, not P&L-based):
                        if age_hours > 168:  # 7 days
                            is_stale = True
                            stale_reason = f"7+ days old ({age_hours/24:.1f}d)"
                        elif age_hours > 48 and pos.get("current_price") is None:
                            is_stale = True
                            stale_reason = f"48+ hours old ({age_hours:.1f}h) with no price data"
                        
                        # Safety: NEVER close positions < 1 hour old
                        if age_hours < 1:
                            is_stale = False
                            
                    else:
                        # No timestamp = suspicious, but don't auto-close
                        is_stale = False
                        
                except Exception:
                    # Parse error = don't auto-close
                    is_stale = False
                
                if is_stale:
                    # Mark as closed
                    pos["exit_price"] = pos.get("entry_price", 0)
                    pos["closed_at"] = now.isoformat()
                    pos["close_reason"] = f"auto_cleanup_{stale_reason}"
                    pos["funding_fees"] = 0.0
                    pos["price_roi"] = 0.0
                    pos["leveraged_roi"] = 0.0
                    pos["final_roi"] = 0.0
                    closed_positions.append(pos)
                    stale_positions.append(f"{pos.get('symbol', 'UNKNOWN')} ({stale_reason})")
                else:
                    cleaned_open.append(pos)
            
            if stale_positions:
                # Update file
                positions["open_positions"] = cleaned_open
                positions["closed_positions"] = closed_positions
                
                with open(positions_file, 'w') as f:
                    json.dump(positions, f, indent=2)
                
                return {
                    "type": "cleanup_stale_positions",
                    "count": len(stale_positions),
                    "symbols": stale_positions,
                    "message": f"Closed {len(stale_positions)} genuinely stale positions (age-based criteria)"
                }
            
            return None
            
        except Exception as e:
            self.errors.append(f"Failed to cleanup stale positions: {e}")
            return None
    
    def _cleanup_orphaned_positions(self) -> Dict[str, Any]:
        """Remove old orphaned position files."""
        try:
            import time
            
            orphaned = []
            for file in LOGS.glob("position_*.json"):
                # Skip main position files
                if file.name in ["positions_futures.json", "positions.json"]:
                    continue
                
                file_age_days = (time.time() - os.path.getmtime(file)) / 86400
                if file_age_days > 7:
                    orphaned.append(str(file))
                    file.unlink()  # Delete file
            
            if orphaned:
                return {
                    "type": "cleanup_orphaned_files",
                    "count": len(orphaned),
                    "files": [f.split('/')[-1] for f in orphaned],
                    "message": f"Deleted {len(orphaned)} orphaned position files"
                }
            
            return None
            
        except Exception as e:
            self.errors.append(f"Failed to cleanup orphaned files: {e}")
            return None
    
    def _verify_portfolio_consistency(self) -> Dict[str, Any]:
        """Verify portfolio.json data consistency."""
        try:
            portfolio_file = LOGS / "portfolio.json"
            if not portfolio_file.exists():
                return None
            
            with open(portfolio_file, 'r') as f:
                portfolio = json.load(f)
            
            # Check for negative values
            issues_fixed = []
            
            if portfolio.get("current_value", 0) < 0:
                issues_fixed.append("Negative wallet balance detected")
            
            if portfolio.get("available_balance", 0) < 0:
                issues_fixed.append("Negative available balance detected")
            
            # Check for unreasonable values
            if portfolio.get("current_value", 0) > 100000:
                issues_fixed.append("Unreasonably high wallet balance")
            
            if issues_fixed:
                return {
                    "type": "portfolio_consistency",
                    "issues": issues_fixed,
                    "message": f"Found {len(issues_fixed)} portfolio consistency issues"
                }
            
            return None
            
        except Exception as e:
            self.errors.append(f"Failed to verify portfolio: {e}")
            return None
    
    def _save_reconciliation_report(self, report: Dict[str, Any]):
        """Save reconciliation report."""
        try:
            report_file = LOGS / "dashboard_reconciliation.json"
            
            # Load existing reports
            if report_file.exists():
                with open(report_file, 'r') as f:
                    history = json.load(f)
            else:
                history = {"reports": []}
            
            # Add new report
            history["reports"].append(report)
            
            # Keep only last 50 reports
            history["reports"] = history["reports"][-50:]
            
            # Save
            with open(report_file, 'w') as f:
                json.dump(history, f, indent=2)
                
        except Exception as e:
            print(f"⚠️ Failed to save reconciliation report: {e}")
    
    def print_report(self, report: Dict[str, Any]):
        """Print reconciliation report."""
        print("\n" + "="*60)
        print("🔧 DASHBOARD RECONCILIATION REPORT")
        print("="*60)
        print(f"Status: {report['status']}")
        print(f"Timestamp: {report['timestamp']}")
        print()
        
        if not report['fixes_applied']:
            print("✅ No issues found - Dashboard is healthy")
        else:
            print(f"🔧 Applied {len(report['fixes_applied'])} fix(es):")
            for fix in report['fixes_applied']:
                print(f"\n   {fix['type'].upper()}:")
                print(f"   - {fix['message']}")
                if fix.get('count'):
                    print(f"   - Count: {fix['count']}")
                if fix.get('symbols'):
                    print(f"   - Symbols: {', '.join(fix['symbols'])}")
        
        if report['errors']:
            print(f"\n❌ {len(report['errors'])} error(s) occurred:")
            for error in report['errors']:
                print(f"   - {error}")
        
        print("="*60)


def run_reconciliation():
    """Run dashboard reconciliation and return report."""
    reconciler = DashboardReconciliation()
    report = reconciler.reconcile_all()
    reconciler.print_report(report)
    return report


if __name__ == "__main__":
    run_reconciliation()
