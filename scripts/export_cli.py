"""
File Overview: CLI Script to export multi-day research Excel files on demand.

Usage:
  python scripts/export_cli.py --symbol IREDA --start 2026-08-01 --end 2026-08-11
  python scripts/export_cli.py --symbol NIFTY --start 2026-08-01 --end 2026-08-14 --output nifty_august_research.xlsx
"""

import os
import sys
import argparse
from datetime import datetime

# Add project root directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from domains.analytics.application.historical_research_exporter import generate_research_excel_workbook


def main():
    parser = argparse.ArgumentParser(description="AlphaStreams Multi-Day Historical Research Excel Exporter")
    parser.add_argument("--symbol", "-s", required=True, help="Ticker symbol (e.g. NIFTY, IREDA, RELIANCE)")
    parser.add_argument("--start", "-st", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", "-et", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--layout", "-l", choices=["separate_tabs", "combined_per_day"], default="separate_tabs", help="Excel layout mode")
    parser.add_argument("--output", "-o", help="Output file path (optional)")

    args = parser.parse_args()

    try:
        dt_start = datetime.strptime(args.start, "%Y-%m-%d").date()
        dt_end = datetime.strptime(args.end, "%Y-%m-%d").date()
    except ValueError:
        print("Error: Dates must be in YYYY-MM-DD format (e.g. 2026-08-01).")
        sys.exit(1)

    if dt_start > dt_end:
        print("Error: Start date must be before or equal to End date.")
        sys.exit(1)

    print(f"[*] Generating Research Excel export for {args.symbol.upper()} from {dt_start} to {dt_end}...")

    excel_bytes = generate_research_excel_workbook(
        symbol=args.symbol,
        start_date=dt_start,
        end_date=dt_end,
        layout_mode=args.layout
    )

    out_filename = args.output
    if not out_filename:
        out_filename = f"AlphaStreams_{args.symbol.upper()}_{dt_start.strftime('%Y%m%d')}_to_{dt_end.strftime('%Y%m%d')}.xlsx"

    out_dir = os.path.dirname(os.path.abspath(out_filename))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(out_filename, "wb") as f:
        f.write(excel_bytes)

    print(f"[OK] Export successful! File saved to: {os.path.abspath(out_filename)}")


if __name__ == "__main__":
    main()
