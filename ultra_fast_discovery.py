"""
Ultra-Fast Discovery System v4 (WebSocket-Primary)

Architecture:
- WebSocket captures whale trades in real-time
- Resolution loop checks pending trades after expected resolution time
- NO blockchain scanning needed
- Database for stats only

This module now just provides database access and stats.
All whale discovery happens via resolution-based tracking.
"""

import asyncio
from datetime import datetime
import json
import os

from trade_database import TradeDatabase, get_db_path


class UltraFastDiscovery:
    """
    Discovery system v4 - WebSocket primary, no blockchain scanning.

    This class now only handles:
    - Database access
    - Stats printing
    """

    def __init__(self, db_path: str = None):
        # SQLite database for persistent storage
        if db_path is None:
            db_path = get_db_path()
        self.db = TradeDatabase(db_path)

        print("⚡ DISCOVERY v4 (WebSocket-Primary)")
        print(f"   Storage: SQLite ({db_path})")
        print(f"   No blockchain scanning - WebSocket handles real-time trades")

    async def run_ultra_fast_discovery(self):
        """Main loop - just stats printing, no scanning"""

        print("\n" + "="*80)
        print("⚡ DISCOVERY v4 (WebSocket-Primary)")
        print("="*80)
        print("\nArchitecture:")
        print("  • WebSocket captures whale trades in real-time")
        print("  • Resolution loop tracks PnL after market resolution")
        print("  • No blockchain scanning needed")
        print("  • New whales discovered from profitable resolved trades\n")

        # Check existing data
        stats = self.db.get_database_stats()
        print(f"📊 Database stats:")
        print(f"   Whales in tiers: {stats['whale_count']}")
        print(f"   Pending trades: {stats['pending_trades']}")
        print(f"   Market metadata: {stats['market_metadata']}")

        # Start stats loop only
        stats_task = asyncio.create_task(self.print_stats_loop())

        try:
            await asyncio.gather(stats_task)
        except KeyboardInterrupt:
            print("\n⚠️  Discovery stopped")
            self.db.close()

    async def print_stats_loop(self):
        """Print database stats every 2 minutes"""

        while True:
            await asyncio.sleep(120)

            stats = self.db.get_database_stats()
            pending = self.db.get_pending_trades_summary()

            # Check database file size
            db_path = os.environ.get('DB_PATH', 'trades.db')
            try:
                db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
                db_size_str = f"{db_size_mb:.1f}MB"
            except:
                db_size_str = "?"

            print("\n" + "-"*60)
            print(f"📊 STATS - {datetime.now().strftime('%H:%M:%S')}")
            print("-"*60)
            print(f"🐋 Whales in tiers: {stats['whale_count']}")
            print(f"⏳ Pending trades: {pending['total']} ({pending['ready_to_resolve']} ready)")
            print(f"📈 Incremental stats: {stats['incremental_addresses']} addresses, {stats['incremental_trades']} trades")
            print(f"🗄️  Database size: {db_size_str}")
            print("-"*60 + "\n")

    def get_db(self) -> TradeDatabase:
        """Get database instance"""
        return self.db

    def get_monitoring_addresses(self) -> list:
        """Get list of whale addresses to monitor from database tiers"""
        if not self.db:
            return []
        return list(self.db.get_all_tier_whales())


async def main():
    """Run discovery (standalone mode)"""

    print("="*80)
    print("⚡ DISCOVERY v4 (WebSocket-Primary)")
    print("="*80)
    print()
    print("Architecture:")
    print("  • WebSocket captures whale trades in real-time")
    print("  • Resolution loop tracks PnL after market resolution")
    print("  • No blockchain scanning needed")
    print()
    print("="*80)
    print()

    discovery = UltraFastDiscovery()
    await discovery.run_ultra_fast_discovery()


if __name__ == "__main__":
    asyncio.run(main())
