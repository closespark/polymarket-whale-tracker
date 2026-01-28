"""
Multi-Timeframe Trading Strategy

Expands beyond 15-minute markets to capture more opportunities:
- Tier 1: 15-minute specialists (highest priority)
- Tier 2: Hourly specialists
- Tier 3: 4-hour specialists
- Tier 4: Daily specialists

Benefits:
- 2x more trading opportunities
- 90%+ capital utilization (vs 70%)
- Diversification across timeframes
- Better compounding

Expected impact: +50-100% more trades, +30-50% ROI increase
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import json
import re
import os


class WhaleTimeframeTier:
    """Represents a tier of whale specialists for a specific timeframe"""

    def __init__(self,
                 name: str,
                 timeframe: str,
                 base_threshold: float,
                 position_multiplier: float,
                 min_win_rate: float,
                 max_whales: int = 15):
        self.name = name
        self.timeframe = timeframe
        self.base_threshold = base_threshold
        self.position_multiplier = position_multiplier
        self.min_win_rate = min_win_rate
        self.max_whales = max_whales
        self.whales: List[Dict] = []

    def add_whale(self, whale_data: Dict):
        """Add a whale specialist to this tier"""
        # max_whales=None means unlimited
        if self.max_whales is None or len(self.whales) < self.max_whales:
            self.whales.append(whale_data)

    def is_whale_in_tier(self, address: str) -> bool:
        """Check if address is in this tier"""
        return any(w.get('address', '').lower() == address.lower() for w in self.whales)

    def get_whale_data(self, address: str) -> Optional[Dict]:
        """Get whale data if in tier"""
        for w in self.whales:
            if w.get('address', '').lower() == address.lower():
                return w
        return None


class MultiTimeframeStrategy:
    """
    Multi-timeframe whale-following strategy

    Tiers:
    1. 15-min specialists: 88% threshold, 1.2x position (their specialty)
    2. Hourly specialists: 90% threshold, 1.0x position
    3. 4-hour specialists: 92% threshold, 0.8x position
    4. Daily specialists: 93% threshold, 0.7x position

    When a whale trades OUTSIDE their specialty timeframe:
    - Higher threshold (+6%)
    - Smaller position (0.6-0.8x)
    """

    def __init__(self):
        # Define tiers - no artificial limits, monitor all qualified whales
        # Note: min_win_rate here is for COPY THRESHOLD (higher), not for discovery
        # Discovery uses lower thresholds in trade_database.py to find more whales
        self.tiers = {
            '15min': WhaleTimeframeTier(
                name='Tier 1: 15-Min Specialists',
                timeframe='15min',
                base_threshold=88.0,
                position_multiplier=1.2,
                min_win_rate=0.70,  # Lowered for more coverage (confidence still filters)
                max_whales=None  # Unlimited
            ),
            'hourly': WhaleTimeframeTier(
                name='Tier 2: Hourly Specialists',
                timeframe='hourly',
                base_threshold=90.0,
                position_multiplier=1.0,
                min_win_rate=0.68,
                max_whales=None  # Unlimited
            ),
            '4hour': WhaleTimeframeTier(
                name='Tier 3: 4-Hour Specialists',
                timeframe='4hour',
                base_threshold=92.0,
                position_multiplier=0.8,
                min_win_rate=0.65,
                max_whales=None  # Unlimited
            ),
            'daily': WhaleTimeframeTier(
                name='Tier 4: Daily Specialists',
                timeframe='daily',
                base_threshold=93.0,
                position_multiplier=0.7,
                min_win_rate=0.65,
                max_whales=None  # Unlimited
            )
        }

        # Outside-specialty adjustments
        self.outside_specialty_threshold_boost = 6.0  # +6% threshold
        self.outside_specialty_position_mult = 0.7    # 0.7x position

        # Stats
        self.trades_by_tier = defaultdict(lambda: {'total': 0, 'wins': 0, 'profit': 0})
        self.trades_in_specialty = 0
        self.trades_outside_specialty = 0

        print("📊 Multi-Timeframe Strategy initialized")
        print(f"   Tiers: {list(self.tiers.keys())}")

    def detect_market_timeframe(self, market_name: str) -> str:
        """
        Detect the timeframe of a market from its name by parsing end time.

        Uses current time (ET) to determine timeframe bucket:
        - 15min: ends within 15 minutes
        - hourly: ends within 1 hour
        - 4hour: ends within 4 hours
        - daily: ends within 24 hours

        Examples:
        - "Bitcoin Up or Down - January 27, 6PM ET" → parse end time, compare to now
        - "Ethereum Up or Down on January 28?" → daily (tomorrow)
        - "BTC Up in Next 15 Minutes" → 15min (legacy pattern)
        """
        market_lower = market_name.lower()

        # First check legacy patterns (explicit timeframe in name)
        if any(p in market_lower for p in ['15 min', '15min', 'next 15', '15-min']):
            return '15min'

        if any(p in market_lower for p in ['4 hour', '4hour', '4-hour', 'next 4']):
            return '4hour'

        # Try to parse date/time from market name
        # Patterns like "January 27, 6PM ET" or "January 28?"
        from datetime import datetime
        import pytz

        try:
            et_tz = pytz.timezone('US/Eastern')
            now_et = datetime.now(et_tz)

            # Pattern: "Month Day, TimeAM/PM ET" or "Month Day, Time:MinAM/PM-Time:MinAM/PM ET"
            # Examples:
            #   "January 27, 6PM ET"
            #   "January 28, 9:45AM-10:00AM ET" (15-min markets with time range)

            # First try time range pattern (e.g., "9:45AM-10:00AM ET") - extract END time
            time_range_match = re.search(
                r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*\d{1,2}:\d{2}(?:am|pm)?-(\d{1,2}):(\d{2})(am|pm)\s*et',
                market_lower
            )

            if time_range_match:
                month_name = time_range_match.group(1)
                day = int(time_range_match.group(2))
                hour = int(time_range_match.group(3))
                minute = int(time_range_match.group(4))
                ampm = time_range_match.group(5)
            else:
                # Try simple time pattern (e.g., "6PM ET")
                time_match = re.search(
                    r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2}),?\s*(\d{1,2})(am|pm)\s*et',
                    market_lower
                )
                if time_match:
                    month_name = time_match.group(1)
                    day = int(time_match.group(2))
                    hour = int(time_match.group(3))
                    minute = 0
                    ampm = time_match.group(4)
                else:
                    time_match = None
                    time_range_match = None

            if time_match or time_range_match:
                # month_name, day, hour, minute, ampm are set above

                # Convert to 24-hour
                if ampm == 'pm' and hour != 12:
                    hour += 12
                elif ampm == 'am' and hour == 12:
                    hour = 0

                # Build end datetime
                month_num = ['january', 'february', 'march', 'april', 'may', 'june',
                            'july', 'august', 'september', 'october', 'november', 'december'].index(month_name) + 1

                end_time = et_tz.localize(datetime(now_et.year, month_num, day, hour, minute, 0))

                # If end_time is in the past, it might be next year
                if end_time < now_et:
                    end_time = et_tz.localize(datetime(now_et.year + 1, month_num, day, hour, minute, 0))

                # Calculate time until end
                time_until_end = (end_time - now_et).total_seconds() / 3600  # hours

                if time_until_end <= 0.25:  # 15 minutes
                    return '15min'
                elif time_until_end <= 1:
                    return 'hourly'
                elif time_until_end <= 4:
                    return '4hour'
                elif time_until_end <= 24:
                    return 'daily'
                else:
                    return 'unknown'  # More than 24 hours out

            # Pattern: "on Month Day?" (e.g., "on January 28?") - daily markets
            date_match = re.search(
                r'on\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})',
                market_lower
            )

            if date_match:
                month_name = date_match.group(1)
                day = int(date_match.group(2))
                month_num = ['january', 'february', 'march', 'april', 'may', 'june',
                            'july', 'august', 'september', 'october', 'november', 'december'].index(month_name) + 1

                # Assume end of day (11:59 PM ET)
                end_time = et_tz.localize(datetime(now_et.year, month_num, day, 23, 59, 0))

                if end_time < now_et:
                    end_time = et_tz.localize(datetime(now_et.year + 1, month_num, day, 23, 59, 0))

                time_until_end = (end_time - now_et).total_seconds() / 3600

                if time_until_end <= 24:
                    return 'daily'
                else:
                    return 'unknown'

        except Exception as e:
            # If parsing fails, fall back to pattern matching
            pass

        # Legacy hour patterns (e.g., "2 hours", "6 hours")
        hour_match = re.search(r'(\d+)\s*hour', market_lower)
        if hour_match:
            hours = int(hour_match.group(1))
            if hours <= 1:
                return 'hourly'
            elif hours <= 4:
                return '4hour'
            else:
                return 'daily'

        # Unknown timeframe - don't process
        return 'unknown'

    def find_whale_tier(self, whale_address: str) -> Tuple[Optional[str], Optional[WhaleTimeframeTier]]:
        """Find which tier a whale belongs to"""
        whale_lower = whale_address.lower()

        for tier_name, tier in self.tiers.items():
            if tier.is_whale_in_tier(whale_lower):
                return tier_name, tier

        return None, None

    def _is_blocked_market(self, market_question: str) -> bool:
        """
        Check if market should be blocked based on historical loss patterns.

        Currently blocks: Soccer/football O/U markets (Champions League, Europa League, etc.)
        These showed poor performance in backtesting despite high confidence scores.
        """
        if not market_question:
            return False

        q = market_question.lower()

        # Block soccer O/U markets - identified as loss pattern
        # These contain team names (FC, Club, United, City) + O/U betting lines
        soccer_team_indicators = ['fc', 'club', 'united', 'city', 'sc', 'cf']
        is_over_under = 'o/u' in q or 'over/under' in q
        has_soccer_team = any(indicator in q for indicator in soccer_team_indicators)

        if is_over_under and has_soccer_team:
            return True

        return False

    def should_copy_trade(self,
                          whale_address: str,
                          trade_data: Dict,
                          base_confidence: float) -> Dict:
        """
        Determine if we should copy this trade

        Returns:
            {
                'should_copy': bool,
                'threshold': float,
                'position_multiplier': float,
                'tier': str,
                'is_specialty': bool,
                'reason': str
            }
        """

        # Use timeframe from trade_data (extracted from Gamma API recurrence field)
        # No fallback to name parsing - recurrence is the only reliable source
        market_timeframe = trade_data.get('timeframe', 'unknown')

        # Filter out blocked market types (e.g., Champions League O/U)
        market_question = trade_data.get('market', trade_data.get('market_question', ''))
        if self._is_blocked_market(market_question):
            return {
                'should_copy': False,
                'threshold': 100.0,
                'position_multiplier': 0.0,
                'tier': 'blocked',
                'market_timeframe': market_timeframe,
                'is_specialty': False,
                'reason': f'Blocked market type (soccer O/U): {market_question[:50]}...'
            }

        # Filter out unknown timeframes (weekly, monthly, pre-market, etc.)
        if market_timeframe == 'unknown':
            market = trade_data.get('market', trade_data.get('market_question', ''))
            return {
                'should_copy': False,
                'threshold': 100.0,
                'position_multiplier': 0.0,
                'tier': 'unknown',
                'market_timeframe': 'unknown',
                'is_specialty': False,
                'reason': f'No recurrence field from Gamma API: {market[:50]}...'
            }

        # Find whale's tier
        whale_tier_name, whale_tier = self.find_whale_tier(whale_address)

        if whale_tier is None:
            # Whale not in any tier - use conservative defaults
            return {
                'should_copy': False,
                'threshold': 95.0,
                'position_multiplier': 0.5,
                'tier': 'unknown',
                'market_timeframe': market_timeframe,  # Preserve timeframe for logging
                'is_specialty': False,
                'reason': 'Whale not in monitored tiers'
            }

        # Check if trading in their specialty
        is_specialty = (whale_tier.timeframe == market_timeframe)

        if is_specialty:
            # Trading in specialty - use tier's base values
            threshold = whale_tier.base_threshold
            position_mult = whale_tier.position_multiplier
            self.trades_in_specialty += 1
        else:
            # Trading outside specialty - be more conservative
            threshold = whale_tier.base_threshold + self.outside_specialty_threshold_boost
            position_mult = whale_tier.position_multiplier * self.outside_specialty_position_mult
            self.trades_outside_specialty += 1

        # Check confidence against threshold
        should_copy = base_confidence >= threshold

        # Build reason
        if should_copy:
            if is_specialty:
                reason = f"✅ {whale_tier.name} trading {market_timeframe} (specialty)"
            else:
                reason = f"⚠️ {whale_tier.name} trading {market_timeframe} (outside specialty, higher threshold)"
        else:
            reason = f"❌ Confidence {base_confidence:.1f}% < threshold {threshold:.1f}%"

        return {
            'should_copy': should_copy,
            'threshold': threshold,
            'position_multiplier': position_mult,
            'tier': whale_tier_name,
            'tier_name': whale_tier.name,
            'is_specialty': is_specialty,
            'market_timeframe': market_timeframe,
            'reason': reason
        }

    def calculate_position_size(self,
                                base_size: float,
                                tier_result: Dict) -> float:
        """
        Apply tier-specific position multiplier

        Args:
            base_size: Position size from Kelly criterion
            tier_result: Result from should_copy_trade()

        Returns:
            Adjusted position size
        """
        multiplier = tier_result.get('position_multiplier', 1.0)
        return base_size * multiplier

    def record_trade_result(self, tier: str, is_win: bool, profit: float):
        """Record trade result for tier statistics"""
        self.trades_by_tier[tier]['total'] += 1
        if is_win:
            self.trades_by_tier[tier]['wins'] += 1
        self.trades_by_tier[tier]['profit'] += profit

    def add_whale_to_tier(self, whale_data: Dict, timeframe: str):
        """Add a whale specialist to the appropriate tier"""
        if timeframe in self.tiers:
            self.tiers[timeframe].add_whale(whale_data)

    def populate_from_database(self, db_connection):
        """
        Populate tiers from database analysis

        Analyzes traders and assigns them to appropriate tiers
        based on their performance in each timeframe
        """
        # This would query the database and analyze each trader's
        # performance by market timeframe
        pass

    def load_from_database(self, db) -> bool:
        """
        Load tier assignments from database timeframe analysis

        This runs on startup and analyzes traders by their performance
        in different market timeframes (15min, hourly, 4hour, daily).

        Args:
            db: TradeDatabase instance

        Returns:
            True if loaded successfully
        """
        try:
            import os
            skip_analysis = os.environ.get('SKIP_ANALYSIS', 'false').lower() == 'true'

            # First check if we have cached tiers
            tiers_data = db.get_timeframe_tiers()
            total = sum(len(t) for t in tiers_data.values())

            # If SKIP_ANALYSIS=true, only use cached data (for memory-constrained environments)
            if skip_analysis:
                if total > 0:
                    print(f"   SKIP_ANALYSIS=true - Loading {total} whales from pre-computed cache")
                else:
                    print("   ⚠️ SKIP_ANALYSIS=true but no cached data found!")
                    print("   Run analysis locally and upload the database with pre-computed stats")
                    return False
            else:
                # Check token timeframes quality - if mostly unknown, clear cache and refetch
                if hasattr(db, 'get_token_timeframes_stats'):
                    stats = db.get_token_timeframes_stats()
                    known = stats.get('known', 0)
                    unknown = stats.get('unknown', 0)
                    total_meta = stats.get('total', 0)

                    # If we have metadata but >90% is unknown, clear and refetch
                    if total_meta > 100 and unknown > 0 and (unknown / total_meta) > 0.90:
                        print(f"   Poor token data quality ({known} known, {unknown} unknown) - clearing cache...")
                        db.clear_timeframe_cache()

                # App loads from pre-computed whale_timeframe_stats
                # Analysis is done by standalone script, not the live app
                if total == 0:
                    print("   ⚠️ No whale tier data found in database")
                    print("   Run standalone script to populate whale_timeframe_stats table")

            if total == 0:
                print("   No timeframe specialists found in database")
                return False

            # Populate tiers
            for tf_name, traders in tiers_data.items():
                if tf_name not in self.tiers:
                    continue

                tier = self.tiers[tf_name]

                for trader in traders:
                    # max_whales=None means unlimited
                    if tier.max_whales is not None and len(tier.whales) >= tier.max_whales:
                        break

                    whale_data = {
                        'address': trader.get('address', ''),
                        'win_rate': trader.get('win_rate', 0.70),
                        'trade_count': trader.get('trades', 0),
                        'profit': trader.get('profit', 0),
                        'timeframe_specialty': tf_name
                    }
                    tier.add_whale(whale_data)

            # Count actual loaded whales
            loaded_count = sum(len(tier.whales) for tier in self.tiers.values())
            print(f"   Loaded {loaded_count} qualified whales into tiers:")
            for tf_name, tier in self.tiers.items():
                print(f"      {tier.name}: {len(tier.whales)} whales")

            return True

        except Exception as e:
            print(f"   Error loading from database: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_all_monitored_addresses(self) -> List[str]:
        """Get all whale addresses across all tiers"""
        addresses = []
        for tier in self.tiers.values():
            for whale in tier.whales:
                addr = whale.get('address', '')
                if addr and addr not in addresses:
                    addresses.append(addr)
        return addresses

    def get_tier_stats(self) -> str:
        """Get statistics for each tier"""
        lines = ["\n📊 MULTI-TIMEFRAME TIER STATISTICS", "=" * 60]

        for tier_name, tier in self.tiers.items():
            stats = self.trades_by_tier[tier_name]
            total = stats['total']
            wins = stats['wins']
            profit = stats['profit']
            win_rate = (wins / total * 100) if total > 0 else 0

            lines.append(f"\n{tier.name}:")
            max_str = str(tier.max_whales) if tier.max_whales is not None else "unlimited"
            lines.append(f"   Whales: {len(tier.whales)}/{max_str}")
            lines.append(f"   Trades: {total}")
            lines.append(f"   Win rate: {win_rate:.1f}%")
            lines.append(f"   Profit: ${profit:.2f}")
            lines.append(f"   Threshold: {tier.base_threshold}%")
            lines.append(f"   Position mult: {tier.position_multiplier}x")

        # Overall stats
        total_trades = self.trades_in_specialty + self.trades_outside_specialty
        if total_trades > 0:
            specialty_pct = self.trades_in_specialty / total_trades * 100
            lines.append(f"\n📈 SPECIALTY BREAKDOWN:")
            lines.append(f"   In specialty: {self.trades_in_specialty} ({specialty_pct:.0f}%)")
            lines.append(f"   Outside specialty: {self.trades_outside_specialty} ({100-specialty_pct:.0f}%)")

        lines.append("=" * 60)
        return "\n".join(lines)


class TimeframeAnalyzer:
    """
    Analyze traders to determine their timeframe specialty

    Looks at:
    1. Which market timeframes they trade most
    2. Win rates by timeframe
    3. Profit by timeframe
    """

    def __init__(self):
        self.trader_stats = defaultdict(lambda: {
            '15min': {'trades': 0, 'wins': 0, 'profit': 0},
            'hourly': {'trades': 0, 'wins': 0, 'profit': 0},
            '4hour': {'trades': 0, 'wins': 0, 'profit': 0},
            'daily': {'trades': 0, 'wins': 0, 'profit': 0}
        })

    def record_trade(self, trader_address: str, market: str, was_win: bool, profit: float):
        """Record a trade for analysis"""
        timeframe = self.detect_timeframe(market)
        stats = self.trader_stats[trader_address.lower()][timeframe]

        stats['trades'] += 1
        if was_win:
            stats['wins'] += 1
        stats['profit'] += profit

    def detect_timeframe(self, market: str) -> str:
        """Detect market timeframe"""
        strategy = MultiTimeframeStrategy()
        return strategy.detect_market_timeframe(market)

    def get_trader_specialty(self, trader_address: str) -> Dict:
        """
        Determine trader's best timeframe

        Returns:
            {
                'specialty': '15min',
                'win_rate': 0.78,
                'trades': 150,
                'profit': 1234.56,
                'all_timeframes': {...}
            }
        """
        stats = self.trader_stats[trader_address.lower()]

        best_timeframe = None
        best_score = 0

        for tf, tf_stats in stats.items():
            trades = tf_stats['trades']
            if trades < 10:  # Need minimum trades
                continue

            win_rate = tf_stats['wins'] / trades
            profit = tf_stats['profit']

            # Score: weighted combination of win rate and profit
            score = (win_rate * 0.6) + (min(profit / 1000, 0.4))  # Cap profit contribution

            if score > best_score:
                best_score = score
                best_timeframe = tf

        if best_timeframe is None:
            best_timeframe = '15min'  # Default

        best_stats = stats[best_timeframe]
        trades = best_stats['trades']
        win_rate = (best_stats['wins'] / trades) if trades > 0 else 0

        return {
            'specialty': best_timeframe,
            'win_rate': win_rate,
            'trades': trades,
            'profit': best_stats['profit'],
            'all_timeframes': dict(stats)
        }

    def analyze_all_traders(self) -> Dict[str, List[Dict]]:
        """
        Analyze all traders and group by specialty

        Returns:
            {
                '15min': [trader1, trader2, ...],
                'hourly': [trader3, trader4, ...],
                ...
            }
        """
        specialists = defaultdict(list)

        for address, _ in self.trader_stats.items():
            specialty = self.get_trader_specialty(address)

            # Only include if they have good performance
            if specialty['win_rate'] >= 0.70 and specialty['trades'] >= 20:
                specialists[specialty['specialty']].append({
                    'address': address,
                    **specialty
                })

        # Sort each list by win rate
        for tf in specialists:
            specialists[tf].sort(key=lambda x: x['win_rate'], reverse=True)

        return dict(specialists)


def create_multi_timeframe_strategy() -> MultiTimeframeStrategy:
    """Factory function to create configured strategy"""
    return MultiTimeframeStrategy()


# Demo
if __name__ == "__main__":
    strategy = MultiTimeframeStrategy()

    # Test market detection
    test_markets = [
        "Will BTC be up in the next 15 minutes?",
        "Will ETH be above $3500 in 1 hour?",
        "Will SOL reach $200 in the next 4 hours?",
        "Will BTC be above $100k by Friday?",
        "BTC 15-min Up",
        "ETH Hourly Price",
    ]

    print("\n🎯 MARKET TIMEFRAME DETECTION TEST")
    print("=" * 60)
    for market in test_markets:
        tf = strategy.detect_market_timeframe(market)
        print(f"{tf:8s} ← {market}")

    # Test tier assignment
    print("\n🐋 TIER CONFIGURATION")
    print("=" * 60)
    for name, tier in strategy.tiers.items():
        print(f"\n{tier.name}:")
        print(f"   Timeframe: {tier.timeframe}")
        print(f"   Base threshold: {tier.base_threshold}%")
        print(f"   Position multiplier: {tier.position_multiplier}x")
        print(f"   Min win rate: {tier.min_win_rate*100:.0f}%")
        print(f"   Max whales: {tier.max_whales if tier.max_whales is not None else 'unlimited'}")
