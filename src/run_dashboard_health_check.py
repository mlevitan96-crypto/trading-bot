"""
Scheduled dashboard health check runner.
Can be run manually or integrated into bot cycle.
"""

import sys
sys.path.insert(0, 'src')

from dashboard_health_monitor import run_health_check
from dashboard_reconciliation import run_reconciliation


def main():
    """Run health check and reconciliation."""
    print("\n" + "="*70)
    print("🏥 DASHBOARD HEALTH & RECONCILIATION SERVICE")
    print("="*70 + "\n")
    
    # Step 1: Run health check
    print("Step 1: Running health diagnostics...")
    health_report = run_health_check()
    
    print("\n")
    
    # Step 2: Run reconciliation if issues found
    if health_report['overall_status'] != "HEALTHY":
        print("Step 2: Running automated reconciliation...")
        reconcile_report = run_reconciliation()
        
        # Step 3: Re-run health check to verify fixes
        print("\nStep 3: Re-running health check to verify fixes...")
        final_report = run_health_check()
        
        if final_report['overall_status'] == "HEALTHY":
            print("\n✅ All issues resolved successfully!")
        else:
            print("\n⚠️  Some issues remain after reconciliation")
    else:
        print("✅ Dashboard is healthy - No reconciliation needed\n")
    
    print("="*70)


if __name__ == "__main__":
    main()
