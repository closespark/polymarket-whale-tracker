"""
Real-Time Whale Monitor
Watches profitable wallets and alerts when they make trades
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

init(autoreset=True)  # Initialize colorama


class WhaleMonitor:
    """Monitor specific whale wallets in real-time"""
    
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
        
        print(f"{Fore.GREEN}✅ Whale Monitor initialized")
        print(f"   Watching {len(self.whales)} whale wallets")
        print(f"   Starting at block: {self.last_block_checked:,}")
    
    async def start_monitoring(self, callback=None):
        """
        Start monitoring whales in real-time
        
        Args:
            callback: Optional async function to call when whale trade detected
                     Signature: async def callback(trade_data)
        """
        
        print(f"\n{Fore.CYAN}{'='*80}")
        print(f"{Fore.CYAN}🔍 REAL-TIME WHALE MONITORING ACTIVE")
        print(f"{Fore.CYAN}{'='*80}\n")
        
        while True:
            try:
                current_block = self.w3.eth.block_number
                
                if current_block > self.last_block_checked:
                    # Check new blocks
                    await self._check_new_blocks(
                        self.last_block_checked + 1,
                        current_block,
                        callback
                    )
                    self.last_block_checked = current_block
                
                # Wait before checking again
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)
                
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}⚠️  Monitoring stopped by user")
                break
            except Exception as e:
                print(f"{Fore.RED}❌ Error in monitoring loop: {e}")
                await asyncio.sleep(5)
    
    async def _check_new_blocks(self, from_block, to_block, callback):
        """Check blocks for whale activity"""
        
        try:
            # Get all OrderFilled events in range
            events = self.ctf_exchange.events.OrderFilled.get_logs(
                from_block=from_block,
                to_block=to_block
            )
            
            # Filter for whale trades
            for event in events:
                maker = event['args']['maker']
                taker = event['args']['taker']
                
                whale_address = None
                whale_side = None
                
                if maker in self.whales:
                    whale_address = maker
                    whale_side = 'SELL'
                elif taker in self.whales:
                    whale_address = taker
                    whale_side = 'BUY'
                
                if whale_address:
                    trade_data = await self._parse_whale_trade(
                        event,
                        whale_address,
                        whale_side
                    )
                    
                    # Alert
                    self._print_whale_alert(trade_data)
                    
                    # Call callback if provided
                    if callback:
                        await callback(trade_data)
        
        except Exception as e:
            print(f"{Fore.RED}Error checking blocks: {e}")
    
    async def _parse_whale_trade(self, event, whale_address, side):
        """Parse trade event into structured data"""
        
        token_id = event['args']['tokenId']
        maker_amount = event['args']['makerAmount']
        taker_amount = event['args']['takerAmount']
        block_number = event['blockNumber']
        tx_hash = event['transactionHash'].hex()
        
        # Calculate price
        if side == 'BUY':
            amount = taker_amount / 1e6  # USDC has 6 decimals
            price = (maker_amount / taker_amount) if taker_amount > 0 else 0
            usdc_value = maker_amount / 1e6
        else:  # SELL
            amount = maker_amount / 1e6
            price = (taker_amount / maker_amount) if maker_amount > 0 else 0
            usdc_value = taker_amount / 1e6
        
        # Get market info from Polymarket API
        market_info = await self._get_market_info(token_id)
        
        # Get block timestamp
        block = self.w3.eth.get_block(block_number)
        timestamp = datetime.fromtimestamp(block['timestamp'])
        
        return {
            'whale_address': whale_address,
            'side': side,
            'token_id': str(token_id),
            'amount': amount,
            'price': price,
            'usdc_value': usdc_value,
            'market_question': market_info.get('question', 'Unknown'),
            'market_id': market_info.get('market_id', 'Unknown'),
            'block_number': block_number,
            'tx_hash': tx_hash,
            'timestamp': timestamp
        }
    
    async def _get_market_info(self, token_id):
        """Get market information from Polymarket API"""
        
        # This is simplified - in reality need to map token_id to market
        # For now, return placeholder
        
        return {
            'question': f'Market for token {token_id}',
            'market_id': 'unknown'
        }
    
    def _print_whale_alert(self, trade):
        """Print colorful alert for whale trade"""
        
        # Color based on side
        color = Fore.GREEN if trade['side'] == 'BUY' else Fore.RED
        
        print(f"\n{color}{'='*80}")
        print(f"{color}🐋 WHALE TRADE DETECTED!")
        print(f"{color}{'='*80}")
        print(f"{Fore.WHITE}Time: {trade['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{Fore.WHITE}Whale: {trade['whale_address'][:10]}...{trade['whale_address'][-8:]}")
        print(f"{color}Side: {trade['side']}")
        print(f"{Fore.WHITE}Market: {trade['market_question']}")
        print(f"{Fore.YELLOW}Price: ${trade['price']:.4f}")
        print(f"{Fore.YELLOW}Amount: {trade['amount']:.2f} tokens")
        print(f"{Fore.YELLOW}Value: ${trade['usdc_value']:.2f}")
        print(f"{Fore.CYAN}Block: {trade['block_number']:,}")
        print(f"{Fore.CYAN}TX: {trade['tx_hash']}")
        print(f"{color}{'='*80}\n")
    
    def get_whale_stats(self, whale_address):
        """Get current statistics for a whale"""
        
        # This would query database or on-chain data
        # For now, return placeholder
        
        return {
            'address': whale_address,
            'total_profit': 0,
            'win_rate': 0,
            'trade_count': 0
        }


async def example_callback(trade_data):
    """Example callback function for trade alerts"""
    
    print(f"{Fore.MAGENTA}📢 Callback triggered for whale trade!")
    print(f"{Fore.MAGENTA}   Consider copying this trade...")
    
    # Here you would:
    # 1. Analyze the trade
    # 2. Check confidence score
    # 3. Execute copy trade if criteria met
    
    # Example:
    if trade_data['usdc_value'] > 1000:  # Large trade
        print(f"{Fore.MAGENTA}   ⚠️  LARGE TRADE: Consider high confidence")


async def main():
    """Main monitoring function"""
    
    # Example whale addresses (replace with real ones from analyzer)
    example_whales = [
        '0x0000000000000000000000000000000000000001',  # Replace with real
        '0x0000000000000000000000000000000000000002',  # Replace with real
    ]
    
    print(f"{Fore.YELLOW}⚠️  Using example addresses - replace with real whales!")
    print(f"{Fore.YELLOW}   Run whale_analyzer.py first to find profitable wallets\n")
    
    monitor = WhaleMonitor(example_whales)
    
    # Start monitoring with callback
    await monitor.start_monitoring(callback=example_callback)


if __name__ == "__main__":
    asyncio.run(main())
