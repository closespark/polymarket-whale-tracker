"""
Ultra-Fast Discovery System v2 (Optimized)

MAJOR IMPROVEMENTS over v1:
- SQLite storage: No more redundant re-scanning
- Incremental-only: Only scans NEW blocks, appends to database
- Rolling window: Keeps last 50K blocks, prunes old data
- Instant pool refresh: Queries database instead of blockchain

RPC Usage:
- OLD: ~53,000 blocks/hour (wasteful)
- NEW: ~3,000 blocks/hour (94% reduction!)
"""

import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import json

from trade_database import TradeDatabase, get_db_path
from fifteen_minute_analyzer import FifteenMinuteWhaleAnalyzer
import config


class UltraFastDiscovery:
    """
    Optimized scanner with persistent storage

    Scans every minute for new trades, stores in SQLite
    Pool refresh uses stored data - no blockchain re-scanning
    """

    def __init__(self, db_path: str = None):
        # Use lightweight analyzer for blockchain connection only
        self.analyzer = FifteenMinuteWhaleAnalyzer()

        # SQLite database for persistent storage
        # Use environment variable DB_PATH for Render persistent disk
        if db_path is None:
            db_path = get_db_path()
        self.db = TradeDatabase(db_path, max_blocks=50000)

        self.whale_database = {}
        self.monitoring_pool = []
        # Note: monitoring_pool is no longer used for WebSocket monitoring
        # Tiers are populated from database analysis, not this pool

        # Scan interval: Every minute for new blocks
        self.scan_interval = 60

        # Pool refresh interval: Every 15 minutes (uses database, instant)
        self.pool_refresh_interval = 900

        # Pruning interval: Every hour
        self.prune_interval = 3600

        print("⚡ ULTRA-FAST DISCOVERY v2 (Optimized)")
        print(f"   Scan interval: Every {self.scan_interval}s (new blocks only)")
        print(f"   Pool refresh: Every {self.pool_refresh_interval/60:.0f}min (from database)")
        print(f"   Storage: SQLite ({db_path})")

    async def run_ultra_fast_discovery(self):
        """Main loop with incremental scanning"""

        print("\n" + "="*80)
        print("⚡ ULTRA-FAST DISCOVERY v2 ACTIVE")
        print("="*80)
        print("\nOptimized for efficiency:")
        print("  • Only scans NEW blocks (not historical)")
        print("  • Stores all trades in SQLite")
        print("  • Pool refresh from database (instant)")
        print("  • 94% fewer RPC calls than v1\n")

        # Check if we have existing data
        stats = self.db.get_database_stats()

        if stats['trade_count'] > 0:
            print(f"📊 Existing data found:")
            print(f"   Trades: {stats['trade_count']:,}")
            print(f"   Block range: {stats['oldest_block']:,} → {stats['newest_block']:,}")
            print(f"   Coverage: {stats['block_range']:,} blocks")
            # Whale tiers are populated separately from database analysis
        else:
            # Skip deep scan on Render (memory constrained)
            # Instead, build up data via incremental scans
            import os
            if os.environ.get('SKIP_DEEP_SCAN') or os.environ.get('DB_PATH', '').startswith('/var'):
                print("⚠️ No existing data - skipping deep scan (memory constrained)")
                print("   Data will be built incrementally via regular scans")
                print("   Upload pre-scanned trades.db for instant data")
            else:
                print("🔍 No existing data - running initial deep scan...")
                await self.initial_deep_scan()

        # Start all loops
        scan_task = asyncio.create_task(self.incremental_scan_loop())
        refresh_task = asyncio.create_task(self.pool_refresh_loop())
        prune_task = asyncio.create_task(self.prune_loop())
        stats_task = asyncio.create_task(self.print_stats_loop())

        try:
            await asyncio.gather(scan_task, refresh_task, prune_task, stats_task)
        except KeyboardInterrupt:
            print("\n⚠️  Discovery stopped")
            self.db.close()

    async def initial_deep_scan(self):
        """
        One-time deep scan at startup (only if no existing data)
        Scans 50K blocks and stores to database
        """

        print("\n" + "="*80)
        print(f"🔍 INITIAL DEEP SCAN (one-time)")
        print("="*80)
        print("This builds the initial trade database...")
        print("Subsequent runs will only scan NEW blocks.\n")

        current_block = self.analyzer.w3.eth.block_number
        start_block = current_block - 50000

        # Get events in chunks and store to database
        events = self.analyzer._get_events_in_chunks(start_block, current_block)

        print(f"\nStoring {len(events):,} trades to database...")
        added = self.db.add_trades_from_events(events)
        self.db.set_last_scanned_block(current_block)

        print(f"✅ Stored {added:,} trades")

        # Analyze and build whale pool
        await self.refresh_pool_from_database()

    async def incremental_scan_loop(self):
        """
        INCREMENTAL SCAN: Only scan NEW blocks

        This is the key optimization:
        - Get last scanned block from database
        - Only fetch blocks after that
        - Append new trades to database
        - Never re-scan old blocks
        """

        while True:
            try:
                await asyncio.sleep(self.scan_interval)

                current_block = self.analyzer.w3.eth.block_number
                last_scanned = self.db.get_last_scanned_block() or (current_block - 50)

                # Only scan new blocks
                from_block = last_scanned + 1

                if from_block >= current_block:
                    continue  # No new blocks

                blocks_to_scan = current_block - from_block
                print(f"\n⚡ Incremental scan: {blocks_to_scan} new blocks ({from_block} → {current_block})")

                # Fetch new events (chunk if too many blocks to avoid RPC errors)
                # Memory-optimized: process each chunk immediately, don't accumulate
                try:
                    total_added = 0
                    if blocks_to_scan > 2000:
                        # Too many blocks - scan in smaller chunks to avoid OOM
                        chunk_size = 1000  # Reduced from 2000
                        print(f"   Scanning in chunks (max {chunk_size} blocks each)...")
                        chunk_start = from_block
                        while chunk_start < current_block:
                            chunk_end = min(chunk_start + chunk_size, current_block)
                            try:
                                chunk_events = self.analyzer.ctf_exchange.events.OrderFilled.get_logs(
                                    from_block=chunk_start,
                                    to_block=chunk_end
                                )
                                # Process immediately, don't accumulate
                                if chunk_events:
                                    added = self.db.add_trades_from_events(chunk_events)
                                    total_added += added
                                    await self.check_whale_activity(chunk_events)
                                    del chunk_events  # Free memory immediately
                            except Exception as chunk_err:
                                print(f"   ⚠️ Chunk error: {chunk_err}")
                            chunk_start = chunk_end + 1
                            await asyncio.sleep(0.3)  # Rate limit
                        if total_added > 0:
                            print(f"   📥 Stored {total_added} new trades (chunked)")
                    else:
                        events = self.analyzer.ctf_exchange.events.OrderFilled.get_logs(
                            from_block=from_block,
                            to_block=current_block
                        )
                        if events:
                            total_added = self.db.add_trades_from_events(events)
                            print(f"   📥 Stored {total_added} new trades")
                            await self.check_whale_activity(events)
                            del events  # Free memory
                except Exception as e:
                    print(f"   ⚠️ Error fetching events: {e}")
                    await asyncio.sleep(10)
                    continue

                # Update last scanned block
                self.db.set_last_scanned_block(current_block)

            except Exception as e:
                print(f"   ❌ Scan error: {e}")
                await asyncio.sleep(10)

    async def check_whale_activity(self, events):
        """
        Quick check if any monitored whales made trades

        Updates whale_database with recent activity
        """

        monitored_addresses = set(w['address'] for w in self.monitoring_pool)

        for event in events:
            maker = event['args']['maker']
            taker = event['args']['taker']

            for address in [maker, taker]:
                if address in monitored_addresses:
                    # Update last seen
                    if address in self.whale_database:
                        self.whale_database[address]['last_seen'] = datetime.now()
                        self.whale_database[address]['recent_trade_count'] = \
                            self.whale_database[address].get('recent_trade_count', 0) + 1
                        print(f"   🐋 Whale active: {address[:10]}...")

    async def pool_refresh_loop(self):
        """
        POOL REFRESH: Uses database, NOT blockchain

        This is instant because it queries SQLite, not the RPC
        Old version: Re-scanned 50K blocks every hour
        New version: Queries database in <1 second
        """

        while True:
            await asyncio.sleep(self.pool_refresh_interval)
            await self.refresh_pool_from_database()

    async def refresh_pool_from_database(self):
        """
        Refresh whale pool from stored database

        NO BLOCKCHAIN SCANNING - just queries SQLite
        """

        print("\n" + "="*80)
        print(f"🔄 POOL REFRESH (from database) - {datetime.now().strftime('%H:%M:%S')}")
        print("="*80)

        # Analyze all trades in database
        specialists = self.db.analyze_and_cache_traders()

        # Update whale database
        for whale in specialists[:100]:  # Top 100
            address = whale['address']

            if address not in self.whale_database:
                self.whale_database[address] = {
                    'discovery_time': datetime.now(),
                    'last_seen': datetime.now()
                }

            self.whale_database[address].update({
                'address': address,
                'trade_count': whale['trade_count'],
                'estimated_profit': whale['estimated_profit'],
                'estimated_win_rate': whale['win_rate'],
                'wins': whale['wins'],
                'losses': whale['losses'],
                'total_volume': whale['total_volume']
            })

        print(f"   ✅ Analyzed {len(specialists)} traders from database")

        await self.update_pool()

        # Export whale stats
        self.db.export_to_csv('whale_specialists.csv')

    async def prune_loop(self):
        """
        PRUNE: Remove old data to keep database manageable

        Keeps last 50K blocks (rolling window)
        """

        while True:
            await asyncio.sleep(self.prune_interval)

            deleted = self.db.prune_old_blocks(keep_blocks=50000)
            if deleted > 0:
                print(f"\n🗑️ Pruned {deleted:,} old trades (keeping last 50K blocks)")

    async def update_pool(self):
        """
        Update monitoring pool based on latest data
        """

        ranked = []

        for address, data in self.whale_database.items():
            score = 0

            # Factor 1: Recent activity (50% weight)
            last_seen = data.get('last_seen', datetime.min)
            minutes_ago = (datetime.now() - last_seen).total_seconds() / 60

            if minutes_ago < 5:
                score += 50  # Active RIGHT NOW
            elif minutes_ago < 60:
                score += 40 * (1 - minutes_ago/60)
            elif minutes_ago < 1440:
                score += 20 * (1 - minutes_ago/1440)

            # Factor 2: Win rate (30% weight)
            win_rate = data.get('estimated_win_rate', 0.5)
            score += (win_rate - 0.5) * 60  # -30 to +30

            # Factor 3: Profit (20% weight)
            profit = data.get('estimated_profit', 0)
            score += min(profit / 100, 20)  # Cap at 20 points

            ranked.append({
                'address': address,
                'score': score,
                **data
            })

        ranked.sort(key=lambda x: x['score'], reverse=True)

        old_pool = set(w['address'] for w in self.monitoring_pool)
        new_pool = ranked[:25]
        new_addresses = set(w['address'] for w in new_pool)

        added = new_addresses - old_pool
        removed = old_pool - new_addresses

        self.monitoring_pool = new_pool

        if added or removed:
            print(f"\n   🔄 Pool updated: {len(new_pool)} whales")
            if added:
                print(f"      📈 Added {len(added)}")
            if removed:
                print(f"      📉 Removed {len(removed)}")

        self.export_state()

    def export_state(self):
        """Export current state - stats only, no CSV cache"""

        # Stats
        db_stats = self.db.get_database_stats()
        stats = {
            'timestamp': datetime.now().isoformat(),
            'total_whales': len(self.whale_database),
            'database_trades': db_stats['trade_count'],
            'database_blocks': db_stats['block_range'],
            'last_scanned_block': db_stats['last_scanned']
        }

        with open('ultra_fast_stats.json', 'w') as f:
            json.dump(stats, f, indent=2)

    async def print_stats_loop(self):
        """Print stats every 2 minutes"""

        while True:
            await asyncio.sleep(120)

            db_stats = self.db.get_database_stats()

            print("\n" + "-"*80)
            print(f"📊 STATS - {datetime.now().strftime('%H:%M:%S')}")
            print("-"*80)
            print(f"🗄️  Database: {db_stats['trade_count']:,} trades, {db_stats['block_range']:,} blocks")
            print(f"🐋 Total whales: {len(self.whale_database)}")
            print(f"👀 Monitoring: {len(self.monitoring_pool)}")

            # Show top 5
            print(f"\n🏆 TOP 5:")
            for i, w in enumerate(self.monitoring_pool[:5], 1):
                profit = w.get('estimated_profit', 0)
                win_rate = w.get('estimated_win_rate', 0) * 100
                print(f"   #{i} {w['address'][:10]}... (${profit:,.0f} profit, {win_rate:.0f}% WR)")

            print("-"*80 + "\n")

    def get_monitoring_addresses(self):
        """Get addresses for monitor"""
        return [w['address'] for w in self.monitoring_pool]

    async def deep_scan(self):
        """
        Compatibility method - now just refreshes from database
        Called by small_capital_system.py
        """
        await self.refresh_pool_from_database()


async def main():
    """Run optimized discovery"""

    print("="*80)
    print("⚡ ULTRA-FAST DISCOVERY v2 (Optimized)")
    print("="*80)
    print()
    print("Key improvements over v1:")
    print("  • SQLite storage - no more re-scanning")
    print("  • Incremental only - just new blocks")
    print("  • 94% fewer RPC calls")
    print("  • Instant pool refresh")
    print()
    print("="*80)
    print()

    discovery = UltraFastDiscovery()
    await discovery.run_ultra_fast_discovery()


if __name__ == "__main__":
    asyncio.run(main())
