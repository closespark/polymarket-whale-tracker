"""
On-Chain Whale Analyzer for Polymarket
Analyzes Polygon blockchain to find profitable traders
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

class PolymarketWhaleAnalyzer:
    """Analyzes on-chain data to find profitable Polymarket traders"""
    
    def __init__(self):
        # Connect to Polygon
        self.w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        if not self.w3.is_connected():
            print("❌ Failed to connect to Polygon RPC, trying backup...")
            for backup_rpc in config.POLYGON_RPC_BACKUP:
                self.w3 = Web3(Web3.HTTPProvider(backup_rpc))
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                if self.w3.is_connected():
                    print(f"✅ Connected to backup RPC: {backup_rpc}")
                    break
        
        # Load contracts
        self.ctf_exchange = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.CTFEXCHANGE_ADDRESS),
            abi=config.CTFEXCHANGE_ABI
        )
        
        self.conditional_tokens = self.w3.eth.contract(
            address=Web3.to_checksum_address(config.CONDITIONAL_TOKENS_ADDRESS),
            abi=config.CONDITIONAL_TOKENS_ABI
        )
        
        print(f"✅ Connected to Polygon: Block {self.w3.eth.block_number:,}")
        
        # Cache for market resolutions
        self.market_resolutions = {}
        self.token_id_to_market = {}
    
    def analyze_historical_trades(self, blocks_to_scan=50000):
        """
        Scan historical blocks to find all trades and calculate trader performance
        
        Args:
            blocks_to_scan: Number of recent blocks to analyze (default: 50000 ≈ 1 week)
        
        Returns:
            List of profitable traders sorted by performance
        """
        
        print(f"\n🔍 Scanning last {blocks_to_scan:,} blocks for trades...")
        
        current_block = self.w3.eth.block_number
        start_block = current_block - blocks_to_scan
        
        # Get all OrderFilled events from CTF Exchange
        print("   Fetching OrderFilled events...")
        
        order_filled_events = self._get_events_in_chunks(
            self.ctf_exchange.events.OrderFilled,
            start_block,
            current_block
        )
        
        print(f"   Found {len(order_filled_events)} trades")
        
        # Analyze each trader's performance
        print("   Analyzing trader performance...")
        trader_stats = self._analyze_trader_performance(order_filled_events)
        
        # Calculate profitability
        print("   Calculating profitability...")
        profitable_traders = self._calculate_profitability(trader_stats)
        
        # Filter by criteria
        whales = [
            t for t in profitable_traders
            if t['profit'] >= config.MIN_WHALE_PROFIT
            and t['win_rate'] >= config.MIN_WHALE_WIN_RATE
            and t['trade_count'] >= config.MIN_WHALE_TRADES
        ]
        
        print(f"\n✅ Found {len(whales)} profitable whales!")
        
        return whales
    
    def _get_events_in_chunks(self, event, from_block, to_block, chunk_size=5000):
        """Get events in chunks to avoid RPC limits"""
        
        all_events = []
        current_from = from_block
        
        progress_bar = tqdm(total=to_block-from_block, desc="Scanning blocks")
        
        while current_from < to_block:
            current_to = min(current_from + chunk_size, to_block)
            
            try:
                events = event.get_logs(from_block=current_from, to_block=current_to)
                all_events.extend(events)
            except Exception as e:
                print(f"\n⚠️  Error fetching blocks {current_from}-{current_to}: {e}")
                # Retry with smaller chunk
                if chunk_size > 1000:
                    chunk_size = chunk_size // 2
                    continue
            
            progress_bar.update(current_to - current_from)
            current_from = current_to + 1
        
        progress_bar.close()
        return all_events
    
    def _analyze_trader_performance(self, events):
        """Analyze each trader's trades"""
        
        trader_data = defaultdict(lambda: {
            'trades': [],
            'total_spent': 0,
            'total_received': 0,
            'tokens_held': defaultdict(int)
        })
        
        for event in tqdm(events, desc="Processing trades"):
            maker = event['args']['maker']
            taker = event['args']['taker']
            token_id = event['args']['tokenId']
            maker_amount = event['args']['makerAmount']
            taker_amount = event['args']['takerAmount']
            block_number = event['blockNumber']
            
            # Maker is selling tokens for USDC
            trader_data[maker]['trades'].append({
                'type': 'SELL',
                'token_id': token_id,
                'amount': maker_amount,
                'usdc': taker_amount,
                'block': block_number,
                'price': taker_amount / maker_amount if maker_amount > 0 else 0
            })
            trader_data[maker]['total_received'] += taker_amount
            trader_data[maker]['tokens_held'][token_id] -= maker_amount
            
            # Taker is buying tokens with USDC
            trader_data[taker]['trades'].append({
                'type': 'BUY',
                'token_id': token_id,
                'amount': taker_amount,
                'usdc': maker_amount,
                'block': block_number,
                'price': maker_amount / taker_amount if taker_amount > 0 else 0
            })
            trader_data[taker]['total_spent'] += maker_amount
            trader_data[taker]['tokens_held'][token_id] += taker_amount
        
        return trader_data
    
    def _calculate_profitability(self, trader_data):
        """Calculate profit for each trader"""
        
        profitable_traders = []
        
        for address, data in tqdm(trader_data.items(), desc="Calculating profits"):
            if len(data['trades']) < config.MIN_WHALE_TRADES:
                continue
            
            # Get current value of held tokens
            current_value = self._estimate_portfolio_value(data['tokens_held'])
            
            # Calculate realized profit
            realized_profit = data['total_received'] - data['total_spent']
            
            # Calculate unrealized profit (current holdings)
            unrealized_profit = current_value - sum(
                trade['usdc'] for trade in data['trades'] if trade['type'] == 'BUY'
            )
            
            total_profit = realized_profit + unrealized_profit
            
            # Calculate win rate (simplified)
            winning_trades = sum(
                1 for trade in data['trades']
                if self._is_winning_trade(trade, data['tokens_held'])
            )
            win_rate = winning_trades / len(data['trades']) if data['trades'] else 0
            
            # Calculate ROI
            total_invested = data['total_spent']
            roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            profitable_traders.append({
                'address': address,
                'profit': total_profit / 1e6,  # Convert from USDC (6 decimals)
                'roi': roi,
                'win_rate': win_rate,
                'trade_count': len(data['trades']),
                'total_volume': (data['total_spent'] + data['total_received']) / 1e6,
                'tokens_held': dict(data['tokens_held'])
            })
        
        # Sort by profit
        profitable_traders.sort(key=lambda x: x['profit'], reverse=True)
        
        return profitable_traders
    
    def _estimate_portfolio_value(self, tokens_held):
        """Estimate current value of held tokens using Polymarket API"""
        
        total_value = 0
        
        for token_id, amount in tokens_held.items():
            if amount <= 0:
                continue
            
            # Get current price from Polymarket API
            try:
                price = self._get_token_price(token_id)
                total_value += amount * price
            except:
                # If can't get price, assume 0.5 (middle)
                total_value += amount * 0.5
        
        return total_value
    
    def _get_token_price(self, token_id):
        """Get current price for a token from Polymarket API"""
        
        # Cache to avoid repeated API calls
        if token_id in self.token_id_to_market:
            market_id = self.token_id_to_market[token_id]
        else:
            # Need to map token_id to market (simplified)
            return 0.5  # Default to middle price
        
        try:
            response = requests.get(f"{config.POLYMARKET_API_BASE}/markets/{market_id}")
            market = response.json()
            return market.get('last_price', 0.5)
        except:
            return 0.5
    
    def _is_winning_trade(self, trade, current_holdings):
        """Determine if a trade was profitable (simplified)"""
        
        # This is a simplified heuristic
        # In reality, need to track each position through resolution
        
        if trade['type'] == 'BUY':
            # If still holding, check current price
            token_id = trade['token_id']
            if token_id in current_holdings and current_holdings[token_id] > 0:
                current_price = self._get_token_price(token_id)
                return current_price > trade['price']
            else:
                # Position closed - assume won if sold
                return True
        else:  # SELL
            # Simplified: assume sales are profitable
            return trade['price'] > 0.5
    
    def get_whale_recent_activity(self, whale_address, last_n_blocks=10000):
        """Get recent trading activity for a specific whale"""
        
        current_block = self.w3.eth.block_number
        start_block = current_block - last_n_blocks
        
        checksum_address = Web3.to_checksum_address(whale_address)
        
        # Get events where whale was maker or taker
        events = []
        
        try:
            maker_events = self.ctf_exchange.events.OrderFilled.get_logs(
                from_block=start_block,
                to_block=current_block,
                argument_filters={'maker': checksum_address}
            )
            events.extend(maker_events)

            taker_events = self.ctf_exchange.events.OrderFilled.get_logs(
                from_block=start_block,
                to_block=current_block,
                argument_filters={'taker': checksum_address}
            )
            events.extend(taker_events)
        except Exception as e:
            print(f"Error fetching whale activity: {e}")
            return []
        
        # Sort by block number
        events.sort(key=lambda x: x['blockNumber'], reverse=True)
        
        return events[:20]  # Return last 20 trades
    
    def export_whales_to_csv(self, whales, filename='profitable_whales.csv'):
        """Export whale data to CSV"""
        
        df = pd.DataFrame(whales)
        df.to_csv(filename, index=False)
        print(f"\n💾 Saved {len(whales)} whales to {filename}")
    
    def print_whale_summary(self, whales, top_n=10):
        """Print summary of top whales"""
        
        print(f"\n{'='*80}")
        print(f"🐋 TOP {top_n} POLYMARKET WHALES")
        print(f"{'='*80}\n")
        
        for i, whale in enumerate(whales[:top_n], 1):
            print(f"#{i} {whale['address'][:10]}...{whale['address'][-8:]}")
            print(f"   💰 Profit: ${whale['profit']:,.2f}")
            print(f"   📈 ROI: {whale['roi']:.1f}%")
            print(f"   🎯 Win Rate: {whale['win_rate']*100:.1f}%")
            print(f"   📊 Trades: {whale['trade_count']:,}")
            print(f"   💵 Volume: ${whale['total_volume']:,.2f}")
            print()


if __name__ == "__main__":
    # Test the analyzer
    print("🚀 Starting Polymarket Whale Analyzer\n")
    
    analyzer = PolymarketWhaleAnalyzer()
    
    # Analyze last 50,000 blocks (~ 1 week on Polygon)
    whales = analyzer.analyze_historical_trades(blocks_to_scan=50000)
    
    # Print summary
    analyzer.print_whale_summary(whales)
    
    # Export to CSV
    analyzer.export_whales_to_csv(whales)
    
    print("\n✅ Analysis complete!")
