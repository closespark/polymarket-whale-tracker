"""
15-Minute Market Monitor
Real-time monitoring of whale activity in 15-minute prediction markets
"""

from web3 import Web3
try:
    from web3.middleware import ExtraDataToPOAMiddleware as geth_poa_middleware
except ImportError:
    from web3.middleware import geth_poa_middleware
import asyncio
import json
from datetime import datetime
from colorama import Fore, Style, init

import config

init(autoreset=True)


class FifteenMinuteMonitor:
    """Monitor whale activity in 15-minute markets in real-time"""

    def __init__(self, whale_addresses):
        """
        Initialize monitor with list of whale addresses to watch

        Args:
            whale_addresses: List of wallet addresses to monitor
        """
        self.whales = [Web3.to_checksum_address(addr) for addr in whale_addresses]

        # Connect to Polygon
        self.w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # Load contract
        self.ctf_exchange = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.CTFEXCHANGE_ADDRESS),
            abi=config.CTFEXCHANGE_ABI
        )

        self.last_block_checked = self.w3.eth.block_number

        print(f"{Fore.GREEN}15-Min Monitor initialized")
        print(f"   Watching {len(self.whales)} whale wallets")
        print(f"   Starting at block: {self.last_block_checked:,}")

    async def start_monitoring(self, callback=None):
        """
        Start monitoring whales in real-time

        Args:
            callback: Async function to call when whale trade detected
        """

        print(f"\n{Fore.CYAN}Starting 15-minute market monitor...")
        print(f"   Scan interval: {config.SCAN_INTERVAL_SECONDS} seconds")

        while True:
            try:
                await self.check_new_trades(callback)
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

            except Exception as e:
                print(f"{Fore.RED}Monitor error: {e}")
                await asyncio.sleep(10)

    async def check_new_trades(self, callback=None):
        """Check for new whale trades since last check"""

        current_block = self.w3.eth.block_number

        if current_block <= self.last_block_checked:
            return

        try:
            # Get all OrderFilled events in range
            events = self.ctf_exchange.events.OrderFilled.get_logs(
                from_block=self.last_block_checked + 1,
                to_block=current_block
            )

            # Filter for whale trades
            whale_trades = []

            for event in events:
                maker = event['args']['maker']
                taker = event['args']['taker']

                if maker in self.whales or taker in self.whales:
                    # Determine if whale is buying or selling
                    if maker in self.whales:
                        whale_address = maker
                        side = 'SELL'
                        usdc_received = event['args']['takerAmount']
                        tokens_sold = event['args']['makerAmount']
                    else:
                        whale_address = taker
                        side = 'BUY'
                        usdc_spent = event['args']['makerAmount']
                        tokens_bought = event['args']['takerAmount']

                    trade_data = {
                        'whale_address': whale_address,
                        'side': side,
                        'token_id': str(event['args'].get('tokenId', '')),
                        'block_number': event['blockNumber'],
                        'tx_hash': event['transactionHash'].hex(),
                        'timestamp': datetime.now().isoformat(),
                        'copied': False
                    }

                    if side == 'BUY':
                        trade_data['usdc_value'] = usdc_spent / 1e6
                        trade_data['token_amount'] = tokens_bought / 1e6
                        trade_data['price'] = usdc_spent / tokens_bought if tokens_bought > 0 else 0
                    else:
                        trade_data['usdc_value'] = usdc_received / 1e6
                        trade_data['token_amount'] = tokens_sold / 1e6
                        trade_data['price'] = usdc_received / tokens_sold if tokens_sold > 0 else 0

                    # Try to get market info
                    trade_data['market_question'] = await self._get_market_question(
                        trade_data['token_id']
                    )

                    whale_trades.append(trade_data)

            # Process whale trades
            for trade in whale_trades:
                await self._process_whale_trade(trade, callback)

            self.last_block_checked = current_block

        except Exception as e:
            print(f"{Fore.RED}Error checking trades: {e}")

    async def _process_whale_trade(self, trade_data, callback=None):
        """Process a detected whale trade"""

        print(f"\n{Fore.YELLOW}{'='*60}")
        print(f"{Fore.YELLOW}WHALE TRADE DETECTED")
        print(f"{'='*60}")
        print(f"{Fore.WHITE}Whale: {trade_data['whale_address'][:10]}...{trade_data['whale_address'][-6:]}")
        print(f"{Fore.WHITE}Side: {Fore.GREEN if trade_data['side'] == 'BUY' else Fore.RED}{trade_data['side']}")
        print(f"{Fore.WHITE}Size: ${trade_data['usdc_value']:.2f}")
        print(f"{Fore.WHITE}Price: ${trade_data['price']:.4f}")

        if trade_data.get('market_question'):
            print(f"{Fore.WHITE}Market: {trade_data['market_question'][:50]}...")

        print(f"{'='*60}\n")

        # Call callback if provided
        if callback:
            await callback(trade_data)

    async def _get_market_question(self, token_id):
        """Get market question for a token ID"""

        try:
            import requests
            # Try to get from Polymarket API
            response = requests.get(
                f"{config.POLYMARKET_API_BASE}/markets",
                timeout=5
            )

            if response.status_code == 200:
                markets = response.json()
                # Search for matching token
                for market in markets:
                    if str(market.get('conditionId', '')) == token_id:
                        return market.get('question', 'Unknown market')

            return 'Unknown market'

        except Exception:
            return 'Unknown market'


if __name__ == "__main__":
    # Test with some sample whale addresses
    test_whales = [
        "0x0000000000000000000000000000000000000001",  # Placeholder
    ]

    async def test_callback(trade):
        print(f"Callback received trade: {trade['whale_address'][:10]}...")

    async def main():
        monitor = FifteenMinuteMonitor(test_whales)
        await monitor.start_monitoring(callback=test_callback)

    asyncio.run(main())
