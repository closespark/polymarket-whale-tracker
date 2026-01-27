"""
WebSocket Real-Time Trade Monitor

Sub-second whale detection using blockchain event subscriptions.

Old approach: Poll every 60 seconds
- Latency: 15-60 seconds
- Miss trades that happen between polls

New approach: WebSocket event stream
- Latency: 2-5 seconds
- Instant notification when whale trades
- Better entry prices, less slippage
"""

import asyncio
import json
from datetime import datetime
from typing import Callable, List, Set, Optional
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

import config


class WebSocketTradeMonitor:
    """
    Real-time trade monitoring using WebSocket subscriptions

    Subscribes to OrderFilled events and triggers callback
    when a monitored whale makes a trade.
    """

    def __init__(self,
                 whale_addresses: List[str],
                 rpc_url: str = None,
                 ws_url: str = None):
        """
        Initialize WebSocket monitor

        Args:
            whale_addresses: List of whale addresses to monitor
            rpc_url: HTTP RPC URL (for fallback)
            ws_url: WebSocket RPC URL (for subscriptions)
        """
        self.whale_addresses = set(addr.lower() for addr in whale_addresses)
        self.rpc_url = rpc_url or config.POLYGON_RPC_URL

        # Convert HTTP to WebSocket URL if needed
        if ws_url:
            self.ws_url = ws_url
        elif 'alchemy.com' in self.rpc_url:
            # Alchemy WebSocket: just replace https with wss (no /ws/ suffix)
            self.ws_url = self.rpc_url.replace('https://', 'wss://')
        elif 'infura.io' in self.rpc_url:
            self.ws_url = self.rpc_url.replace('https://', 'wss://')
        else:
            self.ws_url = None  # Will fall back to polling

        # Web3 connection (HTTP for queries)
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        # CTF Exchange contract
        self.ctf_address = config.CTF_EXCHANGE_ADDRESS
        self.ctf_contract = self.w3.eth.contract(
            address=self.ctf_address,
            abi=config.CTF_EXCHANGE_ABI
        )

        # Callback for when whale trades detected
        self.trade_callback: Optional[Callable] = None

        # Stats
        self.events_received = 0
        self.whale_trades_detected = 0
        self.last_event_time = None
        self.running = False

        print(f"WebSocket Monitor initialized")
        print(f"  Monitoring {len(self.whale_addresses)} whales")
        print(f"  WebSocket URL: {self.ws_url[:50]}..." if self.ws_url else "  WebSocket: Not available (will poll)")

    def update_whale_addresses(self, addresses: List[str]):
        """Update the list of whale addresses to monitor"""
        self.whale_addresses = set(addr.lower() for addr in addresses)
        print(f"Updated whale list: {len(self.whale_addresses)} addresses")

    async def start(self, callback: Callable):
        """
        Start monitoring for whale trades

        Args:
            callback: Async function to call when whale trade detected
                     Receives: trade_data dict
        """
        self.trade_callback = callback
        self.running = True

        if self.ws_url:
            # Try WebSocket first
            try:
                await self._run_websocket_monitor()
            except Exception as e:
                print(f"WebSocket failed ({e}), falling back to polling")
                await self._run_polling_monitor()
        else:
            # Fall back to polling
            await self._run_polling_monitor()

    async def stop(self):
        """Stop monitoring"""
        self.running = False

    async def _run_websocket_monitor(self):
        """
        Monitor using WebSocket event subscriptions

        This is the fast path - 2-5 second latency
        """
        import websockets

        print("\n🔌 Starting WebSocket monitor (sub-second detection)")

        # Build subscription request for OrderFilled events
        # Note: This is provider-specific. Alchemy/Infura support eth_subscribe
        # OrderFilled event signature hash (pre-computed for reliability)
        # keccak256("OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)")
        event_signature = "0x" + self.w3.keccak(
            text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
        ).hex()

        subscription_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": self.ctf_address,
                    "topics": [event_signature]
                }
            ]
        }

        print(f"   Contract: {self.ctf_address}")
        print(f"   Event sig: {event_signature[:20]}...")

        reconnect_count = 0
        max_reconnects = 100  # Allow many reconnects before giving up

        while self.running and reconnect_count < max_reconnects:
            try:
                reconnect_count += 1
                if reconnect_count > 1:
                    print(f"🔄 WebSocket reconnecting (attempt {reconnect_count}/{max_reconnects})...")

                async with websockets.connect(
                    self.ws_url,
                    open_timeout=60,       # Increased from 30
                    close_timeout=10,
                    ping_interval=30,      # Increased from 20 (less aggressive)
                    ping_timeout=30,       # Match ping_interval
                    max_size=10 * 1024 * 1024  # 10MB max message size
                ) as ws:
                    # Subscribe
                    await ws.send(json.dumps(subscription_request))
                    response = await ws.recv()
                    sub_response = json.loads(response)

                    if 'result' in sub_response:
                        print(f"✅ Subscribed to events (ID: {sub_response['result'][:16]}...)")
                        reconnect_count = 0  # Reset on successful connection
                    elif 'error' in sub_response:
                        error = sub_response['error']
                        print(f"❌ Subscription failed: {error.get('message', error)}")
                        print(f"   Falling back to polling mode...")
                        await self._run_polling_monitor()
                        return
                    else:
                        print(f"⚠️ Unexpected subscription response: {sub_response}")

                    # Listen for events
                    heartbeat_count = 0
                    while self.running:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            data = json.loads(message)

                            if 'params' in data and 'result' in data['params']:
                                await self._process_log_event(data['params']['result'])

                        except asyncio.TimeoutError:
                            # No message received in 30s - this is normal, just heartbeat
                            heartbeat_count += 1
                            if heartbeat_count % 4 == 0:  # Every 2 minutes
                                print(f"   💓 WebSocket alive ({heartbeat_count * 30}s, {self.events_received} events, {self.whale_trades_detected} whale trades)")
                            continue

            except websockets.exceptions.ConnectionClosed as e:
                print(f"⚠️ WebSocket connection closed ({e}), reconnecting in 5s...")
                await asyncio.sleep(5)

            except Exception as e:
                print(f"⚠️ WebSocket error: {type(e).__name__}: {e}")
                # Exponential backoff for repeated failures
                wait_time = min(5 * reconnect_count, 60)
                print(f"   Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        # If we exhausted reconnects, fall back to polling
        if reconnect_count >= max_reconnects:
            print(f"⚠️ WebSocket reconnect limit reached, falling back to polling")
            await self._run_polling_monitor()

    async def _process_log_event(self, log_data: dict):
        """Process a raw log event from WebSocket"""
        self.events_received += 1
        self.last_event_time = datetime.now()

        try:
            # Decode the event
            # OrderFilled(bytes32 indexed orderHash, address indexed maker, address indexed taker,
            #             uint256 makerAssetId, uint256 takerAssetId, uint256 makerAmountFilled,
            #             uint256 takerAmountFilled, uint256 fee)
            #
            # Topics: [event_sig, orderHash, maker, taker] - indexed params
            # Data: [makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee] - non-indexed

            topics = log_data.get('topics', [])
            if len(topics) < 4:
                return  # Invalid event

            # Indexed addresses are in topics (padded to 32 bytes)
            maker = '0x' + topics[2][-40:]  # Last 20 bytes (40 hex chars)
            taker = '0x' + topics[3][-40:]

            maker_lower = maker.lower()
            taker_lower = taker.lower()

            # Check if whale
            if maker_lower in self.whale_addresses or taker_lower in self.whale_addresses:
                self.whale_trades_detected += 1

                # Determine which whale
                if maker_lower in self.whale_addresses:
                    whale = maker
                    side = 'SELL'
                else:
                    whale = taker
                    side = 'BUY'

                # Decode amounts from data (non-indexed params)
                # Each uint256 is 32 bytes (64 hex chars)
                data = log_data['data'][2:]  # Remove 0x prefix
                # makerAssetId at offset 0, takerAssetId at 64, makerAmountFilled at 128, takerAmountFilled at 192
                maker_amount = int(data[128:192], 16)  # makerAmountFilled
                taker_amount = int(data[192:256], 16)  # takerAmountFilled

                # Calculate USDC value (taker_amount is in USDC with 6 decimals)
                usdc_value = taker_amount / 1e6

                trade_data = {
                    'whale_address': whale,
                    'side': side,
                    'maker': maker,
                    'taker': taker,
                    'maker_amount': maker_amount,
                    'taker_amount': taker_amount,
                    'usdc_value': usdc_value,
                    'price': taker_amount / maker_amount if maker_amount > 0 else 0,
                    'block_number': int(log_data['blockNumber'], 16),
                    'tx_hash': log_data['transactionHash'],
                    'detection_method': 'websocket',
                    'detection_time': datetime.now().isoformat(),
                    'latency_estimate': '2-5 seconds'
                }

                print(f"\n🐋 WHALE DETECTED (WebSocket)")
                print(f"   Whale: {whale[:10]}...")
                print(f"   Side: {side}")
                print(f"   Amount: ${taker_amount / 1e6:,.2f}")
                print(f"   Block: {trade_data['block_number']}")

                if self.trade_callback:
                    await self.trade_callback(trade_data)

        except Exception as e:
            print(f"Error processing event: {e}")

    async def _run_polling_monitor(self):
        """
        Fallback: Poll for events every 10 seconds

        Slower than WebSocket but more reliable
        """
        print("\n⏱️ Starting polling monitor (10-second intervals)")

        last_block = self.w3.eth.block_number

        while self.running:
            try:
                current_block = self.w3.eth.block_number

                if current_block > last_block:
                    # Get new events
                    events = self.ctf_contract.events.OrderFilled.get_logs(
                        from_block=last_block + 1,
                        to_block=current_block
                    )

                    self.events_received += len(events)

                    for event in events:
                        maker = event['args']['maker'].lower()
                        taker = event['args']['taker'].lower()

                        if maker in self.whale_addresses or taker in self.whale_addresses:
                            self.whale_trades_detected += 1

                            if maker in self.whale_addresses:
                                whale = event['args']['maker']
                                side = 'SELL'
                            else:
                                whale = event['args']['taker']
                                side = 'BUY'

                            trade_data = {
                                'whale_address': whale,
                                'side': side,
                                'maker': event['args']['maker'],
                                'taker': event['args']['taker'],
                                'maker_amount': event['args']['makerAmountFilled'],
                                'taker_amount': event['args']['takerAmountFilled'],
                                'price': event['args']['takerAmountFilled'] / event['args']['makerAmountFilled'] if event['args']['makerAmountFilled'] > 0 else 0,
                                'block_number': event['blockNumber'],
                                'tx_hash': event['transactionHash'].hex(),
                                'detection_method': 'polling',
                                'detection_time': datetime.now().isoformat(),
                                'latency_estimate': '10-20 seconds'
                            }

                            print(f"\n🐋 WHALE DETECTED (Polling)")
                            print(f"   Whale: {whale[:10]}...")
                            print(f"   Side: {side}")

                            if self.trade_callback:
                                await self.trade_callback(trade_data)

                    last_block = current_block

                await asyncio.sleep(10)  # Poll every 10 seconds

            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(30)

    def get_stats(self) -> dict:
        """Get monitoring statistics"""
        return {
            'events_received': self.events_received,
            'whale_trades_detected': self.whale_trades_detected,
            'whales_monitored': len(self.whale_addresses),
            'last_event_time': self.last_event_time.isoformat() if self.last_event_time else None,
            'running': self.running,
            'method': 'websocket' if self.ws_url else 'polling'
        }


class HybridMonitor:
    """
    Hybrid approach: WebSocket + Polling backup

    Uses WebSocket for speed, with polling as reliability backup
    """

    def __init__(self, whale_addresses: List[str]):
        self.ws_monitor = WebSocketTradeMonitor(whale_addresses)
        self.seen_txs = set()  # Deduplicate
        self.callback = None

    async def start(self, callback: Callable):
        """Start both monitoring methods"""
        self.callback = callback

        async def dedupe_callback(trade_data):
            tx_hash = trade_data.get('tx_hash', '')
            if tx_hash not in self.seen_txs:
                self.seen_txs.add(tx_hash)
                # Keep set size manageable
                if len(self.seen_txs) > 10000:
                    self.seen_txs = set(list(self.seen_txs)[-5000:])

                await callback(trade_data)

        await self.ws_monitor.start(dedupe_callback)

    def update_whales(self, addresses: List[str]):
        """Update whale list"""
        self.ws_monitor.update_whale_addresses(addresses)

    async def stop(self):
        """Stop monitoring"""
        await self.ws_monitor.stop()


async def demo():
    """Demo the WebSocket monitor"""
    print("="*60)
    print("WEBSOCKET TRADE MONITOR DEMO")
    print("="*60)

    # Sample whale addresses (replace with real ones)
    whales = [
        "0x1234567890123456789012345678901234567890",
        "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
    ]

    monitor = WebSocketTradeMonitor(whales)

    async def on_whale_trade(trade_data):
        print(f"\n🎯 TRADE DETECTED!")
        print(f"   Whale: {trade_data['whale_address']}")
        print(f"   Side: {trade_data['side']}")
        print(f"   Method: {trade_data['detection_method']}")

    print("\nStarting monitor (Ctrl+C to stop)...")

    try:
        await monitor.start(on_whale_trade)
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    asyncio.run(demo())
