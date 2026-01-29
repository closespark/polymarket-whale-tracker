"""
Market Lifecycle Tracker

Discovers and tracks active markets from Polymarket Gamma API.
Monitors market lifecycle: opening -> active -> closing -> resolved.

Key features:
1. Poll Gamma API for active markets by timeframe (15min, hourly, etc.)
2. Track market end times and resolution status
3. Provide actual resolution outcomes for P&L calculation
4. Cache market metadata to reduce API calls

This replaces the simulated resolution with real market data.
"""

import asyncio
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from collections import defaultdict
import json
import re

import config


class MarketLifecycle:
    """
    Tracks active markets and their lifecycle states.

    Market States:
    - UPCOMING: Market exists but not yet active for trading
    - ACTIVE: Market is open for trading
    - CLOSING_SOON: Market ends within 5 minutes
    - CLOSED: Market has ended, awaiting resolution
    - RESOLVED: Market outcome is known (YES/NO)
    """

    def __init__(self):
        self.gamma_api = "https://gamma-api.polymarket.com"

        # Active markets by timeframe
        # token_id -> market_data
        self.markets: Dict[str, Dict] = {}

        # Markets by timeframe for quick lookup
        self.markets_by_timeframe: Dict[str, Set[str]] = {
            '15min': set(),
            'hourly': set(),
            '4hour': set(),
            'daily': set(),
            'other': set()
        }

        # Resolution cache: token_id -> {'outcome': 'YES'/'NO', 'resolved_at': datetime}
        self.resolution_cache: Dict[str, Dict] = {}

        # Polling intervals
        self.discovery_interval = 60  # Check for new markets every 60s
        self.resolution_check_interval = 15  # Check resolutions every 15s

        # Stats
        self.markets_discovered = 0
        self.resolutions_fetched = 0
        self.last_discovery = None

        print(f"📊 MarketLifecycle initialized")
        print(f"   Discovery interval: {self.discovery_interval}s")
        print(f"   Resolution check: {self.resolution_check_interval}s")

    async def start(self):
        """Start market discovery and resolution tracking loops"""
        print(f"\n🔄 Starting market lifecycle tracking...")

        # Initial discovery
        await self.discover_active_markets()

        # Start background tasks
        discovery_task = asyncio.create_task(self._discovery_loop())
        resolution_task = asyncio.create_task(self._resolution_loop())

        await asyncio.gather(discovery_task, resolution_task)

    async def _discovery_loop(self):
        """Periodically discover new active markets"""
        while True:
            try:
                await asyncio.sleep(self.discovery_interval)
                await self.discover_active_markets()
            except Exception as e:
                print(f"   ⚠️ Discovery error: {e}")
                await asyncio.sleep(30)

    async def _resolution_loop(self):
        """Check for market resolutions"""
        while True:
            try:
                await asyncio.sleep(self.resolution_check_interval)
                await self.check_resolutions()
            except Exception as e:
                print(f"   ⚠️ Resolution check error: {e}")
                await asyncio.sleep(30)

    async def discover_active_markets(self):
        """
        Fetch active markets from Gamma API

        Looks for markets that:
        - Are currently active (not resolved)
        - Have trading volume (liquid)
        - Match our timeframe patterns (15min, hourly, etc.)
        """
        try:
            # Query active markets
            # The API supports various filters
            url = f"{self.gamma_api}/markets"
            params = {
                'active': 'true',
                'closed': 'false',
                'limit': 100,
                'order': 'volume24hr',
                'ascending': 'false'
            }

            response = requests.get(url, params=params, timeout=15)

            if response.status_code != 200:
                print(f"   ⚠️ Gamma API returned {response.status_code}")
                return

            markets = response.json()

            new_markets = 0
            updated_markets = 0

            for market in markets:
                token_id = market.get('clobTokenIds', [None])[0]
                if not token_id:
                    continue

                # Parse market data
                market_data = self._parse_market(market)
                if not market_data:
                    continue

                # Check if new or updated
                if token_id not in self.markets:
                    new_markets += 1
                    self.markets_discovered += 1
                else:
                    updated_markets += 1

                # Store market
                self.markets[token_id] = market_data

                # Index by timeframe
                timeframe = market_data['timeframe']
                if timeframe in self.markets_by_timeframe:
                    self.markets_by_timeframe[timeframe].add(token_id)
                else:
                    self.markets_by_timeframe['other'].add(token_id)

            self.last_discovery = datetime.now()

            if new_markets > 0:
                print(f"   📊 Discovered {new_markets} new markets, updated {updated_markets}")
                self._print_market_summary()

        except Exception as e:
            print(f"   ⚠️ Market discovery failed: {e}")

    def _parse_market(self, raw_market: Dict) -> Optional[Dict]:
        """Parse raw market data from API into our format"""
        try:
            question = raw_market.get('question', '') or raw_market.get('title', '')

            # Get end date
            end_date_str = raw_market.get('endDate') or raw_market.get('end_date_iso')
            end_date = None
            if end_date_str:
                try:
                    # Handle various date formats
                    if 'T' in end_date_str:
                        end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    else:
                        end_date = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
                except:
                    pass

            # Determine timeframe from question
            timeframe = self._detect_timeframe(question, end_date)

            # Get token IDs
            token_ids = raw_market.get('clobTokenIds', [])

            return {
                'token_id': token_ids[0] if token_ids else None,
                'token_ids': token_ids,  # YES and NO tokens
                'condition_id': raw_market.get('conditionId'),
                'question': question,
                'timeframe': timeframe,
                'end_date': end_date,
                'active': raw_market.get('active', True),
                'closed': raw_market.get('closed', False),
                'resolved': raw_market.get('resolved', False),
                'outcome': raw_market.get('outcome'),
                'volume_24h': raw_market.get('volume24hr', 0),
                'liquidity': raw_market.get('liquidity', 0),
                'last_updated': datetime.now()
            }
        except Exception as e:
            return None

    def _detect_timeframe(self, question: str, end_date: datetime = None) -> str:
        """Detect market timeframe from question text and end date"""
        question_lower = question.lower()

        # 15-minute patterns
        if any(p in question_lower for p in ['15 min', '15min', '15-min', 'next 15']):
            return '15min'

        # Hourly patterns (but not 4 hour)
        if any(p in question_lower for p in ['1 hour', '1hour', 'next hour', 'in an hour', '60 min']):
            if '4' not in question_lower:
                return 'hourly'

        # 4-hour patterns
        if any(p in question_lower for p in ['4 hour', '4hour', '4-hour', 'four hour']):
            return '4hour'

        # Daily patterns
        if any(p in question_lower for p in ['today', 'by eod', 'end of day', '24 hour', 'daily']):
            return 'daily'

        # Try to infer from end date
        if end_date:
            now = datetime.now(end_date.tzinfo) if end_date.tzinfo else datetime.now()
            duration = end_date - now

            if duration <= timedelta(minutes=30):
                return '15min'
            elif duration <= timedelta(hours=2):
                return 'hourly'
            elif duration <= timedelta(hours=6):
                return '4hour'
            elif duration <= timedelta(hours=26):
                return 'daily'

        # Default based on crypto patterns
        if any(p in question_lower for p in ['btc', 'eth', 'sol', 'bitcoin', 'ethereum']):
            if 'above' in question_lower or 'below' in question_lower:
                return '15min'  # Most crypto price markets are 15min

        return 'other'

    async def check_resolutions(self):
        """Check markets that should have resolved"""
        now = datetime.now()
        markets_to_check = []

        for token_id, market in self.markets.items():
            # Skip already resolved
            if market.get('resolved') or token_id in self.resolution_cache:
                continue

            # Check if market should have ended
            end_date = market.get('end_date')
            if end_date:
                # Handle timezone-aware dates
                if end_date.tzinfo:
                    now_tz = datetime.now(end_date.tzinfo)
                else:
                    now_tz = now

                if end_date <= now_tz:
                    markets_to_check.append(token_id)

        if not markets_to_check:
            return

        # Check resolutions (batch to avoid rate limits)
        for token_id in markets_to_check[:10]:  # Max 10 per cycle
            outcome = await self._fetch_resolution(token_id)
            if outcome:
                self.resolution_cache[token_id] = {
                    'outcome': outcome,
                    'resolved_at': datetime.now()
                }
                self.resolutions_fetched += 1

                # Update market record
                if token_id in self.markets:
                    self.markets[token_id]['resolved'] = True
                    self.markets[token_id]['outcome'] = outcome

                print(f"   ✅ Market resolved: {token_id[:16]}... → {outcome}")

    async def _fetch_resolution(self, token_id: str) -> Optional[str]:
        """Fetch resolution outcome from Gamma API"""
        try:
            url = f"{self.gamma_api}/markets"
            params = {'clob_token_ids': token_id}

            response = requests.get(url, params=params, timeout=10)

            if response.status_code != 200:
                return None

            markets = response.json()
            if not markets:
                return None

            market = markets[0]

            # Check if resolved
            resolved = market.get('resolved', False) or market.get('closed', False)
            if not resolved:
                return None

            # Get outcome
            outcome = (
                market.get('outcome') or
                market.get('resolution') or
                market.get('winning_outcome')
            )

            # Check outcomePrices if outcome not directly available
            if not outcome:
                outcomes = market.get('outcomes') or []
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)

                op = market.get('outcomePrices')
                if op:
                    if isinstance(op, str):
                        op = json.loads(op)
                    if isinstance(op, (list, tuple)):
                        for i, p in enumerate(op):
                            if i < len(outcomes):
                                if p == 1 or p == 1.0 or str(p).strip() == "1":
                                    outcome = outcomes[i]
                                    break

            if outcome:
                # Normalize
                if str(outcome).lower() in ['yes', 'true', '1', 'up']:
                    return 'YES'
                elif str(outcome).lower() in ['no', 'false', '0', 'down']:
                    return 'NO'
                else:
                    return str(outcome).upper()

            return None

        except Exception as e:
            return None

    def get_resolution(self, token_id: str) -> Optional[str]:
        """
        Get market resolution outcome.

        Returns 'YES', 'NO', or None if not resolved.
        ALWAYS fetches from API if not in cache - NO SIMULATION.
        """
        # Check cache first
        if token_id in self.resolution_cache:
            return self.resolution_cache[token_id]['outcome']

        # Check market record
        market = self.markets.get(token_id)
        if market and market.get('resolved'):
            return market.get('outcome')

        # NOT IN CACHE - fetch directly from Gamma API
        try:
            url = f"{self.gamma_api}/markets"
            params = {'clob_token_ids': token_id}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                markets = response.json()
                if markets:
                    market_data = markets[0]
                    resolved = market_data.get('resolved', False) or market_data.get('closed', False)
                    if resolved:
                        outcome = (
                            market_data.get('outcome') or
                            market_data.get('resolution') or
                            market_data.get('winning_outcome')
                        )

                        # Check outcomePrices if outcome not directly available
                        if not outcome:
                            outcomes = market_data.get('outcomes') or []
                            if isinstance(outcomes, str):
                                outcomes = json.loads(outcomes)

                            op = market_data.get('outcomePrices')
                            if op:
                                if isinstance(op, str):
                                    op = json.loads(op)
                                if isinstance(op, (list, tuple)):
                                    for i, p in enumerate(op):
                                        if i < len(outcomes):
                                            if p == 1 or p == 1.0 or str(p).strip() == "1":
                                                outcome = outcomes[i]
                                                break

                        if outcome:
                            # Normalize outcome
                            if str(outcome).lower() in ['yes', 'true', '1', 'up']:
                                normalized = 'YES'
                            elif str(outcome).lower() in ['no', 'false', '0', 'down']:
                                normalized = 'NO'
                            else:
                                normalized = str(outcome).upper()

                            # Cache it
                            self.resolution_cache[token_id] = {
                                'outcome': normalized,
                                'resolved_at': datetime.now()
                            }
                            print(f"   ✅ Fetched resolution from API: {normalized}")
                            return normalized
        except Exception as e:
            print(f"   ⚠️ API error fetching resolution for {token_id[:16]}: {e}")

        return None

    def get_active_markets(self, timeframe: str = None) -> List[Dict]:
        """Get list of active markets, optionally filtered by timeframe"""
        now = datetime.now()
        active = []

        for token_id, market in self.markets.items():
            # Skip resolved
            if market.get('resolved') or token_id in self.resolution_cache:
                continue

            # Filter by timeframe if specified
            if timeframe and market.get('timeframe') != timeframe:
                continue

            # Check if still active (not past end date)
            end_date = market.get('end_date')
            if end_date:
                if end_date.tzinfo:
                    now_tz = datetime.now(end_date.tzinfo)
                else:
                    now_tz = now

                if end_date <= now_tz:
                    continue

            active.append(market)

        # Sort by end date (soonest first)
        active.sort(key=lambda m: m.get('end_date') or datetime.max)

        return active

    def get_markets_closing_soon(self, minutes: int = 5) -> List[Dict]:
        """Get markets closing within the specified minutes"""
        now = datetime.now()
        threshold = now + timedelta(minutes=minutes)

        closing_soon = []
        for token_id, market in self.markets.items():
            if market.get('resolved'):
                continue

            end_date = market.get('end_date')
            if end_date:
                if end_date.tzinfo:
                    now_tz = datetime.now(end_date.tzinfo)
                    threshold_tz = now_tz + timedelta(minutes=minutes)
                else:
                    threshold_tz = threshold
                    now_tz = now

                if now_tz < end_date <= threshold_tz:
                    closing_soon.append(market)

        return closing_soon

    def get_market_by_token(self, token_id: str) -> Optional[Dict]:
        """Get market data by token ID"""
        return self.markets.get(token_id)

    def _print_market_summary(self):
        """Print summary of tracked markets"""
        print(f"   Markets by timeframe:")
        for tf, tokens in self.markets_by_timeframe.items():
            if tokens:
                print(f"      {tf}: {len(tokens)} markets")

    def get_stats(self) -> Dict:
        """Get lifecycle tracker statistics"""
        return {
            'total_markets': len(self.markets),
            'markets_by_timeframe': {tf: len(tokens) for tf, tokens in self.markets_by_timeframe.items()},
            'resolutions_cached': len(self.resolution_cache),
            'markets_discovered': self.markets_discovered,
            'resolutions_fetched': self.resolutions_fetched,
            'last_discovery': self.last_discovery.isoformat() if self.last_discovery else None
        }


# Singleton instance
_lifecycle = None


def get_market_lifecycle() -> MarketLifecycle:
    """Get or create the MarketLifecycle singleton"""
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = MarketLifecycle()
    return _lifecycle
