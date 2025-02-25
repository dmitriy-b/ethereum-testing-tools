from web3 import Web3
import argparse
import json
from eth_account import Account
import sys
from pathlib import Path
import time

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
        # Direct JSON-RPC calls for more detailed information
        latest = web3.eth.get_transaction_count(address, 'latest')
        pending = web3.eth.get_transaction_count(address, 'pending')
        
        # Try direct eth_getTransactionCount calls
        latest_direct = web3.provider.make_request("eth_getTransactionCount", [address, "latest"])
        pending_direct = web3.provider.make_request("eth_getTransactionCount", [address, "pending"])
        
        print("\nTransaction count details:")
        print(f"Latest (standard): {latest}")
        print(f"Pending (standard): {pending}")
        print(f"Latest (direct): {int(latest_direct['result'], 16) if 'result' in latest_direct else 'N/A'}")
        print(f"Pending (direct): {int(pending_direct['result'], 16) if 'result' in pending_direct else 'N/A'}")
        
        # Try to get pending transactions
        try:
            pending_block = web3.eth.get_block('pending', full_transactions=True)
            if pending_block and 'transactions' in pending_block:
                addr_pending_txs = [tx for tx in pending_block['transactions'] 
                                  if isinstance(tx, dict) and tx.get('from', '').lower() == address.lower()]
                print(f"Pending transactions found in block: {len(addr_pending_txs)}")
                for tx in addr_pending_txs:
                    print(f"Pending tx: nonce={tx.get('nonce', 'N/A')}, hash={tx.get('hash', 'N/A').hex()}")
        except Exception as e:
            print(f"Could not get pending block: {str(e)}")
        
        # Return the highest nonce we found plus 1
        all_nonces = [latest, pending]
        if 'result' in latest_direct:
            all_nonces.append(int(latest_direct['result'], 16))
        if 'result' in pending_direct:
            all_nonces.append(int(pending_direct['result'], 16))
        
        return max(all_nonces)
        
    except Exception as e:
        print(f"Error getting transaction counts: {str(e)}")
        return web3.eth.get_transaction_count(address, 'latest')

def check_transaction_status(web3, tx_hash, timeout=60):
    """Check transaction status with timeout."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            tx_receipt = web3.eth.get_transaction_receipt(tx_hash)
            if tx_receipt is not None:
                return tx_receipt
        except Exception:
            pass
        time.sleep(2)
    return None

def cancel_pending_transactions(web3, from_private_key, start_nonce, end_nonce):
    """Cancel pending transactions by sending 0 ETH transactions to self with higher gas price."""
    account = Account.from_key(from_private_key)
    from_address = account.address
    
    print(f"\nAttempting to cancel transactions with nonces from {start_nonce} to {end_nonce}")
    
    # Get current gas price and use 5x for cancellation
    gas_price = web3.eth.gas_price
    cancel_gas_price = gas_price * 5
    
    for nonce in range(start_nonce, end_nonce + 1):
        try:
            # Create cancellation transaction (send 0 ETH to self)
            transaction = {
                'nonce': nonce,
                'to': from_address,  # Send to self
                'value': 0,  # 0 ETH
                'gas': 21000,
                'gasPrice': cancel_gas_price,
                'chainId': web3.eth.chain_id
            }
            
            # Sign and send cancellation transaction
            signed_txn = web3.eth.account.sign_transaction(transaction, from_private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            print(f"Cancellation transaction sent for nonce {nonce}, hash: {tx_hash.hex()}")
            
            # Wait for the cancellation to be mined
            tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            if tx_receipt.status == 1:
                print(f"Successfully cancelled transaction with nonce {nonce}")
            else:
                print(f"Cancellation failed for nonce {nonce}")
                
        except Exception as e:
            print(f"Error cancelling nonce {nonce}: {str(e)}")
            continue
            
    print("Cancellation attempts completed")
    time.sleep(5)  # Wait for cancellations to propagate

def transfer_eth(web3, from_private_key, to_address, amount_eth, gas_price_gwei=None, max_retries=3):
    """Transfer ETH to a single address."""
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
            # Get fresh nonce after cancellation
            nonce = web3.eth.get_transaction_count(from_address, 'latest')
        else:
            nonce = pending_nonce
    else:
        nonce = latest_nonce
    
    print(f"Starting with nonce: {nonce}")
    
    for attempt in range(max_retries):
        try:
            # Convert ETH amount to Wei
            amount_wei = web3.to_wei(amount_eth, 'ether')

            # Prepare basic transaction
            transaction = {
                'nonce': nonce,
                'to': to_address,
                'value': amount_wei,
                'gas': 21000,
                'chainId': web3.eth.chain_id
            }

            # Set gas price - use higher gas price by default
            if gas_price_gwei:
                transaction['gasPrice'] = web3.to_wei(gas_price_gwei, 'gwei')
            else:
                gas_price = web3.eth.gas_price
                transaction['gasPrice'] = int(gas_price * 2)  # Use 2x gas price by default

            print(f"\nTransaction details:")
            print(f"From: {from_address}")
            print(f"To: {to_address}")
            print(f"Value: {web3.from_wei(amount_wei, 'ether')} ETH")
            print(f"Gas Price: {web3.from_wei(transaction['gasPrice'], 'gwei')} Gwei")
            print(f"Nonce: {nonce}")

            # Sign and send transaction
            signed_txn = web3.eth.account.sign_transaction(transaction, from_private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
            last_tx_hash = tx_hash
            print(f"Transaction sent with nonce {nonce}, hash: {tx_hash.hex()}")
            
            # Wait for transaction receipt
            tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            if tx_receipt and tx_receipt.status == 1:
                return tx_receipt
            else:
                raise Exception("Transaction failed or timed out")

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
    parser = argparse.ArgumentParser(description='Transfer ETH to one or multiple addresses')
    parser.add_argument('--from-key', required=True, help='Private key to send from (with 0x prefix)')
    parser.add_argument('--to', help='Single address to send to')
    parser.add_argument('--to-file', help='File containing addresses (one per line for .txt, or JSON format)')
    parser.add_argument('--amount', type=float, required=True, help='Amount of ETH to send to each address')
    parser.add_argument('--gas-price', type=float, help='Gas price in Gwei (optional)')
    parser.add_argument('--rpc-url', help='Custom RPC URL (required)')

    args = parser.parse_args()

    if not args.to and not args.to_file:
        parser.error("Either --to or --to-file must be specified")

    if args.to and args.to_file:
        parser.error("Cannot specify both --to and --to-file")

    if not args.rpc_url:
        parser.error("--rpc-url is required for Gnosis chain")

    # Setup web3 connection
    web3 = Web3(Web3.HTTPProvider(args.rpc_url))

    if not web3.is_connected():
        print("Error: Could not connect to Gnosis network")
        sys.exit(1)

    # Get chain ID for display
    try:
        chain_id = web3.eth.chain_id
        print(f"Connected to Gnosis network with chain ID: {chain_id}")
    except Exception as e:
        print(f"Warning: Could not get chain ID: {str(e)}")
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

    # Check balance
    account = Account.from_key(args.from_key)
    balance = web3.eth.get_balance(account.address)
    balance_eth = web3.from_wei(balance, 'ether')
    total_needed = args.amount * len(addresses)

    print(f"\nSender address: {account.address}")
    print(f"Current balance: {balance_eth:.6f} ETH")
    print(f"Total ETH needed: {total_needed:.6f} ETH")
    print(f"Number of addresses to send to: {len(addresses)}")

    if balance_eth < total_needed:
        print(f"Error: Insufficient balance. Need {total_needed:.6f} ETH but only have {balance_eth:.6f} ETH")
        sys.exit(1)

    # Perform transfers
    print("\nStarting transfers...")
    success_count = 0
    
    for i, address in enumerate(addresses, 1):
        print(f"\nTransfer {i}/{len(addresses)} to {address}")
        receipt = transfer_eth(web3, args.from_key, address, args.amount, args.gas_price)
        
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