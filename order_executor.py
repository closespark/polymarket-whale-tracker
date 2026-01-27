"""
Order Executor - Handles actual order placement on Polymarket CLOB

This module is responsible for:
1. Building order parameters
2. Fetching nonces
3. Signing and submitting orders
4. Verifying fills
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, Tuple
import requests

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
from py_clob_client.order_builder.constants import BUY, SELL

import config


class OrderExecutor:
    """
    Executes orders on Polymarket CLOB

    Handles the full order lifecycle:
    - Market price lookup
    - Order building and signing
    - Submission and confirmation
    """

    def __init__(self):
        self.client = None
        self.initialized = False
        self.gamma_api = "https://gamma-api.polymarket.com"

        # Order settings
        self.max_slippage = 0.02  # 2% max slippage from detected price
        self.order_timeout = 30  # seconds to wait for fill

        self._initialize_client()

    def _initialize_client(self):
        """Initialize the CLOB client with credentials"""
        try:
            # Check for required credentials
            if not all([
                config.POLYMARKET_API_KEY,
                config.POLYMARKET_SECRET,
                config.POLYMARKET_PASSPHRASE,
                config.PRIVATE_KEY,
                config.FUNDER_ADDRESS
            ]):
                print("⚠️ OrderExecutor: Missing API credentials")
                print("   Set POLYMARKET_API_KEY, SECRET, PASSPHRASE, PRIVATE_KEY, FUNDER_ADDRESS")
                return

            creds = ApiCreds(
                api_key=config.POLYMARKET_API_KEY,
                api_secret=config.POLYMARKET_SECRET,
                api_passphrase=config.POLYMARKET_PASSPHRASE
            )

            self.client = ClobClient(
                host=config.POLYMARKET_CLOB_API,
                key=config.PRIVATE_KEY,
                chain_id=137,  # Polygon mainnet
                signature_type=config.SIGNATURE_TYPE,
                funder=config.FUNDER_ADDRESS,
                creds=creds
            )

            self.initialized = True
            print(f"✅ OrderExecutor initialized")
            print(f"   Funder: {config.FUNDER_ADDRESS[:10]}...")

        except Exception as e:
            print(f"❌ OrderExecutor init failed: {e}")
            self.initialized = False

    def get_market_info(self, token_id: str) -> Optional[Dict]:
        """
        Get market info from Gamma API

        Returns:
            Market data including question, end_date, condition_id
        """
        try:
            url = f"{self.gamma_api}/markets?clob_token_ids={token_id}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                markets = response.json()
                if markets and len(markets) > 0:
                    return markets[0]

            return None

        except Exception as e:
            print(f"   ⚠️ Failed to get market info: {e}")
            return None

    def get_order_book_price(self, token_id: str, side: str) -> Optional[float]:
        """
        Get best price from order book

        For BUY: Get best ask (lowest sell price)
        For SELL: Get best bid (highest buy price)

        Returns:
            Best available price, or None if unavailable
        """
        try:
            # Get order book from CLOB
            book = self.client.get_order_book(token_id)

            if side == 'BUY':
                # Best ask is the lowest price someone is selling at
                asks = book.get('asks', [])
                if asks:
                    return float(asks[0]['price'])
            else:
                # Best bid is the highest price someone is buying at
                bids = book.get('bids', [])
                if bids:
                    return float(bids[0]['price'])

            return None

        except Exception as e:
            print(f"   ⚠️ Failed to get order book: {e}")
            return None

    async def place_order(
        self,
        token_id: str,
        side: str,
        usdc_amount: float,
        whale_price: float = None
    ) -> Dict:
        """
        Place an order on the CLOB

        Args:
            token_id: The outcome token to trade
            side: 'BUY' or 'SELL'
            usdc_amount: Amount in USDC to spend
            whale_price: Price the whale traded at (for reference)

        Returns:
            Dict with order details and status
        """
        if not self.initialized:
            return {
                'success': False,
                'error': 'OrderExecutor not initialized',
                'order_id': None
            }

        try:
            # Get current market price
            current_price = self.get_order_book_price(token_id, side)

            if current_price is None:
                # Fall back to whale's price with slippage
                if whale_price:
                    current_price = whale_price * (1 + self.max_slippage if side == 'BUY' else 1 - self.max_slippage)
                else:
                    return {
                        'success': False,
                        'error': 'Could not determine price',
                        'order_id': None
                    }

            # Calculate quantity
            quantity = usdc_amount / current_price

            # Build order
            order_side = BUY if side == 'BUY' else SELL

            print(f"\n📝 Building order:")
            print(f"   Token: {token_id[:16]}...")
            print(f"   Side: {side}")
            print(f"   Price: ${current_price:.4f}")
            print(f"   Quantity: {quantity:.2f} tokens")
            print(f"   Total: ${usdc_amount:.2f}")

            # Create order args
            order_args = OrderArgs(
                token_id=token_id,
                price=current_price,
                size=quantity,
                side=order_side,
                fee_rate_bps=0,  # Maker has no fees
            )

            # Submit order
            print(f"   Submitting to CLOB...")
            result = self.client.create_order(order_args)

            if result and result.get('orderID'):
                order_id = result['orderID']
                print(f"   ✅ Order placed: {order_id[:16]}...")

                # Wait briefly for fill
                await asyncio.sleep(2)

                # Check fill status
                fill_status = self._check_order_fill(order_id)

                return {
                    'success': True,
                    'order_id': order_id,
                    'token_id': token_id,
                    'side': side,
                    'price': current_price,
                    'quantity': quantity,
                    'total_cost': usdc_amount,
                    'fill_status': fill_status,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                error = result.get('error', 'Unknown error') if result else 'No response'
                print(f"   ❌ Order failed: {error}")
                return {
                    'success': False,
                    'error': error,
                    'order_id': None
                }

        except Exception as e:
            print(f"   ❌ Order execution error: {e}")
            return {
                'success': False,
                'error': str(e),
                'order_id': None
            }

    def _check_order_fill(self, order_id: str) -> Dict:
        """Check if order was filled"""
        try:
            orders = self.client.get_orders()
            for order in orders:
                if order.get('id') == order_id:
                    return {
                        'status': order.get('status', 'unknown'),
                        'filled_size': order.get('filledSize', 0),
                        'remaining_size': order.get('remainingSize', 0)
                    }
            return {'status': 'not_found'}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        try:
            if not self.initialized:
                return False

            result = self.client.cancel_order(order_id)
            return result is not None

        except Exception as e:
            print(f"   ⚠️ Cancel order failed: {e}")
            return False

    def get_usdc_balance(self) -> float:
        """Get current USDC balance"""
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))

            usdc_abi = [
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                }
            ]

            usdc_contract = w3.eth.contract(
                address=Web3.to_checksum_address(config.USDC_ADDRESS),
                abi=usdc_abi
            )

            balance = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(config.FUNDER_ADDRESS)
            ).call()

            decimals = usdc_contract.functions.decimals().call()
            return balance / (10 ** decimals)

        except Exception as e:
            print(f"   ⚠️ Balance check failed: {e}")
            return 0.0

    def get_token_balance(self, token_id: str) -> float:
        """Get balance of a specific outcome token"""
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))

            ctf_abi = [
                {
                    "constant": True,
                    "inputs": [
                        {"name": "_owner", "type": "address"},
                        {"name": "_id", "type": "uint256"}
                    ],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                }
            ]

            ctf_contract = w3.eth.contract(
                address=Web3.to_checksum_address(config.CONDITIONAL_TOKENS_ADDRESS),
                abi=ctf_abi
            )

            balance = ctf_contract.functions.balanceOf(
                Web3.to_checksum_address(config.FUNDER_ADDRESS),
                int(token_id)
            ).call()

            # Outcome tokens have 6 decimals like USDC
            return balance / 1e6

        except Exception as e:
            print(f"   ⚠️ Token balance check failed: {e}")
            return 0.0


# Singleton instance
_executor = None


def get_order_executor() -> OrderExecutor:
    """Get or create the OrderExecutor singleton"""
    global _executor
    if _executor is None:
        _executor = OrderExecutor()
    return _executor
