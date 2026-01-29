"""
Configuration for Polymarket Whale Tracker
Contains contract addresses, ABIs, and settings
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the same directory as this config file
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path, override=True)

# Polymarket API Credentials
POLYMARKET_API_KEY = os.getenv('POLYMARKET_API_KEY')
POLYMARKET_SECRET = os.getenv('POLYMARKET_SECRET')
POLYMARKET_API_SECRET = POLYMARKET_SECRET  # Alias for order_executor
POLYMARKET_PASSPHRASE = os.getenv('POLYMARKET_PASSPHRASE')
POLYMARKET_API_PASSPHRASE = POLYMARKET_PASSPHRASE  # Alias

# Wallet Configuration
PRIVATE_KEY = os.getenv('PRIVATE_KEY')
FUNDER_ADDRESS = os.getenv('FUNDER_ADDRESS')  # Proxy wallet holding funds
SIGNATURE_TYPE = int(os.getenv('SIGNATURE_TYPE', '1'))  # 0=EOA, 1=POLY_PROXY, 2=GNOSIS_SAFE

# Polygon RPC Endpoints
POLYGON_RPC_URL = os.getenv('POLYGON_RPC_URL', 'https://polygon-rpc.com')
POLYGON_RPC_BACKUP = [
    os.getenv('POLYGON_RPC_BACKUP_1', 'https://rpc-mainnet.maticvigil.com'),
    os.getenv('POLYGON_RPC_BACKUP_2', 'https://polygon-mainnet.public.blastapi.io')
]

# Polymarket Contract Addresses on Polygon
CTFEXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
CTF_EXCHANGE_ADDRESS = CTFEXCHANGE_ADDRESS  # Alias for websocket_monitor
CONDITIONAL_TOKENS_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
COLLATERAL_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC
USDC_ADDRESS = COLLATERAL_TOKEN_ADDRESS  # Alias for order_executor

# Polymarket API
POLYMARKET_API_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_CLOB_API = "https://clob.polymarket.com"

# AI Configuration
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# Database
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///whale_tracker.db')

# Trading Settings
AUTO_COPY_ENABLED = os.getenv('AUTO_COPY_ENABLED', 'false').lower() == 'true'
MAX_COPY_SIZE_USD = float(os.getenv('MAX_COPY_SIZE_USD', '100'))
CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', '80'))
MAX_WHALES_TO_TRACK = int(os.getenv('MAX_WHALES_TO_TRACK', '50'))

# Position Sizing Mode
# Set to a dollar amount for fixed sizing (e.g., 10.0 = $10 per trade)
# Set to None or 0 to use Kelly Criterion dynamic sizing
FIXED_POSITION_SIZE = float(os.getenv('FIXED_POSITION_SIZE', '10.0')) or None

# Whale Discovery Criteria
MIN_WHALE_PROFIT = float(os.getenv('MIN_WHALE_PROFIT', '5000'))
MIN_WHALE_WIN_RATE = float(os.getenv('MIN_WHALE_WIN_RATE', '0.60'))
MIN_WHALE_TRADES = int(os.getenv('MIN_WHALE_TRADES', '50'))

# Monitoring
SCAN_INTERVAL_SECONDS = int(os.getenv('SCAN_INTERVAL_SECONDS', '10'))
HISTORICAL_BLOCKS_TO_ANALYZE = int(os.getenv('HISTORICAL_BLOCKS_TO_ANALYZE', '100000'))

# Telegram Alerts
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# CTF Exchange ABI (correct Polymarket OrderFilled event)
# Signature: OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)
CTFEXCHANGE_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "orderHash", "type": "bytes32"},
            {"indexed": True, "name": "maker", "type": "address"},
            {"indexed": True, "name": "taker", "type": "address"},
            {"indexed": False, "name": "makerAssetId", "type": "uint256"},
            {"indexed": False, "name": "takerAssetId", "type": "uint256"},
            {"indexed": False, "name": "makerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "takerAmountFilled", "type": "uint256"},
            {"indexed": False, "name": "fee", "type": "uint256"},
        ],
        "name": "OrderFilled",
        "type": "event"
    }
]
CTF_EXCHANGE_ABI = CTFEXCHANGE_ABI  # Alias for websocket_monitor

# Conditional Tokens ABI (simplified)
CONDITIONAL_TOKENS_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "id", "type": "uint256"},
            {"indexed": False, "name": "value", "type": "uint256"}
        ],
        "name": "TransferSingle",
        "type": "event"
    },
    {
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"}
        ],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Block ranges for analysis (Polymarket launched ~May 2024)
POLYMARKET_LAUNCH_BLOCK = 57000000  # Approximate
CURRENT_BLOCK_LOOKBACK = 500000  # ~1 month of blocks on Polygon

print("✅ Configuration loaded successfully")
print(f"   - Polygon RPC: {POLYGON_RPC_URL}")
print(f"   - CTF Exchange: {CTFEXCHANGE_ADDRESS}")
print(f"   - Auto-copy: {'ENABLED' if AUTO_COPY_ENABLED else 'DISABLED'}")
print(f"   - Min whale profit: ${MIN_WHALE_PROFIT:,.0f}")
print(f"   - Min win rate: {MIN_WHALE_WIN_RATE*100:.0f}%")
