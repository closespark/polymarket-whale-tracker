"""
Trade Database Module
Persistent SQLite storage for blockchain trades with rolling window support.
Eliminates redundant deep scans by storing and querying historical data.
"""

import sqlite3
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def get_db_path() -> str:
    """Get database path from environment or use default"""
    return os.environ.get('DB_PATH', 'trades.db')


class TradeDatabase:
    """
    SQLite-based trade storage with:
    - Persistent storage across restarts
    - Rolling window (keeps last N blocks)
    - Fast querying for whale analysis
    - Incremental updates (only new blocks)
    """

    def __init__(self, db_path: str = "trades.db", max_blocks: int = 50000):
        self.db_path = db_path
        self.max_blocks = max_blocks
        self.conn = None
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with optimized schema"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrent access
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")

        # Create trades table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_number INTEGER NOT NULL,
                tx_hash TEXT,
                maker TEXT NOT NULL,
                taker TEXT NOT NULL,
                maker_amount INTEGER NOT NULL,
                taker_amount INTEGER NOT NULL,
                fee INTEGER DEFAULT 0,
                asset_id TEXT,
                timestamp INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for fast queries
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_block ON trades(block_number)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_maker ON trades(maker)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_taker ON trades(taker)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_block_maker ON trades(block_number, maker)")

        # Create metadata table for tracking scan state
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Create whale stats cache table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_stats (
                address TEXT PRIMARY KEY,
                trade_count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_volume REAL DEFAULT 0,
                estimated_profit REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                first_block INTEGER,
                last_block INTEGER,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create market metadata cache (for timeframe lookups)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS market_metadata (
                token_id TEXT PRIMARY KEY,
                timeframe TEXT DEFAULT 'unknown',
                question TEXT,
                fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create whale timeframe stats cache
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS whale_timeframe_stats (
                address TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                trade_count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                volume REAL DEFAULT 0,
                profit REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (address, timeframe)
            )
        """)

        self.conn.commit()
        print(f"Trade database initialized: {self.db_path}")

    def get_last_scanned_block(self) -> Optional[int]:
        """Get the last block number that was scanned"""
        cursor = self.conn.execute(
            "SELECT value FROM scan_metadata WHERE key = 'last_scanned_block'"
        )
        row = cursor.fetchone()
        return int(row['value']) if row else None

    def set_last_scanned_block(self, block: int):
        """Update the last scanned block"""
        self.conn.execute("""
            INSERT OR REPLACE INTO scan_metadata (key, value)
            VALUES ('last_scanned_block', ?)
        """, (str(block),))
        self.conn.commit()

    def get_oldest_block(self) -> Optional[int]:
        """Get the oldest block in the database"""
        cursor = self.conn.execute("SELECT MIN(block_number) as min_block FROM trades")
        row = cursor.fetchone()
        return row['min_block'] if row and row['min_block'] else None

    def get_trade_count(self) -> int:
        """Get total number of trades in database"""
        cursor = self.conn.execute("SELECT COUNT(*) as count FROM trades")
        return cursor.fetchone()['count']

    def add_trades(self, trades: List[Dict]):
        """
        Bulk insert trades into database

        Args:
            trades: List of trade dicts with keys:
                - block_number, tx_hash, maker, taker
                - maker_amount, taker_amount, fee, asset_id
        """
        if not trades:
            return

        self.conn.executemany("""
            INSERT INTO trades (
                block_number, tx_hash, maker, taker,
                maker_amount, taker_amount, fee, asset_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                t['block_number'],
                t.get('tx_hash', ''),
                t['maker'],
                t['taker'],
                t['maker_amount'],
                t['taker_amount'],
                t.get('fee', 0),
                t.get('asset_id', '')
            )
            for t in trades
        ])
        self.conn.commit()

    def add_trades_from_events(self, events: List):
        """
        Add trades directly from web3 event objects

        Args:
            events: List of web3 event log objects from OrderFilled
        """
        trades = []
        for event in events:
            try:
                trades.append({
                    'block_number': event['blockNumber'],
                    'tx_hash': event.get('transactionHash', b'').hex() if isinstance(event.get('transactionHash'), bytes) else str(event.get('transactionHash', '')),
                    'maker': event['args']['maker'],
                    'taker': event['args']['taker'],
                    'maker_amount': event['args']['makerAmountFilled'],
                    'taker_amount': event['args']['takerAmountFilled'],
                    'fee': event['args'].get('fee', 0),
                    'asset_id': str(event['args'].get('makerAssetId', ''))
                })
            except Exception as e:
                print(f"Error parsing event: {e}")
                continue

        if trades:
            self.add_trades(trades)

        return len(trades)

    def prune_old_blocks(self, keep_blocks: int = None):
        """
        Remove trades older than the rolling window

        Args:
            keep_blocks: Number of recent blocks to keep (default: self.max_blocks)
        """
        keep_blocks = keep_blocks or self.max_blocks

        cursor = self.conn.execute("SELECT MAX(block_number) as max_block FROM trades")
        row = cursor.fetchone()
        if not row or not row['max_block']:
            return 0

        max_block = row['max_block']
        cutoff_block = max_block - keep_blocks

        cursor = self.conn.execute(
            "DELETE FROM trades WHERE block_number < ?",
            (cutoff_block,)
        )
        deleted = cursor.rowcount
        self.conn.commit()

        if deleted > 0:
            # Vacuum to reclaim space
            self.conn.execute("VACUUM")
            print(f"Pruned {deleted:,} old trades (blocks < {cutoff_block:,})")

        return deleted

    def prune_non_whale_trades(self, whale_addresses: List[str], timeout_minutes: int = 10) -> int:
        """
        Remove trades from addresses that are NOT in the whale list.

        This is a major space saver - we only need trades from whales we're tracking.
        Call this AFTER tier analysis to keep only relevant data.

        BLOCKING: This operation locks the database until complete.
        No reads or writes should happen during pruning.

        OPTIMIZED: Uses indexed temp table lookups and batch deletion with progress.

        Args:
            whale_addresses: List of whale addresses to KEEP trades for
            timeout_minutes: Maximum time to spend on deletion (default 10 min)

        Returns:
            Number of trades deleted
        """
        if not whale_addresses:
            print("⚠️ No whale addresses provided - skipping prune")
            return 0

        # Normalize addresses to lowercase for consistent matching
        whale_set = set(addr.lower() for addr in whale_addresses)

        # Get current stats
        before_stats = self.get_database_stats()
        trade_count = before_stats['trade_count']

        # Skip if database is small (< 1000 trades) - not worth the overhead
        if trade_count < 1000:
            print(f"   Database small ({trade_count:,} trades) - skipping prune")
            return 0

        print(f"\n🧹 PRUNING NON-WHALE TRADES (BLOCKING)")
        print(f"   ⏸️  All other database operations paused...")
        print(f"   Before: {trade_count:,} trades")
        print(f"   Keeping trades for {len(whale_set):,} whale addresses")
        print(f"   Timeout: {timeout_minutes} minutes")

        prune_start = time.time()
        timeout_seconds = timeout_minutes * 60

        # STEP 1: Create indexed temp table for fast lookups
        print(f"   [1/5] Creating indexed whale lookup table...")
        self.conn.execute("DROP TABLE IF EXISTS temp_whales")
        self.conn.execute("""
            CREATE TEMP TABLE temp_whales (
                address TEXT PRIMARY KEY
            )
        """)

        # Insert whale addresses (both original case and lowercase for matching)
        whale_list = list(whale_set)
        batch_size = 100
        for i in range(0, len(whale_list), batch_size):
            batch = whale_list[i:i+batch_size]
            self.conn.executemany(
                "INSERT OR IGNORE INTO temp_whales (address) VALUES (?)",
                [(addr,) for addr in batch]
            )
        self.conn.commit()
        print(f"   [1/5] Loaded {len(whale_list)} whale addresses ({time.time() - prune_start:.1f}s)")

        # STEP 2: Count trades to delete (for progress estimation)
        print(f"   [2/5] Estimating trades to delete...")
        count_start = time.time()

        # Use EXPLAIN QUERY PLAN to check if we're using indexes
        # For large datasets, sample-based estimation is faster
        sample_size = min(10000, trade_count // 100)
        if trade_count > 100000:
            # Sample-based estimate for large databases
            cursor = self.conn.execute(f"""
                SELECT COUNT(*) as cnt FROM (
                    SELECT 1 FROM trades
                    WHERE LOWER(maker) NOT IN (SELECT address FROM temp_whales)
                      AND LOWER(taker) NOT IN (SELECT address FROM temp_whales)
                    LIMIT {sample_size}
                )
            """)
            sample_count = cursor.fetchone()['cnt']
            if sample_count == sample_size:
                # Sample hit limit, estimate total
                estimated_delete = int(trade_count * 0.95)  # Assume ~95% are non-whale
                print(f"   [2/5] Estimated ~{estimated_delete:,} trades to delete (sampled)")
            else:
                estimated_delete = sample_count
                print(f"   [2/5] Found {estimated_delete:,} trades to delete")
        else:
            estimated_delete = trade_count  # Will count during deletion
            print(f"   [2/5] Will delete in batches ({time.time() - count_start:.1f}s)")

        # STEP 3: Batch deletion with progress updates
        print(f"   [3/5] Deleting non-whale trades in batches...")
        delete_start = time.time()
        total_deleted = 0
        batch_num = 0
        batch_delete_size = 50000  # Delete 50K at a time for progress updates

        while True:
            batch_num += 1
            batch_start = time.time()

            # Check timeout
            elapsed = time.time() - prune_start
            if elapsed > timeout_seconds:
                print(f"   ⚠️ Timeout reached ({timeout_minutes} min) - stopping deletion")
                print(f"   Deleted {total_deleted:,} trades so far")
                break

            # Delete a batch using rowid for efficiency
            # This approach uses the index on maker/taker more effectively
            cursor = self.conn.execute(f"""
                DELETE FROM trades
                WHERE rowid IN (
                    SELECT rowid FROM trades
                    WHERE LOWER(maker) NOT IN (SELECT address FROM temp_whales)
                      AND LOWER(taker) NOT IN (SELECT address FROM temp_whales)
                    LIMIT {batch_delete_size}
                )
            """)
            batch_deleted = cursor.rowcount
            total_deleted += batch_deleted

            if batch_deleted == 0:
                print(f"   [3/5] Batch deletion complete ({time.time() - delete_start:.1f}s)")
                break

            # Progress update
            elapsed_delete = time.time() - delete_start
            rate = total_deleted / elapsed_delete if elapsed_delete > 0 else 0
            remaining_estimate = (estimated_delete - total_deleted) / rate if rate > 0 else 0

            print(f"   [3/5] Batch {batch_num}: Deleted {batch_deleted:,} trades "
                  f"(total: {total_deleted:,}, {rate:,.0f}/sec, ~{remaining_estimate:.0f}s remaining)")

            self.conn.commit()  # Commit each batch to avoid huge transaction

        deleted = total_deleted

        # STEP 4: Final commit
        print(f"   [4/5] Committing final changes...")
        commit_start = time.time()
        self.conn.commit()
        print(f"   [4/5] Commit complete ({time.time() - commit_start:.1f}s)")

        # Cleanup temp table
        self.conn.execute("DROP TABLE IF EXISTS temp_whales")

        if deleted > 0:
            # STEP 5: Vacuum to reclaim disk space
            print(f"   [5/5] Running VACUUM to reclaim disk space...")
            vacuum_start = time.time()
            self.conn.execute("VACUUM")
            print(f"   [5/5] VACUUM complete ({time.time() - vacuum_start:.1f}s)")

            after_stats = self.get_database_stats()
            total_time = time.time() - prune_start

            print(f"\n   📊 PRUNE SUMMARY:")
            print(f"   Before: {trade_count:,} trades")
            print(f"   After:  {after_stats['trade_count']:,} trades")
            print(f"   Deleted: {deleted:,} non-whale trades")

            # Calculate space savings
            reduction_pct = (1 - after_stats['trade_count'] / trade_count) * 100 if trade_count > 0 else 0
            print(f"   Reduction: {reduction_pct:.1f}%")
            print(f"   Total time: {total_time:.1f}s")
            print(f"   ✅ Prune complete - database operations resuming")
        else:
            print(f"   [5/5] No VACUUM needed")
            print(f"   No non-whale trades to prune")
            print(f"   Total time: {time.time() - prune_start:.1f}s")
            print(f"   ✅ Database already optimized - operations resuming")

        return deleted

    def get_all_trades(self, min_block: int = None, max_block: int = None) -> List[Dict]:
        """
        Get all trades, optionally filtered by block range

        Returns list of dicts for analysis
        """
        query = "SELECT * FROM trades WHERE 1=1"
        params = []

        if min_block:
            query += " AND block_number >= ?"
            params.append(min_block)
        if max_block:
            query += " AND block_number <= ?"
            params.append(max_block)

        query += " ORDER BY block_number ASC"

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_trader_stats(self, address: str) -> Dict:
        """Get cached stats for a specific trader"""
        cursor = self.conn.execute(
            "SELECT * FROM whale_stats WHERE address = ?",
            (address,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def analyze_and_cache_traders(self) -> List[Dict]:
        """
        Analyze all traders from stored trades and cache results

        This replaces the deep scan - runs against stored data, not blockchain
        Returns list of whale stats sorted by estimated profit
        """
        print("Analyzing traders from database...")

        # Get all trades
        cursor = self.conn.execute("""
            SELECT maker, taker, maker_amount, taker_amount, block_number
            FROM trades
        """)

        # Build trader stats in memory
        trader_stats = defaultdict(lambda: {
            'trades': 0,
            'wins': 0,
            'losses': 0,
            'total_volume': 0,
            'first_block': None,
            'last_block': None
        })

        trade_count = 0
        for row in cursor:
            trade_count += 1

            maker = row[0]
            taker = row[1]
            maker_amount = row[2]
            taker_amount = row[3]
            block = row[4]

            # Update maker stats (SELL side)
            self._update_stats(trader_stats[maker], 'SELL', maker_amount, taker_amount, block)

            # Update taker stats (BUY side)
            self._update_stats(trader_stats[taker], 'BUY', taker_amount, maker_amount, block)

        print(f"Processed {trade_count:,} trades for {len(trader_stats):,} unique addresses")

        # Calculate final metrics and filter
        specialists = []
        for address, stats in trader_stats.items():
            if stats['trades'] < 10:
                continue

            total = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total if total > 0 else 0.5
            estimated_profit = stats['total_volume'] * (win_rate - 0.5) * 0.3

            specialists.append({
                'address': address,
                'trade_count': stats['trades'],
                'wins': stats['wins'],
                'losses': stats['losses'],
                'total_volume': stats['total_volume'],
                'estimated_profit': estimated_profit,
                'win_rate': win_rate,
                'first_block': stats['first_block'],
                'last_block': stats['last_block']
            })

        # Sort by profit
        specialists.sort(key=lambda x: x['estimated_profit'], reverse=True)

        # Cache to database
        self._cache_whale_stats(specialists)

        print(f"Found {len(specialists):,} traders with 10+ trades")
        return specialists

    def _update_stats(self, stats: Dict, trade_type: str, token_amount: int, usdc_amount: int, block: int):
        """Update stats for a single trade"""
        stats['trades'] += 1
        stats['total_volume'] += usdc_amount / 1e6  # Convert to USDC

        if stats['first_block'] is None or block < stats['first_block']:
            stats['first_block'] = block
        if stats['last_block'] is None or block > stats['last_block']:
            stats['last_block'] = block

        # Simple win estimation
        price = usdc_amount / token_amount if token_amount > 0 else 0.5
        if trade_type == 'BUY' and price < 0.45:
            stats['wins'] += 1
        elif trade_type == 'SELL' and price > 0.55:
            stats['wins'] += 1
        elif trade_type == 'BUY' and price > 0.75:
            stats['losses'] += 1
        elif trade_type == 'SELL' and price < 0.25:
            stats['losses'] += 1

    def _cache_whale_stats(self, specialists: List[Dict]):
        """Cache whale stats to database for fast lookup"""
        self.conn.execute("DELETE FROM whale_stats")

        self.conn.executemany("""
            INSERT INTO whale_stats (
                address, trade_count, wins, losses, total_volume,
                estimated_profit, win_rate, first_block, last_block
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                s['address'], s['trade_count'], s['wins'], s['losses'],
                s['total_volume'], s['estimated_profit'], s['win_rate'],
                s['first_block'], s['last_block']
            )
            for s in specialists  # Cache all qualified whales
        ])
        self.conn.commit()

    def get_top_whales(self, limit: int = None) -> List[Dict]:
        """Get top whales from cache (instant, no analysis needed)"""
        if limit is None:
            cursor = self.conn.execute("""
                SELECT * FROM whale_stats
                ORDER BY estimated_profit DESC
            """)
        else:
            cursor = self.conn.execute("""
                SELECT * FROM whale_stats
                ORDER BY estimated_profit DESC
                LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def get_database_stats(self) -> Dict:
        """Get summary statistics about the database"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as trade_count,
                MIN(block_number) as oldest_block,
                MAX(block_number) as newest_block,
                COUNT(DISTINCT maker) + COUNT(DISTINCT taker) as unique_addresses
            FROM trades
        """)
        row = cursor.fetchone()

        return {
            'trade_count': row['trade_count'],
            'oldest_block': row['oldest_block'],
            'newest_block': row['newest_block'],
            'block_range': (row['newest_block'] - row['oldest_block']) if row['oldest_block'] and row['newest_block'] else 0,
            'unique_addresses': row['unique_addresses'],
            'last_scanned': self.get_last_scanned_block()
        }

    def export_to_csv(self, filepath: str = "whale_specialists.csv"):
        """Export whale stats to CSV"""
        import csv

        whales = self.get_top_whales(limit=None)  # Export all whales
        if not whales:
            print("No whale data to export")
            return

        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=whales[0].keys())
            writer.writeheader()
            writer.writerows(whales)

        print(f"Exported {len(whales)} whales to {filepath}")

    # ========== MULTI-TIMEFRAME ANALYSIS ==========

    def get_unique_tokens(self, limit: int = 5000) -> List[str]:
        """Get unique asset IDs (token IDs) from trades"""
        cursor = self.conn.execute("""
            SELECT DISTINCT asset_id FROM trades
            WHERE asset_id IS NOT NULL AND asset_id != ''
            LIMIT ?
        """, (limit,))
        return [row[0] for row in cursor.fetchall()]

    def get_cached_timeframe(self, token_id: str) -> Optional[str]:
        """Get cached timeframe for a token"""
        cursor = self.conn.execute(
            "SELECT timeframe FROM market_metadata WHERE token_id = ?",
            (token_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_cached_market_info(self, token_id: str) -> Optional[Dict]:
        """Get cached market info (timeframe and question) for a token"""
        cursor = self.conn.execute(
            "SELECT timeframe, question FROM market_metadata WHERE token_id = ?",
            (token_id,)
        )
        row = cursor.fetchone()
        if row:
            return {'timeframe': row[0], 'question': row[1]}
        return None

    def cache_token_timeframe(self, token_id: str, timeframe: str, question: str = ''):
        """Cache a token's timeframe"""
        self.conn.execute("""
            INSERT OR REPLACE INTO market_metadata (token_id, timeframe, question)
            VALUES (?, ?, ?)
        """, (token_id, timeframe, question))
        self.conn.commit()

    def _infer_timeframe_from_question(self, question: str) -> str:
        """Infer market timeframe from question text"""
        if not question:
            return 'unknown'

        q = question.lower()

        # 15-minute patterns
        if any(p in q for p in ['15 min', '15min', 'next 15', '15-min', 'fifteen min']):
            return '15min'

        # Hourly patterns (but not 4 hour)
        if any(p in q for p in ['1 hour', '1hour', 'next hour', 'in an hour', '60 min', 'one hour']):
            if '4' not in q:  # Avoid matching "4 hour"
                return 'hourly'

        # 4-hour patterns
        if any(p in q for p in ['4 hour', '4hour', '4-hour', 'next 4', 'four hour']):
            return '4hour'

        # Daily patterns
        if any(p in q for p in ['daily', 'by friday', 'by monday', 'by tomorrow',
                                'end of day', 'eod', '24 hour', 'today', 'this week']):
            return 'daily'

        # Crypto price patterns are usually 15min
        if any(p in q for p in ['btc', 'eth', 'sol', 'bitcoin', 'ethereum']):
            if any(p in q for p in ['up', 'down', 'above', 'below', 'price']):
                return '15min'

        return 'daily'  # Default

    def fetch_market_timeframes(self, max_tokens: int = 2000, batch_delay: float = 0.3):
        """
        Fetch market metadata from Polymarket Gamma API and cache timeframes

        Uses the Gamma API which supports direct token ID lookups via clob_token_ids parameter.
        This runs once on startup, then uses cached data.
        """
        if not HAS_REQUESTS:
            print("   requests library not available, skipping API fetch")
            return 0

        tokens_needed = set(self.get_unique_tokens(limit=max_tokens))

        # Check how many we already have cached
        cursor = self.conn.execute("SELECT token_id FROM market_metadata")
        cached_tokens = set(row[0] for row in cursor.fetchall())

        uncached_tokens = tokens_needed - cached_tokens
        cached_count = len(tokens_needed) - len(uncached_tokens)

        if not uncached_tokens:
            print(f"   All {cached_count} tokens already cached")
            return cached_count

        print(f"   {cached_count} cached, {len(uncached_tokens)} need metadata...")

        # Use Gamma API with clob_token_ids parameter for direct lookup
        # Note: API only supports single token lookups, not comma-separated batches
        print(f"   Fetching from Polymarket Gamma API (single token lookup)...")

        token_to_question = {}
        uncached_list = list(uncached_tokens)

        # Limit to prevent excessive API calls on first run
        max_to_fetch = min(len(uncached_list), max_tokens, 500)  # Cap at 500 for first run

        for i, token_id in enumerate(uncached_list[:max_to_fetch]):
            try:
                url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}"
                response = requests.get(url, timeout=10)

                if response.status_code == 200:
                    markets = response.json()
                    # API returns a list for single token query
                    if isinstance(markets, list) and markets:
                        question = markets[0].get('question', '')
                        if question:
                            token_to_question[token_id] = question

            except Exception as e:
                pass  # Skip failed lookups silently

            # Progress update
            if (i + 1) % 50 == 0:
                print(f"      Checked {i + 1}/{max_to_fetch} tokens, found {len(token_to_question)} with metadata...")
                import sys
                sys.stdout.flush()

            time.sleep(batch_delay)  # Rate limit (0.3s = ~3 req/sec)

        print(f"   Found metadata for {len(token_to_question)} tokens")

        # Cache the results
        fetched = 0
        for token_id, question in token_to_question.items():
            timeframe = self._infer_timeframe_from_question(question)
            self.cache_token_timeframe(token_id, timeframe, question[:200])
            fetched += 1

        # Mark remaining as unknown so we don't retry them repeatedly
        for token_id in uncached_tokens - set(token_to_question.keys()):
            self.cache_token_timeframe(token_id, 'unknown', '')

        print(f"   Cached {fetched} new market timeframes")
        return cached_count + fetched

    def analyze_traders_by_timeframe(self) -> Dict[str, List[Dict]]:
        """
        Analyze all traders and group by their best-performing timeframe

        Memory-optimized: Uses SQL aggregation instead of Python dicts
        to handle large datasets within 512MB memory limit.

        Returns: Dict mapping timeframe -> list of qualified traders
        """
        print("Analyzing traders by timeframe (SQL-optimized)...")

        # First, create a temporary table joining trades with timeframes
        # This lets SQLite do the heavy lifting instead of Python
        self.conn.execute("DROP TABLE IF EXISTS temp_trade_timeframes")
        self.conn.execute("""
            CREATE TEMP TABLE temp_trade_timeframes AS
            SELECT
                t.maker, t.taker, t.maker_amount, t.taker_amount,
                m.timeframe,
                CAST(t.taker_amount AS REAL) / 1000000.0 as usdc_amount,
                CASE WHEN t.maker_amount > 0
                     THEN CAST(t.taker_amount AS REAL) / CAST(t.maker_amount AS REAL)
                     ELSE 0.5 END as price
            FROM trades t
            JOIN market_metadata m ON t.asset_id = m.token_id
            WHERE m.timeframe != 'unknown'
        """)

        # Count matched trades
        cursor = self.conn.execute("SELECT COUNT(*) FROM temp_trade_timeframes")
        matched_count = cursor.fetchone()[0]
        print(f"   Matched {matched_count:,} trades with timeframe metadata")

        if matched_count == 0:
            print("   No trades matched - need more market metadata")
            return {'15min': [], 'hourly': [], '4hour': [], 'daily': []}

        # Aggregate stats per address per timeframe using SQL
        # This processes millions of rows without loading them all into Python
        self.conn.execute("DROP TABLE IF EXISTS temp_trader_stats")
        self.conn.execute("""
            CREATE TEMP TABLE temp_trader_stats AS
            SELECT
                address,
                timeframe,
                COUNT(*) as trades,
                SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                SUM(usdc_amount) as volume,
                SUM(CASE WHEN is_win = 1 THEN usdc_amount * 0.3
                         WHEN is_loss = 1 THEN -usdc_amount * 0.2
                         ELSE 0 END) as profit
            FROM (
                -- Maker side (SELL)
                SELECT
                    LOWER(maker) as address,
                    timeframe,
                    usdc_amount,
                    CASE WHEN price > 0.55 THEN 1 ELSE 0 END as is_win,
                    CASE WHEN price < 0.25 THEN 1 ELSE 0 END as is_loss
                FROM temp_trade_timeframes
                UNION ALL
                -- Taker side (BUY)
                SELECT
                    LOWER(taker) as address,
                    timeframe,
                    usdc_amount,
                    CASE WHEN price < 0.45 THEN 1 ELSE 0 END as is_win,
                    CASE WHEN price > 0.75 THEN 1 ELSE 0 END as is_loss
                FROM temp_trade_timeframes
            )
            GROUP BY address, timeframe
            HAVING COUNT(*) >= 10
        """)

        cursor = self.conn.execute("SELECT COUNT(DISTINCT address) FROM temp_trader_stats")
        trader_count = cursor.fetchone()[0]
        print(f"   Found {trader_count:,} traders with 10+ trades in known timeframes")

        # Tier requirements - lowered slightly for more coverage
        tier_requirements = {
            '15min': {'min_trades': 15, 'min_win_rate': 0.70},
            'hourly': {'min_trades': 12, 'min_win_rate': 0.68},
            '4hour': {'min_trades': 8, 'min_win_rate': 0.65},
            'daily': {'min_trades': 8, 'min_win_rate': 0.65}
        }

        tiers = {'15min': [], 'hourly': [], '4hour': [], 'daily': []}

        # Query qualified traders for each timeframe
        # No LIMIT - we monitor ALL qualified whales since set lookup is O(1)
        for tf, req in tier_requirements.items():
            cursor = self.conn.execute("""
                SELECT address, trades, wins, volume, profit,
                       CAST(wins AS REAL) / trades as win_rate
                FROM temp_trader_stats
                WHERE timeframe = ?
                  AND trades >= ?
                  AND CAST(wins AS REAL) / trades >= ?
                ORDER BY (CAST(wins AS REAL) / trades * 0.6) + (MIN(profit / 1000.0, 0.4)) DESC
            """, (tf, req['min_trades'], req['min_win_rate']))

            for row in cursor:
                address, trades, wins, volume, profit, win_rate = row
                score = (win_rate * 0.6) + min(profit / 1000.0, 0.4)
                tiers[tf].append({
                    'address': address,
                    'specialty': tf,
                    'trades': trades,
                    'wins': wins,
                    'win_rate': round(win_rate, 4),
                    'volume': round(volume, 2),
                    'profit': round(profit, 2),
                    'score': round(score, 4)
                })

        # Cleanup temp tables
        self.conn.execute("DROP TABLE IF EXISTS temp_trade_timeframes")
        self.conn.execute("DROP TABLE IF EXISTS temp_trader_stats")

        # Cache results
        self._cache_timeframe_stats(tiers)

        # Print summary
        print(f"\n   Multi-Timeframe Tier Results:")
        for tf, traders in tiers.items():
            print(f"      {tf}: {len(traders)} specialists")

        return tiers

    def _update_tf_stats(self, stats: Dict, side: str, price: float, volume: float):
        """Update timeframe stats for a single trade"""
        stats['trades'] += 1
        stats['volume'] += volume

        is_win = False
        if side == 'BUY' and price < 0.45:
            is_win = True
        elif side == 'SELL' and price > 0.55:
            is_win = True

        if is_win:
            stats['wins'] += 1
            stats['profit'] += volume * 0.3
        elif (side == 'BUY' and price > 0.75) or (side == 'SELL' and price < 0.25):
            stats['losses'] += 1
            stats['profit'] -= volume * 0.2

    def _cache_timeframe_stats(self, tiers: Dict[str, List[Dict]]):
        """Cache timeframe tier results to database"""
        self.conn.execute("DELETE FROM whale_timeframe_stats")

        for tf, traders in tiers.items():
            for t in traders:  # No limit - cache all qualified whales
                self.conn.execute("""
                    INSERT INTO whale_timeframe_stats
                    (address, timeframe, trade_count, wins, losses, volume, profit, win_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (t['address'], tf, t['trades'], t['wins'],
                      t['trades'] - t['wins'], t['volume'], t['profit'], t['win_rate']))

        self.conn.commit()

    def get_timeframe_tiers(self) -> Dict[str, List[Dict]]:
        """Get cached timeframe tier assignments"""
        tiers = {'15min': [], 'hourly': [], '4hour': [], 'daily': []}

        cursor = self.conn.execute("""
            SELECT address, timeframe, trade_count, wins, volume, profit, win_rate
            FROM whale_timeframe_stats
            ORDER BY profit DESC
        """)

        for row in cursor:
            tf = row[1]
            if tf in tiers:
                tiers[tf].append({
                    'address': row[0],
                    'specialty': tf,
                    'trades': row[2],
                    'wins': row[3],
                    'win_rate': row[6],
                    'volume': row[4],
                    'profit': row[5]
                })

        return tiers

    def clear_timeframe_cache(self):
        """Clear cached market metadata and tier assignments to force re-analysis"""
        self.conn.execute("DELETE FROM market_metadata")
        self.conn.execute("DELETE FROM whale_timeframe_stats")
        self.conn.commit()
        print("   Cleared timeframe cache")

    def get_metadata_quality(self) -> dict:
        """Check the quality of cached market metadata"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN timeframe = 'unknown' THEN 1 ELSE 0 END) as unknown,
                SUM(CASE WHEN timeframe = '15min' THEN 1 ELSE 0 END) as min15,
                SUM(CASE WHEN timeframe = 'hourly' THEN 1 ELSE 0 END) as hourly,
                SUM(CASE WHEN timeframe = '4hour' THEN 1 ELSE 0 END) as hour4,
                SUM(CASE WHEN timeframe = 'daily' THEN 1 ELSE 0 END) as daily
            FROM market_metadata
        """)
        row = cursor.fetchone()
        return {
            'total': row[0] or 0,
            'unknown': row[1] or 0,
            'known': (row[0] or 0) - (row[1] or 0),
            '15min': row[2] or 0,
            'hourly': row[3] or 0,
            '4hour': row[4] or 0,
            'daily': row[5] or 0
        }

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


# Standalone test
if __name__ == "__main__":
    db = TradeDatabase("test_trades.db", max_blocks=50000)

    # Add some test trades
    test_trades = [
        {
            'block_number': 100,
            'maker': '0xAAA',
            'taker': '0xBBB',
            'maker_amount': 1000000,
            'taker_amount': 500000
        },
        {
            'block_number': 101,
            'maker': '0xAAA',
            'taker': '0xCCC',
            'maker_amount': 2000000,
            'taker_amount': 900000
        }
    ]

    db.add_trades(test_trades)
    print(f"Database stats: {db.get_database_stats()}")

    db.close()
