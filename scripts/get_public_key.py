from web3 import Web3
from eth_account import Account
import argparse

def get_ethereum_address(private_key_hex):
    # Add '0x' prefix if not present
    if not private_key_hex.startswith('0x'):
        private_key_hex = '0x' + private_key_hex
        
    # Create account from private key
    account = Account.from_key(private_key_hex)
    
    # Get the Ethereum address (which is derived from the public key)
    return account.address

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get Ethereum address from private key')
    parser.add_argument('private_key', help='Private key in hex format (with or without 0x prefix)')
    
    args = parser.parse_args()
    
    try:
        address = get_ethereum_address(args.private_key)
        print(f"Ethereum Address: {address}")
    except Exception as e:
        print(f"Error: {str(e)}")