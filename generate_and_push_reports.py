#!/usr/bin/env python3
"""
Generate Reports and Push to GitHub
===================================
Automated workflow to generate analysis reports and push them to GitHub
for easy download and AI analysis.
"""

import subprocess
import sys
import os
import json
from pathlib import Path

# Import the report generators
try:
    from generate_performance_summary import generate_summary_report
except ImportError:
    print("ERROR: generate_performance_summary.py not found")
    sys.exit(1)


def git_push_files(files_to_push, commit_message):
    """Push specified files to GitHub."""
    try:
        # Add files
        for file in files_to_push:
            if os.path.exists(file):
                subprocess.run(["git", "add", file], check=True)
                print(f"✅ Added {file}")
            else:
                print(f"⚠️  File not found: {file}")
        
        # Commit (may fail if nothing to commit - that's ok)
        commit_result = subprocess.run(
            ["git", "commit", "-m", commit_message],
            capture_output=True,
            text=True
        )
        
        if commit_result.returncode == 0:
            print(f"✅ Committed: {commit_message}")
        elif "nothing to commit" in commit_result.stdout or "nothing to commit" in commit_result.stderr:
            print(f"ℹ️  No changes to commit (files already up to date)")
            # Check if we still need to push
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True
            )
            if not status_result.stdout.strip():
                print("ℹ️  Everything already pushed to GitHub")
                return True  # Success - nothing to do
        else:
            print(f"⚠️  Commit warning: {commit_result.stderr}")
        
        # Check if there's anything to push
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True
        )
        
        if not status_result.stdout.strip():
            # Check if we're ahead of remote
            ahead_result = subprocess.run(
                ["git", "rev-list", "--count", "HEAD...origin/main"],
                capture_output=True,
                text=True
            )
            if ahead_result.returncode == 0 and ahead_result.stdout.strip() == "0":
                print("ℹ️  Everything already up to date on GitHub")
                return True
        
        # Push
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Pushed to GitHub successfully")
            return True
        elif "Everything up-to-date" in result.stdout or "Everything up-to-date" in result.stderr:
            print("✅ Everything already up to date on GitHub")
            return True
        else:
            print(f"⚠️  Git push output: {result.stdout}")
            print(f"⚠️  Git push errors: {result.stderr}")
            print("⚠️  Push failed - you may need to authenticate")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Git error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


def main():
    """Generate reports and push to GitHub."""
    print("=" * 80)
    print("GENERATE REPORTS AND PUSH TO GITHUB")
    print("=" * 80)
    print()
    
    # Generate performance summary
    print("Generating performance summary report...")
    try:
        reports = generate_summary_report()
        if not reports:
            print("❌ Failed to generate report")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error generating report: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Generate golden hour analysis
    print("Generating golden hour analysis...")
    try:
        from analyze_golden_hour_trades import analyze_golden_hour_trades, generate_report
        analysis = analyze_golden_hour_trades()
        if analysis:
            report = generate_report(analysis)
            Path("GOLDEN_HOUR_ANALYSIS.md").write_text(report)
            Path("GOLDEN_HOUR_ANALYSIS.json").write_text(
                json.dumps(analysis, indent=2, default=str)
            )
            print("✅ Golden hour analysis complete")
        else:
            print("⚠️  Golden hour analysis returned no data")
    except ImportError:
        print("⚠️  analyze_golden_hour_trades.py not found, skipping golden hour analysis")
    except Exception as e:
        print(f"⚠️  Error generating golden hour analysis: {e}")
        import traceback
        traceback.print_exc()
    
    # Files to push
    files_to_push = [
        "performance_summary_report.json",
        "performance_summary_report.md",
        "EXTERNAL_REVIEW_SUMMARY.md"
    ]
    
    # Add golden hour files if they exist
    if os.path.exists("GOLDEN_HOUR_ANALYSIS.md"):
        files_to_push.append("GOLDEN_HOUR_ANALYSIS.md")
    if os.path.exists("GOLDEN_HOUR_ANALYSIS.json"):
        files_to_push.append("GOLDEN_HOUR_ANALYSIS.json")
    
    # Check which files exist
    existing_files = [f for f in files_to_push if os.path.exists(f)]
    
    if not existing_files:
        print("❌ No report files found to push")
        sys.exit(1)
    
    print()
    print(f"Files ready to push: {len(existing_files)}")
    for f in existing_files:
        size = os.path.getsize(f)
        print(f"  - {f} ({size:,} bytes)")
    
    print()
    commit_message = f"Add generated performance reports - {Path('performance_summary_report.json').stat().st_mtime if os.path.exists('performance_summary_report.json') else 'auto'}"
    
    # Push to GitHub
    print("Pushing to GitHub...")
    success = git_push_files(existing_files, commit_message)
    
    print()
    print("=" * 80)
    if success:
        print("✅ SUCCESS: Reports pushed to GitHub")
        print("   You can now download from GitHub or have AI analyze directly")
    else:
        print("⚠️  Reports generated but push failed")
        print("   Files are ready locally, push manually with:")
        print("   git add *.md *.json")
        print("   git commit -m 'Add reports'")
        print("   git push origin main")
    print("=" * 80)


if __name__ == "__main__":
    main()

