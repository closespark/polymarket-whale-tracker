"""
15-Minute Market Whale Analyzer
Specialized for finding profitable traders in 15-minute prediction markets
"""

from web3 import Web3
try:
    from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
except ImportError:
    from web3.middleware import geth_poa_middleware
import requests
import json
from datetime import datetime, timedelta
from collections import defaultdict
from tqdm import tqdm
import pandas as pd

import config


class FifteenMinuteWhaleAnalyzer:
    """
    Specialized analyzer for 15-minute prediction markets

    These markets resolve every 15 minutes (BTC/ETH/SPY price predictions)
    and offer high-frequency trading opportunities.
    """

    def __init__(self):
        # Connect to Polygon
        self.w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        if not self.w3.is_connected():
            print("Failed to connect to Polygon RPC, trying backup...")
            for backup_rpc in config.POLYGON_RPC_BACKUP:
                self.w3 = Web3(Web3.HTTPProvider(backup_rpc))
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                if self.w3.is_connected():
                    print(f"Connected to backup RPC: {backup_rpc}")
                    break

        # Load CTF Exchange contract
        self.ctf_exchange = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.CTFEXCHANGE_ADDRESS),
            abi=config.CTFEXCHANGE_ABI
        )

        print(f"Connected to Polygon: Block {self.w3.eth.block_number:,}")

        # Cache for 15-minute market identification
        self.fifteen_min_markets = set()
        self.trader_stats = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_volume': 0,
            'first_trade_block': None,
            'last_trade_block': None
        })

    def find_fifteen_minute_specialists(self, blocks_to_scan=50000):
        """
        Find traders who specialize in 15-minute markets

        Args:
            blocks_to_scan: Number of blocks to analyze

        Returns:
            List of specialist traders sorted by performance
        """

        print(f"\nScanning last {blocks_to_scan:,} blocks for 15-min specialists...")

        current_block = self.w3.eth.block_number
        start_block = current_block - blocks_to_scan

        # Get all OrderFilled events
        events = self._get_events_in_chunks(start_block, current_block)

        print(f"Found {len(events)} total trades")

        # Analyze each trader
        self._analyze_traders(events)

        # Calculate metrics and rank specialists
        specialists = self._rank_specialists()

        print(f"Found {len(specialists)} 15-minute specialists")

        return specialists

    def _get_events_in_chunks(self, from_block, to_block, chunk_size=1000):
        """Get OrderFilled events in chunks to avoid RPC limits"""
        import json

        all_events = []
        current_from = from_block
        total_blocks = to_block - from_block

        progress_bar = tqdm(total=total_blocks, desc="Scanning blocks")

        while current_from < to_block:
            current_to = min(current_from + chunk_size, to_block)

            try:
                events = self.ctf_exchange.events.OrderFilled.get_logs(
                    from_block=current_from,
                    to_block=current_to
                )
                all_events.extend(events)
            except Exception as e:
                print(f"\nError fetching blocks {current_from}-{current_to}: {e}")
                if chunk_size > 1000:
                    chunk_size = chunk_size // 2
                    continue

            progress_bar.update(current_to - current_from)
            current_from = current_to + 1

            # Write progress to file for dashboard
            blocks_done = current_from - from_block
            progress_pct = (blocks_done / total_blocks) * 100
            try:
                with open('scan_progress.json', 'w') as f:
                    json.dump({
                        'blocks_scanned': blocks_done,
                        'total_blocks': total_blocks,
                        'progress_percent': round(progress_pct, 1),
                        'events_found': len(all_events),
                        'status': 'scanning'
                    }, f)
            except:
                pass

        progress_bar.close()

        # Mark scan complete
        try:
            with open('scan_progress.json', 'w') as f:
                json.dump({
                    'blocks_scanned': total_blocks,
                    'total_blocks': total_blocks,
                    'progress_percent': 100,
                    'events_found': len(all_events),
                    'status': 'complete'
                }, f)
        except:
            pass

        return all_events

    def _analyze_traders(self, events):
        """Analyze all traders from events"""

        for event in tqdm(events, desc="Analyzing traders"):
            maker = event['args']['maker']
            taker = event['args']['taker']
            # Use correct field names from ABI: makerAmountFilled, takerAmountFilled
            maker_amount = event['args']['makerAmountFilled']
            taker_amount = event['args']['takerAmountFilled']
            block_number = event['blockNumber']

            # Update maker stats
            self._update_trader_stats(maker, 'SELL', maker_amount, taker_amount, block_number)

            # Update taker stats
            self._update_trader_stats(taker, 'BUY', taker_amount, maker_amount, block_number)

    def _update_trader_stats(self, address, trade_type, token_amount, usdc_amount, block):
        """Update stats for a trader"""

        stats = self.trader_stats[address]

        # Track trade
        stats['trades'].append({
            'type': trade_type,
            'token_amount': token_amount,
            'usdc_amount': usdc_amount,
            'block': block,
            'price': usdc_amount / token_amount if token_amount > 0 else 0
        })

        # Update volume (convert from wei to USDC)
        stats['total_volume'] += usdc_amount / 1e6

        # Track first/last block
        if stats['first_trade_block'] is None or block < stats['first_trade_block']:
            stats['first_trade_block'] = block
        if stats['last_trade_block'] is None or block > stats['last_trade_block']:
            stats['last_trade_block'] = block

        # Simple win estimation (buys below 0.5 or sells above 0.5 are typically good)
        price = usdc_amount / token_amount if token_amount > 0 else 0.5
        if trade_type == 'BUY' and price < 0.45:
            stats['wins'] += 1
        elif trade_type == 'SELL' and price > 0.55:
            stats['wins'] += 1
        elif trade_type == 'BUY' and price > 0.75:
            stats['losses'] += 1
        elif trade_type == 'SELL' and price < 0.25:
            stats['losses'] += 1

    def _rank_specialists(self):
        """Rank traders by their 15-minute market performance"""

        specialists = []

        for address, stats in self.trader_stats.items():
            trade_count = len(stats['trades'])

            # Need minimum trades
            if trade_count < 10:
                continue

            # Calculate metrics
            total_trades = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total_trades if total_trades > 0 else 0.5

            # Calculate trading frequency (trades per block range)
            if stats['first_trade_block'] and stats['last_trade_block']:
                block_range = stats['last_trade_block'] - stats['first_trade_block']
                if block_range > 0:
                    trades_per_block = trade_count / block_range
                else:
                    trades_per_block = trade_count
            else:
                trades_per_block = 0

            # Estimate profit (simplified)
            # Real implementation would track actual position P&L
            estimated_profit = stats['total_volume'] * (win_rate - 0.5) * 0.3

            # Speed score: how quickly they enter after market opens
            # Higher trades_per_block = faster/more active trader
            speed_score = min(trades_per_block * 1000, 1.0)

            # Markets traded (unique token IDs)
            unique_markets = len(set(t.get('token_id', i) for i, t in enumerate(stats['trades'])))

            specialists.append({
                'address': address,
                'trade_count': trade_count,
                'estimated_profit': estimated_profit,
                'estimated_win_rate': win_rate,
                'markets_traded': unique_markets,
                'speed_score': speed_score,
                'total_volume': stats['total_volume'],
                'first_block': stats['first_trade_block'],
                'last_block': stats['last_trade_block']
            })

        # Sort by estimated profit
        specialists.sort(key=lambda x: x['estimated_profit'], reverse=True)

        return specialists

    def export_specialists(self, specialists, filename='fifteen_min_specialists.csv'):
        """Export specialists to CSV"""

        df = pd.DataFrame(specialists)
        df.to_csv(filename, index=False)
        print(f"Saved {len(specialists)} specialists to {filename}")

        return df


if __name__ == "__main__":
    print("=" * 80)
    print("15-MINUTE MARKET WHALE ANALYZER")
    print("=" * 80)

    analyzer = FifteenMinuteWhaleAnalyzer()

    # Find specialists in last ~1 week of blocks
    specialists = analyzer.find_fifteen_minute_specialists(blocks_to_scan=50000)

    # Print top 10
    print("\nTOP 10 15-MINUTE SPECIALISTS:")
    print("-" * 80)

    for i, spec in enumerate(specialists[:10], 1):
        print(f"#{i} {spec['address'][:10]}...{spec['address'][-6:]}")
        print(f"    Trades: {spec['trade_count']:,}")
        print(f"    Est. Profit: ${spec['estimated_profit']:,.2f}")
        print(f"    Win Rate: {spec['estimated_win_rate']*100:.1f}%")
        print(f"    Speed Score: {spec['speed_score']:.2f}")
        print()

    # Export
    analyzer.export_specialists(specialists)

    print("Analysis complete!")
