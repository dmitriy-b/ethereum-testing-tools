import os
import argparse
from eth_abi import abi          # for encoding data into ABI format
from eth_utils import to_hex     # for converting values to hex
from web3 import Web3, HTTPProvider

def parse_args():
    parser = argparse.ArgumentParser(description='Send blob transactions to Ethereum network')
    parser.add_argument('--rpc-url', type=str, default='http://127.0.0.1:8545',
                      help='RPC URL (default: http://127.0.0.1:8545)')
    parser.add_argument('--private-key', type=str,
                      default='0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80',
                      help='Private key for the sending account')
    parser.add_argument('--gas-price', type=int, default=10**12,
                      help='Gas price in wei (default: 1 Twei)')
    parser.add_argument('--gas-limit', type=int,
                      help='Gas limit for the transaction (if not specified, will be estimated)')
    parser.add_argument('--to', type=str,
                      default='0x25D5FA335D952FdCa821EE415de414C15Eb3eFAd',
                      help='Recipient address (default: 0x25D5FA335D952FdCa821EE415de414C15Eb3eFAd)')
    parser.add_argument('--number-of-blobs', type=int, default=2,
                      help='Number of blobs to include in the transaction (default: 2)')
    return parser.parse_args()

def send_blob(args):
    w3 = Web3(HTTPProvider(args.rpc_url))

    text = "<( o.O )>"
    encoded_text = abi.encode(["string"], [text])

    print("Text:", encoded_text)

    # Blob data must be comprised of 4096 32-byte field elements
    # So yeah, blobs must be pretty big
    BLOB_DATA = (b"\x00" * 32 * (4096 - len(encoded_text) // 32)) + encoded_text
    # Create list of blobs based on number_of_blobs argument
    blobs = [BLOB_DATA for _ in range(args.number_of_blobs)]

    acct = w3.eth.account.from_key(args.private_key)

    tx = {
        "type": 3,
        "chainId": w3.eth.chain_id,  # Anvil
        "from": acct.address,
        "to": args.to,
        "value": 0,
        "maxFeePerGas": args.gas_price,
        "maxPriorityFeePerGas": args.gas_price,
        "maxFeePerBlobGas": to_hex(args.gas_price),
        "nonce": w3.eth.get_transaction_count(acct.address),
    }

    # Use provided gas limit or estimate if not specified
    if args.gas_limit:
        tx["gas"] = args.gas_limit
    else:
        try:
            tx["gas"] = w3.eth.estimate_gas(tx)
            print(f"Estimated gas: {tx['gas']}")
        except Exception as e:
            print(f"Gas estimation failed: {e}")
            print("Using default gas limit of 1,000,000")
            tx["gas"] = 1000000

    signed = acct.sign_transaction(tx, blobs=blobs)

    print("Signed Transaction:", signed, "\n")

    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Transaction hash: {tx_hash.hex()}")

    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Tx receipt: {tx_receipt}")
    print(f"Transaction included in block {tx_receipt.blockNumber}, status: {tx_receipt.status}")


def main() -> int:
    args = parse_args()
    send_blob(args)
    return 0


if __name__ == "__main__":
    main()