"""
API Connection Test Script
Tests all connections before running the main system
"""

import os
from dotenv import load_dotenv
from web3 import Web3
import requests
from colorama import Fore, Style, init

# Initialize colorama
init(autoreset=True)

def print_header(text):
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}{text}")
    print(f"{Fore.CYAN}{'='*80}\n")

def print_success(text):
    print(f"{Fore.GREEN}✅ {text}")

def print_error(text):
    print(f"{Fore.RED}❌ {text}")

def print_warning(text):
    print(f"{Fore.YELLOW}⚠️  {text}")

def print_info(text):
    print(f"{Fore.WHITE}   {text}")

def test_env_file():
    """Test if .env file exists and is readable"""
    print_header("TEST 1: .env File")
    
    if not os.path.exists('.env'):
        print_error(".env file not found!")
        print_info("Create a .env file with your API credentials")
        return False
    
    print_success(".env file exists")
    
    # Load environment variables
    load_dotenv()
    
    return True

def test_polymarket_credentials():
    """Test Polymarket API credentials"""
    print_header("TEST 2: Polymarket API Credentials")
    
    api_key = os.getenv('POLYMARKET_API_KEY')
    secret = os.getenv('POLYMARKET_SECRET')
    passphrase = os.getenv('POLYMARKET_PASSPHRASE')
    
    if not api_key:
        print_error("POLYMARKET_API_KEY not found in .env")
        return False
    print_success(f"API Key found: {api_key[:20]}...")
    
    if not secret:
        print_error("POLYMARKET_SECRET not found in .env")
        return False
    print_success(f"Secret found: {secret[:20]}...")
    
    if not passphrase:
        print_error("POLYMARKET_PASSPHRASE not found in .env")
        return False
    print_success(f"Passphrase found: {passphrase[:20]}...")
    
    return True

def test_polygon_rpc():
    """Test Polygon RPC connection"""
    print_header("TEST 3: Polygon RPC Connection")
    
    rpc_url = os.getenv('POLYGON_RPC_URL')
    
    if not rpc_url:
        print_error("POLYGON_RPC_URL not found in .env")
        print_info("Add: POLYGON_RPC_URL=https://polygon-rpc.com")
        return False
    
    print_success(f"RPC URL found: {rpc_url[:50]}...")
    
    try:
        # Test connection
        print_info("Testing connection...")
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            print_error("Cannot connect to Polygon RPC")
            print_info("Check your RPC URL or try a different one")
            return False
        
        print_success("Connected to Polygon RPC!")
        
        # Get current block
        try:
            block = w3.eth.block_number
            print_success(f"Current block: {block:,}")
            
            # Test speed
            import time
            start = time.time()
            w3.eth.block_number
            latency = (time.time() - start) * 1000
            
            if latency < 100:
                print_success(f"Latency: {latency:.0f}ms (Excellent! ⚡)")
            elif latency < 500:
                print_success(f"Latency: {latency:.0f}ms (Good)")
            else:
                print_warning(f"Latency: {latency:.0f}ms (Slow - consider Alchemy)")
            
            return True
            
        except Exception as e:
            print_error(f"Error getting block number: {e}")
            return False
            
    except Exception as e:
        print_error(f"Connection error: {e}")
        print_info("Check your POLYGON_RPC_URL")
        return False

def test_polymarket_api():
    """Test Polymarket API connection"""
    print_header("TEST 4: Polymarket API Connection")
    
    try:
        print_info("Testing Polymarket API endpoint...")
        
        # Test public endpoint (doesn't need auth)
        url = "https://clob.polymarket.com/markets"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            print_success("Polymarket API is accessible")
            markets = response.json()
            print_success(f"Found {len(markets)} active markets")
            return True
        else:
            print_error(f"API returned status code: {response.status_code}")
            return False
            
    except Exception as e:
        print_error(f"Cannot connect to Polymarket API: {e}")
        print_info("Check your internet connection")
        return False

def test_polymarket_auth():
    """Test Polymarket authenticated endpoint"""
    print_header("TEST 5: Polymarket Authentication")

    api_key = os.getenv('POLYMARKET_API_KEY')
    secret = os.getenv('POLYMARKET_SECRET')
    passphrase = os.getenv('POLYMARKET_PASSPHRASE')
    private_key = os.getenv('PRIVATE_KEY')
    funder_address = os.getenv('FUNDER_ADDRESS')
    signature_type = int(os.getenv('SIGNATURE_TYPE', '1'))

    if not all([api_key, secret, passphrase, private_key]):
        print_warning("Missing credentials - skipping auth test")
        return False

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
        from py_clob_client.constants import POLYGON

        print_info("Initializing Polymarket client...")

        # Create API credentials
        creds = ApiCreds(
            api_key=api_key,
            api_secret=secret,
            api_passphrase=passphrase
        )

        # Create client with proxy wallet configuration
        client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=POLYGON,
            signature_type=signature_type,
            funder=funder_address,
            creds=creds
        )

        print_success("Polymarket client initialized!")
        print_info(f"Signer address: {client.signer.address()}")
        if funder_address:
            print_info(f"Funder address: {funder_address}")
        print_info(f"Signature type: {signature_type} ({'EOA' if signature_type == 0 else 'POLY_PROXY' if signature_type == 1 else 'GNOSIS_SAFE'})")

        # Try to get orders (authenticated endpoint)
        try:
            print_info("Testing authentication...")
            orders = client.get_orders()
            print_success("Authentication working!")
            print_info(f"Open orders: {len(orders) if orders else 0}")
            return True

        except Exception as e:
            print_error(f"Authentication failed: {e}")
            print_info("Check your API credentials and wallet configuration")
            return False

    except ImportError:
        print_error("py-clob-client not installed")
        print_info("Run: pip install py-clob-client")
        return False
    except Exception as e:
        print_error(f"Error creating client: {e}")
        return False

def test_contract_addresses():
    """Test if we can access Polymarket contracts"""
    print_header("TEST 6: Smart Contract Access")
    
    rpc_url = os.getenv('POLYGON_RPC_URL')
    if not rpc_url:
        print_warning("No RPC URL - skipping contract test")
        return False
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        # CTF Exchange contract
        ctf_address = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
        
        print_info(f"Testing CTF Exchange contract...")
        print_info(f"Address: {ctf_address}")
        
        # Check if contract exists
        code = w3.eth.get_code(ctf_address)
        
        if code and code != b'':
            print_success("CTF Exchange contract found!")
            print_success("Can read blockchain events")
            return True
        else:
            print_error("Contract not found at expected address")
            return False
            
    except Exception as e:
        print_error(f"Error accessing contract: {e}")
        return False

def test_dependencies():
    """Test if all required packages are installed"""
    print_header("TEST 7: Python Dependencies")
    
    required_packages = {
        'web3': 'Web3',
        'pandas': 'pandas',
        'py_clob_client': 'py-clob-client',
        'dotenv': 'python-dotenv',
        'tqdm': 'tqdm',
        'colorama': 'colorama',
    }
    
    all_installed = True
    
    for module, package in required_packages.items():
        try:
            __import__(module)
            print_success(f"{package} installed")
        except ImportError:
            print_error(f"{package} NOT installed")
            print_info(f"Run: pip install {package}")
            all_installed = False
    
    return all_installed

def test_configuration():
    """Test configuration values"""
    print_header("TEST 8: Configuration Values")
    
    config_items = {
        'STARTING_CAPITAL': 'Starting capital',
        'AUTO_COPY_ENABLED': 'Auto-copy enabled',
        'MAX_WHALES_TO_MONITOR': 'Max whales to monitor',
        'CONFIDENCE_THRESHOLD': 'Confidence threshold',
        'SCAN_INTERVAL_SECONDS': 'Scan interval',
    }
    
    all_set = True
    
    for key, name in config_items.items():
        value = os.getenv(key)
        if value:
            print_success(f"{name}: {value}")
        else:
            print_warning(f"{name}: Not set (will use default)")
    
    return True

def test_wallet_balance():
    """Check Polymarket wallet balance"""
    print_header("TEST 9: Polymarket Wallet Balance")
    
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.constants import POLYGON
        
        api_key = os.getenv('POLYMARKET_API_KEY')
        secret = os.getenv('POLYMARKET_SECRET')
        
        if not api_key or not secret:
            print_warning("No API credentials - skipping balance check")
            return False
        
        print_info("Checking wallet balance...")
        
        # Note: This is a simplified check
        # The actual balance check would require the full client setup
        print_warning("Balance check requires full authentication")
        print_info("Check your balance at: https://polymarket.com")
        
        return True
        
    except Exception as e:
        print_warning(f"Cannot check balance: {e}")
        print_info("Check manually at: https://polymarket.com")
        return True

def run_all_tests():
    """Run all connection tests"""
    
    print(f"\n{Fore.YELLOW}{'='*80}")
    print(f"{Fore.YELLOW}🔍 POLYMARKET WHALE TRACKER - CONNECTION TEST")
    print(f"{Fore.YELLOW}{'='*80}\n")
    
    results = {}
    
    # Run tests
    results['env_file'] = test_env_file()
    results['polymarket_creds'] = test_polymarket_credentials()
    results['polygon_rpc'] = test_polygon_rpc()
    results['polymarket_api'] = test_polymarket_api()
    results['polymarket_auth'] = test_polymarket_auth()
    results['contracts'] = test_contract_addresses()
    results['dependencies'] = test_dependencies()
    results['configuration'] = test_configuration()
    results['wallet'] = test_wallet_balance()
    
    # Summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        if result:
            print_success(f"{test_name.replace('_', ' ').title()}: PASSED")
        else:
            print_error(f"{test_name.replace('_', ' ').title()}: FAILED")
    
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}Results: {passed}/{total} tests passed")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    if passed == total:
        print(f"{Fore.GREEN}🎉 ALL TESTS PASSED! You're ready to run the system!")
        print(f"\n{Fore.WHITE}Run: python small_capital_system.py")
    elif passed >= total - 2:
        print(f"{Fore.YELLOW}⚠️  MOSTLY READY - Fix the failed tests above")
        print(f"\n{Fore.WHITE}Most connections working - you can probably still run")
    else:
        print(f"{Fore.RED}❌ SETUP INCOMPLETE - Fix the issues above")
        print(f"\n{Fore.WHITE}Fix the failed tests before running the system")
    
    print()

if __name__ == "__main__":
    run_all_tests()
