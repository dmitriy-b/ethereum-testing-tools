from web3 import Web3
import argparse
import json
from typing import List, Dict, Any
from web3.types import TxData
from hexbytes import HexBytes
from collections import Counter


def get_pending_pool_status(web3):
    """Get the status of the transaction pool including pending and queued transactions."""
    try:
        # Make direct JSON-RPC call to get txpool status
        response = web3.provider.make_request("txpool_status", [])
        
        if 'result' not in response:
            print("Error: No 'result' field in response")
            return
            
        status = response['result']
        pending = int(status.get('pending', '0'), 16) if isinstance(status.get('pending'), str) else status.get('pending', 0)
        queued = int(status.get('queued', '0'), 16) if isinstance(status.get('queued'), str) else status.get('queued', 0)
        
        print("\nTransaction pool status:")
        print(f"Pending transactions: {pending}")
        print(f"Queued transactions: {queued}")
        print(f"Total transactions: {pending + queued}")
            
    except Exception as e:
        print(f"Error getting pool status: {str(e)}")


def get_pending_pool_transactions(web3):
    """Get all pending transactions from the pool and count them by type."""
    try:
        # Make direct JSON-RPC call to get pending transactions
        response = web3.provider.make_request("eth_pendingTransactions", [])
        
        if 'result' not in response:
            print("Error: No 'result' field in response")
            return
            
        transactions = response['result']
        
        # Count transactions by type
        type_counter = Counter()
        for tx in transactions:
            tx_type = tx.get('type', '0x0')  # Default to '0x0' for legacy transactions
            type_counter[tx_type] += 1
            
        # Print results
        print("\nPending transactions by type:")
        total_txs = sum(type_counter.values())
        print(f"Total pending transactions: {total_txs}")
        
        for tx_type, count in sorted(type_counter.items()):
            type_name = {
                '0x0': 'Legacy',
                '0x1': 'Access List',
                '0x2': 'EIP-1559',
                '0x3': 'Blob'
            }.get(tx_type, f'Unknown ({tx_type})')
            
            percentage = (count / total_txs * 100) if total_txs > 0 else 0
            print(f"{type_name}: {count} ({percentage:.1f}%)")
            
    except Exception as e:
        print(f"Error getting pending pool transactions: {str(e)}")


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


def main():
    parser = argparse.ArgumentParser(description='Get pending transactions for an Ethereum account')
    parser.add_argument('--node-url', required=True, help='Ethereum node URL (e.g., Infura endpoint)')
    parser.add_argument('--address', help='Ethereum account address')
    parser.add_argument('--pool', action='store_true', help='Show pending transactions in the pool by type')
    parser.add_argument('--status', action='store_true', help='Show transaction pool status (pending and queued counts)')
    
    args = parser.parse_args()
    
    w3 = Web3(Web3.HTTPProvider(args.node_url))
    
    if args.status:
        get_pending_pool_status(w3)
    elif args.pool:
        get_pending_pool_transactions(w3)
    elif args.address:
        get_transaction_counts(w3, args.address)
    else:
        parser.error("One of --address, --pool, or --status must be specified")

if __name__ == "__main__":
    main() 