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
        
        # Commit
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            check=True,
            capture_output=True
        )
        print(f"✅ Committed: {commit_message}")
        
        # Push
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Pushed to GitHub successfully")
            return True
        else:
            print(f"⚠️  Git push output: {result.stdout}")
            print(f"⚠️  Git push errors: {result.stderr}")
            print("⚠️  Push failed - you may need to authenticate")
            print("   Run: git push origin main")
            print("   Username: mlevitan96")
            print("   Password: (use your GitHub token)")
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
    
    # Files to push
    files_to_push = [
        "performance_summary_report.json",
        "performance_summary_report.md",
        "EXTERNAL_REVIEW_SUMMARY.md"
    ]
    
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

