#!/usr/bin/env python3
"""
Generate Dry Run Analytics Reports

Usage:
    python generate_report.py              # Full weekly report
    python generate_report.py daily        # Today's summary
    python generate_report.py whale 0x123  # Specific whale report
    python generate_report.py market       # Market breakdown
    python generate_report.py timing       # Timing analysis
    python generate_report.py confidence   # Confidence calibration
    python generate_report.py execution    # Execution quality
"""

import sys
from dry_run_analytics import DryRunAnalytics


def main():
    analytics = DryRunAnalytics()

    if len(sys.argv) < 2:
        # Full report
        print(analytics.get_weekly_report())
        return

    cmd = sys.argv[1].lower()

    if cmd == 'daily':
        print(analytics.get_daily_summary())

    elif cmd == 'whale':
        if len(sys.argv) < 3:
            # List all whales
            print("\nTracked Whales:")
            print("="*60)
            for addr in analytics.data['whale_stats'].keys():
                stats = analytics.data['whale_stats'][addr]
                total = stats['wins'] + stats['losses']
                if total > 0:
                    wr = stats['wins'] / total * 100
                    print(f"{addr[:10]}...: {total} trades, {wr:.0f}% win, ${stats['total_profit']:.2f}")
        else:
            # Specific whale
            whale_addr = sys.argv[2]
            # Find matching whale
            for addr in analytics.data['whale_stats'].keys():
                if whale_addr.lower() in addr.lower():
                    print(analytics.get_whale_report(addr))
                    break
            else:
                print(f"Whale {whale_addr} not found")

    elif cmd == 'market':
        print(analytics.get_market_report())

    elif cmd == 'timing':
        print(analytics.get_timing_report())

    elif cmd == 'confidence':
        print(analytics.get_confidence_calibration_report())

    elif cmd == 'execution':
        print(analytics.get_execution_report())

    elif cmd == 'help':
        print(__doc__)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
