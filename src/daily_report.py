import json
import datetime
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_tracker import load_portfolio
from missed_opportunity_tracker import get_missed_opportunities_stats
from performance_tracker import calculate_sharpe_ratio, calculate_sortino_ratio


def generate_daily_report():
    """
    Generate a comprehensive daily performance report.
    
    Metrics included:
        - Total trades executed
        - Win rate percentage
        - Average ROI per trade
        - Blocked signals count
        - Sharpe ratio
        - Sortino ratio
        - Portfolio value
        - Total profit/loss
    
    Output:
        Saves report to logs/daily_report.json
    """
    portfolio = load_portfolio()
    
    try:
        missed = get_missed_opportunities_stats()
    except Exception as e:
        print(f"⚠️  Could not load missed opportunities: {e}")
        missed = {}
    
    trades = portfolio.get('trades', [])
    
    rois = [t['roi'] for t in trades if 'roi' in t]
    
    if rois:
        sharpe = calculate_sharpe_ratio(rois, 0.0)
        sortino = calculate_sortino_ratio(rois, 0.0)
        win_rate = sum(1 for r in rois if r > 0) / len(rois)
        avg_roi = sum(rois) / len(rois)
    else:
        sharpe = 0.0
        sortino = 0.0
        win_rate = 0.0
        avg_roi = 0.0
    
    report = {
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'total_trades': len(trades),
        'win_rate': round(win_rate * 100, 2),
        'avg_roi': round(avg_roi * 100, 4),
        'blocked_signals': missed.get('total_missed', 0),
        'sharpe': round(sharpe, 3),
        'sortino': round(sortino, 3),
        'portfolio_value': portfolio.get('portfolio_value', 10000.0),
        'total_profit': portfolio.get('total_profit', 0.0),
        'max_drawdown': portfolio.get('max_drawdown', 0.0),
        'peak_value': portfolio.get('peak_value', 10000.0)
    }
    
    Path('logs').mkdir(exist_ok=True)
    
    with open('logs/daily_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"📊 Daily report generated: Win Rate={report['win_rate']}%, Sharpe={report['sharpe']}, Trades={report['total_trades']}")
    
    return report


def get_latest_daily_report():
    """
    Load the most recent daily report.
    
    Returns:
        dict: Daily report data or empty dict if not found
    """
    report_path = Path('logs/daily_report.json')
    
    if not report_path.exists():
        return {}
    
    try:
        with open(report_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load daily report: {e}")
        return {}
