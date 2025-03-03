from web3 import Web3
import argparse
import json
from eth_account import Account
import sys
from pathlib import Path
import time

# ERC-20 Token ABI - only the methods we need
TOKEN_ABI = [
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
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]

def load_addresses_from_file(file_path):
    """Load addresses from a text file or JSON file."""
    file_path = Path(file_path)
    if file_path.suffix == '.txt':
        with open(file_path, 'r') as f:
            # Remove any whitespace and empty lines
            return [addr.strip() for addr in f.readlines() if addr.strip()]
    elif file_path.suffix == '.json':
        with open(file_path, 'r') as f:
            data = json.load(f)
            # Handle both array of objects with 'public_key' and array of addresses
            addresses = []
            for item in data:
                if isinstance(item, dict) and 'public_key' in item:
                    addresses.append(item['public_key'])
                elif isinstance(item, str):
                    addresses.append(item)
            return addresses
    else:
        raise ValueError("Unsupported file format. Use .txt or .json")

def validate_eth_address(address):
    """Validate if the address is a valid Ethereum address."""
    return Web3.is_address(address)

def get_transaction_counts(web3, address):
    """Get detailed transaction counts using different methods."""
    try:
        latest = web3.eth.get_transaction_count(address, 'latest')
        pending = web3.eth.get_transaction_count(address, 'pending')
        
        latest_direct = web3.provider.make_request("eth_getTransactionCount", [address, "latest"])
        pending_direct = web3.provider.make_request("eth_getTransactionCount", [address, "pending"])
        
        print("\nTransaction count details:")
        print(f"Latest (standard): {latest}")
        print(f"Pending (standard): {pending}")
        print(f"Latest (direct): {int(latest_direct['result'], 16) if 'result' in latest_direct else 'N/A'}")
        print(f"Pending (direct): {int(pending_direct['result'], 16) if 'result' in pending_direct else 'N/A'}")
        
        all_nonces = [latest, pending]
        if 'result' in latest_direct:
            all_nonces.append(int(latest_direct['result'], 16))
        if 'result' in pending_direct:
            all_nonces.append(int(pending_direct['result'], 16))
        
        return max(all_nonces)
        
    except Exception as e:
        print(f"Error getting transaction counts: {str(e)}")
        return web3.eth.get_transaction_count(address, 'latest')

def cancel_pending_transactions(web3, from_private_key, start_nonce, end_nonce):
    """Cancel pending transactions by sending 0 ETH transactions to self with higher gas price."""
    account = Account.from_key(from_private_key)
    from_address = account.address
    
    print(f"\nAttempting to cancel transactions with nonces from {start_nonce} to {end_nonce}")
    
    gas_price = web3.eth.gas_price
    cancel_gas_price = gas_price * 5
    
    for nonce in range(start_nonce, end_nonce + 1):
        try:
            transaction = {
                'nonce': nonce,
                'to': from_address,
                'value': 0,
                'gas': 21000,
                'gasPrice': cancel_gas_price,
                'chainId': web3.eth.chain_id
            }
            
            signed_txn = web3.eth.account.sign_transaction(transaction, from_private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            print(f"Cancellation transaction sent for nonce {nonce}, hash: {tx_hash.hex()}")
            
            tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            if tx_receipt.status == 1:
                print(f"Successfully cancelled transaction with nonce {nonce}")
            else:
                print(f"Cancellation failed for nonce {nonce}")
                
        except Exception as e:
            print(f"Error cancelling nonce {nonce}: {str(e)}")
            continue
            
    print("Cancellation attempts completed")
    time.sleep(5)

def transfer_tokens(web3, token_contract, from_private_key, to_address, amount_tokens, gas_price_gwei=None, max_retries=3):
    """Transfer tokens to a single address."""
    account = Account.from_key(from_private_key)
    from_address = account.address
    last_tx_hash = None
    
    # Get initial nonce with detailed information
    latest_nonce = web3.eth.get_transaction_count(from_address, 'latest')
    pending_nonce = web3.eth.get_transaction_count(from_address, 'pending')
    
    if pending_nonce > latest_nonce:
        print(f"\nDetected {pending_nonce - latest_nonce} pending transactions")
        response = input("Would you like to attempt to cancel pending transactions? (yes/no): ")
        if response.lower() == 'yes':
            cancel_pending_transactions(web3, from_private_key, latest_nonce, pending_nonce - 1)
            nonce = web3.eth.get_transaction_count(from_address, 'latest')
        else:
            nonce = pending_nonce
    else:
        nonce = latest_nonce
    
    print(f"Starting with nonce: {nonce}")
    
    # Get token decimals
    decimals = token_contract.functions.decimals().call()
    token_symbol = token_contract.functions.symbol().call()
    
    # Convert token amount to smallest unit
    amount_in_smallest_unit = int(amount_tokens * (10 ** decimals))
    
    for attempt in range(max_retries):
        try:
            # Try legacy transaction first since we know the network supports it
            try:
                print("Trying legacy transaction...")
                gas_price = web3.eth.gas_price * 2 if not gas_price_gwei else web3.to_wei(gas_price_gwei, 'gwei')
                
                transfer_txn = token_contract.functions.transfer(
                    to_address,
                    amount_in_smallest_unit
                ).build_transaction({
                    'chainId': web3.eth.chain_id,
                    'gas': 100000,
                    'gasPrice': gas_price,
                    'nonce': nonce,
                })
                
                print(f"\nTransaction details:")
                print(f"From: {from_address}")
                print(f"To: {to_address}")
                print(f"Value: {amount_tokens} {token_symbol}")
                print(f"Gas Price: {web3.from_wei(gas_price, 'gwei')} Gwei")
                print(f"Nonce: {nonce}")
                
                signed_txn = web3.eth.account.sign_transaction(transfer_txn, from_private_key)
                tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
                last_tx_hash = tx_hash
                
                tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                if tx_receipt and tx_receipt.status == 1:
                    return tx_receipt
                    
            except Exception as legacy_error:
                print(f"Legacy transaction failed: {str(legacy_error)}")
                print("Trying EIP-1559 transaction...")
                
                # Get the latest base fee
                base_fee = web3.eth.get_block('latest').get('baseFeePerGas', web3.eth.gas_price)
                
                # Calculate max fee and priority fee
                if gas_price_gwei:
                    max_fee_per_gas = web3.to_wei(gas_price_gwei, 'gwei')
                    max_priority_fee_per_gas = web3.to_wei(min(2, gas_price_gwei), 'gwei')
                else:
                    max_priority_fee_per_gas = web3.to_wei(2, 'gwei')
                    max_fee_per_gas = base_fee * 2 + max_priority_fee_per_gas
                
                transfer_txn = token_contract.functions.transfer(
                    to_address,
                    amount_in_smallest_unit
                ).build_transaction({
                    'chainId': web3.eth.chain_id,
                    'gas': 100000,  # Higher gas limit for token transfers
                    'maxFeePerGas': max_fee_per_gas,
                    'maxPriorityFeePerGas': max_priority_fee_per_gas,
                    'nonce': nonce,
                    'type': 2  # EIP-1559 transaction type
                })

                print(f"\nTransaction details:")
                print(f"From: {from_address}")
                print(f"To: {to_address}")
                print(f"Value: {amount_tokens} {token_symbol}")
                print(f"Max Fee Per Gas: {web3.from_wei(max_fee_per_gas, 'gwei')} Gwei")
                print(f"Max Priority Fee Per Gas: {web3.from_wei(max_priority_fee_per_gas, 'gwei')} Gwei")
                print(f"Nonce: {nonce}")

                signed_txn = web3.eth.account.sign_transaction(transfer_txn, from_private_key)
                tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
                last_tx_hash = tx_hash
                
                tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                if tx_receipt and tx_receipt.status == 1:
                    return tx_receipt

        except Exception as e:
            error_message = str(e)
            print(f"Error: {error_message}")

            if 'nonce too low' in error_message.lower():
                nonce = web3.eth.get_transaction_count(from_address, 'latest')
                print(f"Got new nonce: {nonce}")
                continue
            elif 'already known' in error_message.lower() or 'known transaction' in error_message.lower():
                if last_tx_hash:
                    print("Transaction already in mempool, waiting for confirmation...")
                    try:
                        tx_receipt = web3.eth.wait_for_transaction_receipt(last_tx_hash, timeout=30)
                        if tx_receipt and tx_receipt.status == 1:
                            return tx_receipt
                    except Exception as wait_error:
                        print(f"Error waiting for receipt: {str(wait_error)}")
            
            if attempt < max_retries - 1:
                print(f"Attempt {attempt + 1} failed, waiting before retry...")
                time.sleep(5)
                nonce = web3.eth.get_transaction_count(from_address, 'latest')
                continue
            else:
                print(f"All attempts failed")
                return None

def main():
    parser = argparse.ArgumentParser(description='Transfer ERC-20 tokens to one or multiple addresses')
    parser.add_argument('--from-key', required=True, help='Private key to send from (with 0x prefix)')
    parser.add_argument('--to', help='Single address to send to')
    parser.add_argument('--to-file', help='File containing addresses (one per line for .txt, or JSON format)')
    parser.add_argument('--amount', type=float, required=True, help='Amount of tokens to send to each address')
    parser.add_argument('--token-address', required=True, help='Token contract address')
    parser.add_argument('--gas-price', type=float, help='Gas price in Gwei (optional)')
    parser.add_argument('--rpc-url', required=True, help='Custom RPC URL')

    args = parser.parse_args()

    if not args.to and not args.to_file:
        parser.error("Either --to or --to-file must be specified")

    if args.to and args.to_file:
        parser.error("Cannot specify both --to and --to-file")

    # Setup web3 connection
    web3 = Web3(Web3.HTTPProvider(args.rpc_url))

    if not web3.is_connected():
        print("Error: Could not connect to network")
        sys.exit(1)

    # Get chain ID for display
    try:
        chain_id = web3.eth.chain_id
        print(f"Connected to network with chain ID: {chain_id}")
    except Exception as e:
        print(f"Warning: Could not get chain ID: {str(e)}")
        sys.exit(1)

    # Initialize token contract
    try:
        token_contract = web3.eth.contract(address=args.token_address, abi=TOKEN_ABI)
        token_symbol = token_contract.functions.symbol().call()
        token_decimals = token_contract.functions.decimals().call()
        print(f"Token: {token_symbol} (decimals: {token_decimals})")
    except Exception as e:
        print(f"Error initializing token contract: {str(e)}")
        sys.exit(1)

    # Get addresses to send to
    if args.to:
        addresses = [args.to]
    else:
        try:
            addresses = load_addresses_from_file(args.to_file)
        except Exception as e:
            print(f"Error loading addresses from file: {str(e)}")
            sys.exit(1)

    # Validate addresses
    invalid_addresses = [addr for addr in addresses if not validate_eth_address(addr)]
    if invalid_addresses:
        print("Error: Invalid Ethereum addresses found:")
        for addr in invalid_addresses:
            print(addr)
        sys.exit(1)

    # Check token balance
    account = Account.from_key(args.from_key)
    token_balance = token_contract.functions.balanceOf(account.address).call()
    token_balance_formatted = token_balance / (10 ** token_decimals)
    total_needed = args.amount * len(addresses)

    print(f"\nSender address: {account.address}")
    print(f"Current token balance: {token_balance_formatted:.6f} {token_symbol}")
    print(f"Total tokens needed: {total_needed:.6f} {token_symbol}")
    print(f"Number of addresses to send to: {len(addresses)}")

    if token_balance_formatted < total_needed:
        print(f"Error: Insufficient token balance. Need {total_needed:.6f} {token_symbol} but only have {token_balance_formatted:.6f} {token_symbol}")
        sys.exit(1)

    # Check if there's enough ETH for gas
    eth_balance = web3.eth.get_balance(account.address)
    eth_balance_eth = web3.from_wei(eth_balance, 'ether')
    estimated_gas_eth = web3.from_wei(web3.eth.gas_price * 100000 * len(addresses), 'ether')  # Rough estimate
    
    print(f"Current ETH balance: {eth_balance_eth:.6f} ETH")
    print(f"Estimated ETH needed for gas: {estimated_gas_eth:.6f} ETH")
    
    if eth_balance_eth < estimated_gas_eth:
        print(f"Warning: ETH balance might be too low for gas fees")
        response = input("Continue anyway? (yes/no): ")
        if response.lower() != 'yes':
            sys.exit(1)

    # Perform transfers
    print("\nStarting transfers...")
    success_count = 0
    
    for i, address in enumerate(addresses, 1):
        print(f"\nTransfer {i}/{len(addresses)} to {address}")
        receipt = transfer_tokens(web3, token_contract, args.from_key, address, args.amount, args.gas_price)
        
        if receipt:
            print(f"Success! Transaction hash: {receipt['transactionHash'].hex()}")
            success_count += 1
        else:
            print("Transfer failed!")
            sys.exit(1)  # Exit on first failure

    if success_count == len(addresses):
        print(f"\nAll transfers completed successfully! ({success_count}/{len(addresses)})")

if __name__ == "__main__":
    main() 