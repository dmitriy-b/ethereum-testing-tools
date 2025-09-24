import sys
import json
import argparse
from typing import cast, Optional

from web3 import HTTPProvider, Web3
from web3.types import HexStr
from web3.middleware import SignAndSendRawMiddlewareBuilder


def send_voluntary_exit(
    w3: Web3,
    password: Optional[str],
    pubkey: str,
    validator_index: int,
    keystore_path: Optional[str] = None,
    contract_address: str = "0x0000000000000000000000000000000000000000",  # This should be replaced with actual voluntary exit contract
    private_key: Optional[bytes] = None,
):
    print(f"Preparing voluntary exit for validator {pubkey} (index: {validator_index})")
    
    if private_key:
        # Use the provided private key directly
        account = w3.eth.account.from_key(private_key)
    else:
        # Use keystore file
        if not keystore_path:
            raise ValueError("Keystore path must be provided if private key is not used")
        if not password:
            raise ValueError("Password must be provided when using keystore file")
            
        with open(keystore_path, "r") as f:
            keystore = json.load(f)
        decrypted_key = w3.eth.account.decrypt(
            keystore,
            password,
        )
        account = w3.eth.account.from_key(decrypted_key)
    
    w3.middleware_onion.inject(SignAndSendRawMiddlewareBuilder.build(account), layer=0)
    w3.eth.default_account = account.address

    # Check account balance
    balance = w3.eth.get_balance(account.address)
    print(f"Account balance: {w3.from_wei(balance, 'gwei')} gwei ({w3.from_wei(balance, 'ether')} ETH)")
    print(f"Account address: {account.address}")

    # Validate validator index
    if validator_index < 0:
        print("Error: Validator index must be a positive integer")
        return
    
    # Confirm voluntary exit
    print("\nWARNING: Voluntary exit is IRREVERSIBLE!")
    print("Once your validator has exited, it cannot be reactivated.")
    print("You will be able to withdraw your stake after the exit is processed and finalized.")
    confirm = input("Do you want to continue with the voluntary exit? (y/n): ")
    if confirm.lower() != 'y':
        print("Voluntary exit cancelled")
        return

    # Prepare exit transaction data
    # Format: pubkey (0x + 48 bytes) + validator_index (32-bit integer)
    exit_tx_data = f"0x{pubkey[2:]}{hex(validator_index)[2:].zfill(8)}"
    print(f"Preparing transaction for voluntary exit of validator with index {validator_index}")
    
    try:
        # Gas price calculation
        gas_price = w3.eth.gas_price
        print(f"Current gas price: {w3.from_wei(gas_price, 'gwei')} gwei")
        
        # Estimated gas fee
        estimated_gas = 100000  # This is an estimate, adjust as needed
        estimated_fee = estimated_gas * gas_price
        print(f"Estimated transaction fee: {w3.from_wei(estimated_fee, 'gwei')} gwei ({w3.from_wei(estimated_fee, 'ether')} ETH)")
        
        # Check if balance is sufficient
        if balance < estimated_fee:
            print(f"Insufficient funds. Need at least {w3.from_wei(estimated_fee, 'gwei')} gwei")
            print(f"Please send some ETH to address {account.address} to cover the transaction fee.")
            return
        
        # Send transaction
        exit_tx_hash = w3.eth.send_transaction(
            {
                "from": account.address,
                "to": Web3.to_checksum_address(contract_address),
                "gas": estimated_gas,
                "data": Web3.to_bytes(hexstr=cast(HexStr, exit_tx_data)),
            }
        )
        print("Transaction sent successfully!")
        print("Transaction hash: 0x" + exit_tx_hash.hex())
        print(f"Voluntary exit initiated for validator with index {validator_index}.")
        print("It may take several epochs (hours) for the exit to be processed on the beacon chain.")
    except Exception as e:
        print(f"Error sending transaction: {e}")


def main():
    parser = argparse.ArgumentParser(description='Submit a voluntary exit for an Ethereum validator')
    parser.add_argument('--rpc-url', required=True, help='RPC URL for Ethereum node')
    parser.add_argument('--pubkey', required=True, help='Public key of the validator')
    parser.add_argument('--validator-index', required=True, type=int, help='Index of the validator on the beacon chain')
    parser.add_argument('--keystore-path', 
                        default=None,
                        help='Path to keystore file')
    parser.add_argument('--private-key',
                        default=None,
                        help='Private key for transaction signing (alternative to keystore)')
    parser.add_argument('--contract-address', 
                        default="0x0000000000000000000000000000000000000000",  # This should be replaced with actual voluntary exit contract
                        help='Voluntary exit contract address')
    parser.add_argument('--fund-account', action='store_true',
                        help='Only display the account address that needs funding, without attempting exit')
    
    args = parser.parse_args()
    
    provider = HTTPProvider(args.rpc_url)
    w3 = Web3(provider)
    
    # Make sure either private key or keystore path is provided
    if not args.private_key and not args.keystore_path:
        print("Error: Either --private-key or --keystore-path must be provided")
        sys.exit(1)
    
    # If using keystore, get password
    password = None
    if args.keystore_path:
        password = input("Input keystore password: ")
    
    # If --fund-account is specified, just show the address that needs funding
    if args.fund_account:
        if args.private_key:
            account = w3.eth.account.from_key(bytes.fromhex(args.private_key.replace('0x', '')))
        else:
            if not args.keystore_path:
                print("Error: Either --private-key or --keystore-path must be provided")
                sys.exit(1)
                
            if not password:
                print("Error: Password is required when using keystore file")
                sys.exit(1)
                
            with open(args.keystore_path, "r") as f:
                keystore = json.load(f)
            decrypted_key = w3.eth.account.decrypt(keystore, password)
            account = w3.eth.account.from_key(decrypted_key)
        
        print("\n=== FUNDING INFORMATION ===")
        print(f"Account address: {account.address}")
        print(f"Current balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")
        print("\nPlease send a small amount of ETH (0.001 ETH should be more than enough)")
        print("to this address to cover the voluntary exit transaction fee.")
        print("\nAfter funding, run the script again without the --fund-account flag to perform the exit.")
        sys.exit(0)
    
    # Validate validator index
    if args.validator_index < 0:
        print("Error: Validator index must be a positive integer")
        sys.exit(1)

    # Confirm voluntary exit
    print("\nWARNING: Voluntary exit is IRREVERSIBLE!")
    print("Once your validator has exited, it cannot be reactivated.")
    print("You will be able to withdraw your stake after the exit is processed and finalized.")
    confirm = input("Are you ABSOLUTELY SURE you want to exit validator {0}? (y/n): ".format(args.validator_index))
    if confirm.lower() != 'y':
        print("Voluntary exit cancelled")
        sys.exit(1)

    send_voluntary_exit(
        w3,
        password,
        args.pubkey,
        args.validator_index,
        args.keystore_path,
        args.contract_address,
        bytes.fromhex(args.private_key.replace('0x', '')) if args.private_key else None,
    )


if __name__ == "__main__":
    main() 