import os
import argparse
from web3 import Web3, HTTPProvider

def parse_args():
    parser = argparse.ArgumentParser(description='Send regular transactions to Ethereum network')
    parser.add_argument('--rpc-url', type=str, default='http://127.0.0.1:8545',
                      help='RPC URL (default: http://127.0.0.1:8545)')
    parser.add_argument('--private-key', type=str,
                      default='0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80',
                      help='Private key for the sending account')
    parser.add_argument('--gas-price', type=int, default=10**9,
                      help='Gas price in wei for legacy transactions (default: 1 Gwei)')
    parser.add_argument('--max-fee', type=int, default=10**9,
                      help='Max fee per gas in wei for EIP-1559 transactions (default: 1 Gwei)')
    parser.add_argument('--max-priority-fee', type=int, default=10**9,
                      help='Max priority fee per gas in wei for EIP-1559 transactions (default: 1 Gwei)')
    parser.add_argument('--gas-limit', type=int,
                      help='Gas limit for the transaction (if not specified, will be estimated)')
    parser.add_argument('--to', type=str,
                      default='0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
                      help='Recipient address')
    parser.add_argument('--value', type=int, default=0,
                      help='Amount of ETH to send in wei (default: 0)')
    parser.add_argument('--data', type=str, default='',
                      help='Transaction data in hex format (default: empty)')
    parser.add_argument('--tx-type', type=str, choices=['0x1', '0x2'], default='0x2',
                      help='Transaction type: 0x1 (legacy) or 0x2 (EIP-1559) (default: 0x2)')
    parser.add_argument('--log', action='store_true',
                      help='Log the transaction hash and receipt')
    return parser.parse_args()

def send_transaction(args):
    w3 = Web3(HTTPProvider(args.rpc_url))
    acct = w3.eth.account.from_key(args.private_key)

    # Base transaction parameters
    tx = {
        "from": acct.address,
        "to": args.to,
        "value": args.value,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
    }

    # Add data if provided
    if args.data:
        tx["data"] = args.data

    # Set transaction type specific parameters
    if args.tx_type == '0x1':
        tx["gasPrice"] = args.gas_price
    else:  # EIP-1559 transaction (0x2)
        tx["type"] = 2  # Explicitly set type for EIP-1559
        tx["maxFeePerGas"] = args.max_fee
        tx["maxPriorityFeePerGas"] = args.max_priority_fee

    # Use provided gas limit or estimate if not specified
    if args.gas_limit:
        tx["gas"] = args.gas_limit
    else:
        try:
            tx["gas"] = w3.eth.estimate_gas(tx)
            print(f"Estimated gas: {tx['gas']}")
        except Exception as e:
            print(f"Gas estimation failed: {e}")
            print("Using default gas limit of 21,000")
            tx["gas"] = 21000

    if args.log:
        print(f"Transaction details: {tx}")

    # Sign and send transaction
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    
    if args.log:
        print(f"Transaction hash: {tx_hash.hex()}")

    # Wait for transaction receipt
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if args.log:
        print(f"Transaction receipt: {tx_receipt}")
    
    print(f"Transaction included in block {tx_receipt.blockNumber}, status: {tx_receipt.status}")
    return tx_receipt

def main() -> int:
    args = parse_args()
    send_transaction(args)
    return 0

if __name__ == "__main__":
    main() 