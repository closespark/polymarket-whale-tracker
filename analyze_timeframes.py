"""
Multi-Timeframe Tier Analyzer

Analyzes existing trades in the database and assigns traders to appropriate
timeframe tiers (15min, hourly, 4hour, daily) based on their performance.

This script:
1. Queries Polymarket API to get market metadata (including resolution time)
2. Analyzes each trader's performance by market timeframe
3. Assigns traders to their best-performing timeframe tier
4. Saves tier assignments to a JSON file for use by the trading system

Run locally or on Render to populate multi-timeframe tiers.
"""

import sqlite3
import json
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import requests

# Polymarket API endpoints
POLYMARKET_API = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB = "https://clob.polymarket.com"


def get_db_path() -> str:
    """Get database path from environment or use default"""
    return os.environ.get('DB_PATH', 'trades.db')


class MarketMetadataCache:
    """Cache for market metadata from Polymarket API"""

    def __init__(self, cache_file: str = "market_metadata_cache.json"):
        self.cache_file = cache_file
        self.cache: Dict[str, Dict] = {}
        self._load_cache()

    def _load_cache(self):
        """Load cached metadata from file"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
                print(f"Loaded {len(self.cache)} cached markets")
            except:
                self.cache = {}

    def _save_cache(self):
        """Save cache to file"""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)

    def get_market_by_token(self, token_id: str) -> Optional[Dict]:
        """Get market metadata by token ID (asset_id)"""

        # Check cache first
        if token_id in self.cache:
            return self.cache[token_id]

        # Query API
        try:
            # Try CLOB API first (has token mapping)
            url = f"{POLYMARKET_CLOB}/markets/{token_id}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                market = response.json()
                self.cache[token_id] = market
                return market

            # Fall back to gamma API search
            url = f"{POLYMARKET_API}/markets"
            params = {"token_id": token_id}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                markets = response.json()
                if markets:
                    market = markets[0]
                    self.cache[token_id] = market
                    return market

        except Exception as e:
            pass

        return None

    def get_market_timeframe(self, market_data: Dict) -> str:
        """
        Determine market timeframe from metadata

        Returns: '15min', 'hourly', '4hour', or 'daily'
        """
        if not market_data:
            return 'unknown'

        # Check market question/title
        question = market_data.get('question', '') or market_data.get('title', '')
        question_lower = question.lower()

        # 15-minute patterns
        if any(p in question_lower for p in ['15 min', '15min', 'next 15', '15-min']):
            return '15min'

        # Hourly patterns (but not 4 hour)
        if any(p in question_lower for p in ['1 hour', '1hour', 'next hour', 'in an hour', '60 min']):
            return 'hourly'

        # 4-hour patterns
        if any(p in question_lower for p in ['4 hour', '4hour', '4-hour', 'next 4']):
            return '4hour'

        # Daily patterns
        if any(p in question_lower for p in ['daily', 'by friday', 'by monday', 'by tomorrow',
                                              'end of day', 'eod', '24 hour', 'today']):
            return 'daily'

        # Check resolution time if available
        end_date = market_data.get('end_date_iso') or market_data.get('end_date')
        if end_date:
            try:
                # Parse end date and compare to creation
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                created = market_data.get('created_at') or market_data.get('created_time')
                if created:
                    created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    duration = end_dt - created_dt

                    if duration <= timedelta(minutes=30):
                        return '15min'
                    elif duration <= timedelta(hours=2):
                        return 'hourly'
                    elif duration <= timedelta(hours=6):
                        return '4hour'
                    else:
                        return 'daily'
            except:
                pass

        # Default - check for crypto price patterns (usually 15min)
        if any(p in question_lower for p in ['btc', 'eth', 'sol', 'crypto', 'bitcoin', 'ethereum']):
            if 'up' in question_lower or 'down' in question_lower or 'above' in question_lower:
                return '15min'  # Most crypto price markets are 15min

        return 'daily'  # Default to daily for unknown


class TimeframeAnalyzer:
    """Analyze traders and assign them to timeframe tiers"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_db_path()
        self.conn = None
        self.metadata_cache = MarketMetadataCache()

        # Trader stats by timeframe
        self.trader_stats: Dict[str, Dict[str, Dict]] = defaultdict(lambda: {
            '15min': {'trades': 0, 'wins': 0, 'losses': 0, 'volume': 0, 'profit': 0},
            'hourly': {'trades': 0, 'wins': 0, 'losses': 0, 'volume': 0, 'profit': 0},
            '4hour': {'trades': 0, 'wins': 0, 'losses': 0, 'volume': 0, 'profit': 0},
            'daily': {'trades': 0, 'wins': 0, 'losses': 0, 'volume': 0, 'profit': 0},
            'unknown': {'trades': 0, 'wins': 0, 'losses': 0, 'volume': 0, 'profit': 0}
        })

        # Cache of token_id -> timeframe
        self.token_timeframes: Dict[str, str] = {}

    def connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        print(f"Connected to database: {self.db_path}")

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def get_unique_tokens(self) -> List[str]:
        """Get all unique asset IDs (token IDs) from trades"""
        cursor = self.conn.execute("""
            SELECT DISTINCT asset_id
            FROM trades
            WHERE asset_id IS NOT NULL AND asset_id != ''
        """)
        tokens = [row['asset_id'] for row in cursor.fetchall()]
        print(f"Found {len(tokens)} unique tokens in database")
        return tokens

    def fetch_market_timeframes(self, batch_size: int = 100, max_tokens: int = 5000):
        """
        Fetch market metadata for tokens and determine their timeframes

        This queries the Polymarket API to get market info for each token
        """
        tokens = self.get_unique_tokens()[:max_tokens]

        print(f"\nFetching market metadata for {len(tokens)} tokens...")
        print("This may take a few minutes (rate limited API calls)")

        fetched = 0
        cached = 0

        for i, token in enumerate(tokens):
            # Check if already in cache
            if token in self.token_timeframes:
                cached += 1
                continue

            if token in self.metadata_cache.cache:
                market = self.metadata_cache.cache[token]
                timeframe = self.metadata_cache.get_market_timeframe(market)
                self.token_timeframes[token] = timeframe
                cached += 1
                continue

            # Fetch from API
            market = self.metadata_cache.get_market_by_token(token)
            if market:
                timeframe = self.metadata_cache.get_market_timeframe(market)
                self.token_timeframes[token] = timeframe
                fetched += 1
            else:
                self.token_timeframes[token] = 'unknown'

            # Progress update
            if (i + 1) % 100 == 0:
                print(f"   Processed {i+1}/{len(tokens)} tokens ({fetched} fetched, {cached} cached)")

            # Rate limit
            if fetched % 10 == 0:
                time.sleep(0.5)  # 500ms delay every 10 fetches

        # Save cache
        self.metadata_cache._save_cache()

        # Print summary
        timeframe_counts = defaultdict(int)
        for tf in self.token_timeframes.values():
            timeframe_counts[tf] += 1

        print(f"\nToken timeframe distribution:")
        for tf, count in sorted(timeframe_counts.items()):
            print(f"   {tf}: {count} tokens")

    def analyze_traders(self):
        """
        Analyze all trades and build trader stats by timeframe
        """
        print("\nAnalyzing trader performance by timeframe...")

        # Get all trades with asset IDs
        cursor = self.conn.execute("""
            SELECT maker, taker, maker_amount, taker_amount, asset_id, block_number
            FROM trades
            WHERE asset_id IS NOT NULL AND asset_id != ''
            ORDER BY block_number ASC
        """)

        trade_count = 0
        unknown_tokens = 0

        for row in cursor:
            trade_count += 1

            maker = row['maker']
            taker = row['taker']
            maker_amount = row['maker_amount']
            taker_amount = row['taker_amount']
            token = row['asset_id']

            # Get timeframe for this token
            timeframe = self.token_timeframes.get(token, 'unknown')
            if timeframe == 'unknown':
                unknown_tokens += 1

            # Calculate trade outcome (simplified)
            usdc_amount = taker_amount / 1e6 if taker_amount else 0
            token_amount = maker_amount / 1e6 if maker_amount else 1
            price = usdc_amount / token_amount if token_amount > 0 else 0.5

            # Update maker stats (SELL side)
            self._update_trader_stats(maker, timeframe, 'SELL', price, usdc_amount)

            # Update taker stats (BUY side)
            self._update_trader_stats(taker, timeframe, 'BUY', price, usdc_amount)

            if trade_count % 500000 == 0:
                print(f"   Processed {trade_count:,} trades...")

        print(f"\nAnalyzed {trade_count:,} trades for {len(self.trader_stats):,} traders")
        print(f"   Unknown token timeframes: {unknown_tokens:,}")

    def _update_trader_stats(self, address: str, timeframe: str, side: str, price: float, volume: float):
        """Update stats for a single trade"""
        stats = self.trader_stats[address.lower()][timeframe]
        stats['trades'] += 1
        stats['volume'] += volume

        # Simple win estimation based on price
        is_win = False
        if side == 'BUY' and price < 0.45:
            is_win = True
        elif side == 'SELL' and price > 0.55:
            is_win = True

        if is_win:
            stats['wins'] += 1
            stats['profit'] += volume * 0.3  # Estimated 30% profit
        elif (side == 'BUY' and price > 0.75) or (side == 'SELL' and price < 0.25):
            stats['losses'] += 1
            stats['profit'] -= volume * 0.2  # Estimated 20% loss

    def assign_traders_to_tiers(self) -> Dict[str, List[Dict]]:
        """
        Assign traders to their best-performing timeframe tier

        Returns: Dict mapping timeframe to list of trader data
        """
        print("\nAssigning traders to timeframe tiers...")

        # Tier requirements
        tier_requirements = {
            '15min': {'min_trades': 20, 'min_win_rate': 0.75},
            'hourly': {'min_trades': 15, 'min_win_rate': 0.73},
            '4hour': {'min_trades': 10, 'min_win_rate': 0.72},
            'daily': {'min_trades': 10, 'min_win_rate': 0.70}
        }

        tiers = {
            '15min': [],
            'hourly': [],
            '4hour': [],
            'daily': []
        }

        for address, tf_stats in self.trader_stats.items():
            # Find their best timeframe
            best_tf = None
            best_score = 0

            for tf in ['15min', 'hourly', '4hour', 'daily']:
                stats = tf_stats[tf]
                trades = stats['trades']

                if trades < tier_requirements[tf]['min_trades']:
                    continue

                win_rate = stats['wins'] / trades if trades > 0 else 0

                if win_rate < tier_requirements[tf]['min_win_rate']:
                    continue

                # Score: combination of win rate and profit
                score = (win_rate * 0.6) + (min(stats['profit'] / 1000, 0.4))

                if score > best_score:
                    best_score = score
                    best_tf = tf

            if best_tf:
                stats = tf_stats[best_tf]
                trades = stats['trades']
                win_rate = stats['wins'] / trades if trades > 0 else 0

                tiers[best_tf].append({
                    'address': address,
                    'specialty': best_tf,
                    'trades': trades,
                    'wins': stats['wins'],
                    'win_rate': round(win_rate, 4),
                    'volume': round(stats['volume'], 2),
                    'profit': round(stats['profit'], 2),
                    'score': round(best_score, 4),
                    # Include stats for other timeframes
                    'all_timeframes': {
                        tf: {
                            'trades': s['trades'],
                            'win_rate': round(s['wins'] / s['trades'], 4) if s['trades'] > 0 else 0
                        }
                        for tf, s in tf_stats.items() if s['trades'] > 0
                    }
                })

        # Sort each tier by score
        for tf in tiers:
            tiers[tf].sort(key=lambda x: x['score'], reverse=True)

        return tiers

    def print_tier_summary(self, tiers: Dict[str, List[Dict]]):
        """Print summary of tier assignments"""
        print("\n" + "="*80)
        print("MULTI-TIMEFRAME TIER ANALYSIS RESULTS")
        print("="*80)

        for tf, traders in tiers.items():
            print(f"\n{tf.upper()} SPECIALISTS ({len(traders)} traders):")
            print("-"*60)

            if not traders:
                print("   No qualified traders found")
                continue

            # Show top 10
            for i, t in enumerate(traders[:10]):
                print(f"   {i+1}. {t['address'][:10]}... | "
                      f"Win: {t['win_rate']*100:.1f}% | "
                      f"Trades: {t['trades']} | "
                      f"Profit: ${t['profit']:.0f}")

            if len(traders) > 10:
                print(f"   ... and {len(traders)-10} more")

        # Overall summary
        total = sum(len(t) for t in tiers.values())
        print(f"\n{'='*80}")
        print(f"TOTAL SPECIALISTS: {total}")
        for tf, traders in tiers.items():
            print(f"   {tf}: {len(traders)} traders")
        print("="*80)

    def save_tier_assignments(self, tiers: Dict[str, List[Dict]], output_file: str = "timeframe_tiers.json"):
        """Save tier assignments to JSON file"""
        output = {
            'generated_at': datetime.now().isoformat(),
            'database': self.db_path,
            'tiers': {}
        }

        # Limit each tier to top N traders
        tier_limits = {
            '15min': 15,
            'hourly': 15,
            '4hour': 10,
            'daily': 10
        }

        for tf, traders in tiers.items():
            limit = tier_limits.get(tf, 10)
            output['tiers'][tf] = traders[:limit]

        with open(output_file, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\nSaved tier assignments to {output_file}")
        return output_file


def main():
    """Main analysis pipeline"""
    print("="*80)
    print("MULTI-TIMEFRAME TIER ANALYZER")
    print("="*80)
    print()

    db_path = get_db_path()
    print(f"Database: {db_path}")

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return

    analyzer = TimeframeAnalyzer(db_path)

    try:
        analyzer.connect()

        # Step 1: Fetch market metadata (timeframes)
        print("\n" + "="*80)
        print("STEP 1: FETCHING MARKET METADATA")
        print("="*80)
        analyzer.fetch_market_timeframes(max_tokens=3000)

        # Step 2: Analyze trader performance by timeframe
        print("\n" + "="*80)
        print("STEP 2: ANALYZING TRADER PERFORMANCE")
        print("="*80)
        analyzer.analyze_traders()

        # Step 3: Assign traders to tiers
        print("\n" + "="*80)
        print("STEP 3: ASSIGNING TRADERS TO TIERS")
        print("="*80)
        tiers = analyzer.assign_traders_to_tiers()

        # Print results
        analyzer.print_tier_summary(tiers)

        # Save results
        output_file = analyzer.save_tier_assignments(tiers)

        print("\n" + "="*80)
        print("ANALYSIS COMPLETE!")
        print("="*80)
        print(f"Results saved to: {output_file}")
        print("\nNext steps:")
        print("1. Copy timeframe_tiers.json to Render")
        print("2. Update small_capital_system.py to load tiers from file")
        print("3. Restart the trading system")

    finally:
        analyzer.close()


if __name__ == "__main__":
    import sys

    # Can be run with: python analyze_timeframes.py
    # Or on Render: python analyze_timeframes.py /var/data/trades.db

    if len(sys.argv) > 1:
        os.environ['DB_PATH'] = sys.argv[1]

    main()
