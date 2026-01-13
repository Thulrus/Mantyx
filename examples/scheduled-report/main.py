#!/usr/bin/env python3
"""
Example Scheduled Mantyx Application - Daily Report

This app generates a simple report. It's designed to be run on a schedule.
"""

import sys
from datetime import datetime
from pathlib import Path


def generate_report():
    """Generate a simple daily report."""
    timestamp = datetime.now()
    
    print("=" * 50)
    print(f"Daily Report - {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()
    
    # Example: Check a directory
    reports_dir = Path("/tmp/mantyx_reports")
    reports_dir.mkdir(exist_ok=True)
    
    print(f"Reports directory: {reports_dir}")
    print(f"Exists: {reports_dir.exists()}")
    
    # Create a report file
    report_file = reports_dir / f"report_{timestamp.strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w') as f:
        f.write(f"Report generated at: {timestamp}\n")
        f.write(f"Status: OK\n")
        f.write(f"Items processed: 42\n")
    
    print(f"Report saved to: {report_file}")
    print()
    print("Report generation complete!")
    print("=" * 50)


def main():
    """Main entry point."""
    print("Starting report generation...")
    
    try:
        generate_report()
        sys.exit(0)
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
