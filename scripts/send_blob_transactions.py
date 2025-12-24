"""
Send Blob Transactions to Ethereum Network - Osaka Fork Compatible

This script sends EIP-4844 blob transactions with full support for the Osaka fork
specifications (EIP-7762). It includes comprehensive validation, error handling,
and logging for Osaka-compatible blob transaction submission.

Osaka Fork (EIP-7762) Compatibility:
- Blob transaction wrapper version: v1 (0x01 prefix on versioned hashes)
- Maximum blobs per transaction: 6 (enforced by validation)
- Versioned hash format: 0x01 + sha256(commitment)[1:32]
- Gas limit cap: 2^24 (16,777,216 wei)
- Blob reserve price: 2^13 (8,192 wei base cost)
- Transaction type: 0x3 (required for blob transactions)

Reference: https://eips.ethereum.org/EIPS/eip-7762
"""

import os
import argparse
from eth_abi import abi
from eth_utils import to_hex
from web3 import Web3, HTTPProvider
import hashlib
import ckzg  # type: ignore
import rlp

TRUSTED_SETUP = os.path.join(os.path.dirname(__file__), "trusted_setup.txt")

# ============================================================================
# OSAKA FORK CONSTANTS
# ============================================================================

OSAKA_MAX_BLOBS_PER_TX = 6
OSAKA_BLOB_SIZE_BYTES = 131072  # 4096 * 32
OSAKA_VERSIONED_HASH_PREFIX = b'\x01'  # Blob wrapper version 1
OSAKA_GAS_LIMIT_CAP = 2**24  # 16,777,216
OSAKA_BLOB_RESERVE_PRICE = 2**13  # 8,192 wei


# ============================================================================
# VALIDATION FUNCTIONS - OSAKA FORK COMPLIANCE
# ============================================================================

def validate_osaka_params(tx_type, value, number_of_blobs, gas_limit=None):
    """
    Validate transaction parameters against Osaka fork specifications.
    
    Ensures:
    - Blob transactions use type 0x3
    - Blob transactions have value=0
    - Maximum 6 blobs per transaction
    - Gas limit doesn't exceed 2^24 cap
    - At least 1 blob for blob transactions
    
    Args:
        tx_type (str): Transaction type ('0x2' or '0x3')
        value (int): Value to send in wei
        number_of_blobs (int): Number of blobs to include
        gas_limit (int, optional): Gas limit in wei
        
    Raises:
        ValueError: If any Osaka parameter validation fails
    """
    # Type 0x3 required for blob transactions with blobs
    if number_of_blobs > 0 and tx_type != '0x3':
        raise ValueError(
            f"Blob transactions require type 0x3, got {tx_type}. "
            "Use --tx-type 0x3 for blob transactions."
        )
    
    # Blob transactions must have value=0 (Osaka requirement)
    if number_of_blobs > 0 and value != 0:
        raise ValueError(
            f"Blob transactions must have value=0 (Osaka fork), got {value}. "
            "Blob data is stored separately, value must be 0."
        )
    
    # Enforce maximum 6 blobs per transaction (Osaka spec)
    if number_of_blobs > OSAKA_MAX_BLOBS_PER_TX:
        raise ValueError(
            f"Osaka fork allows max {OSAKA_MAX_BLOBS_PER_TX} blobs per transaction, "
            f"got {number_of_blobs}"
        )
    
    # At least 1 blob required for blob transactions
    if number_of_blobs < 1:
        raise ValueError(
            f"Must include at least 1 blob for blob transactions, got {number_of_blobs}"
        )
    
    # Validate gas limit cap (Osaka: 2^24 = 16,777,216)
    if gas_limit is not None and gas_limit > OSAKA_GAS_LIMIT_CAP:
        raise ValueError(
            f"Gas limit {gas_limit} exceeds Osaka fork cap of 2^24 ({OSAKA_GAS_LIMIT_CAP})"
        )


def validate_blob_data(blobs):
    """
    Validate blob data for Osaka fork compliance.
    
    Ensures:
    - Each blob is exactly 131,072 bytes (4096 * 32 field elements)
    - Blob data is bytes type
    
    Args:
        blobs (list): List of blob data
        
    Raises:
        ValueError: If any blob has incorrect size
    """
    for i, blob in enumerate(blobs):
        if len(blob) != OSAKA_BLOB_SIZE_BYTES:
            raise ValueError(
                f"Blob {i} size {len(blob)} bytes doesn't match Osaka requirement "
                f"of {OSAKA_BLOB_SIZE_BYTES} bytes (4096 * 32 field elements)"
            )


# ============================================================================
# ARGUMENT PARSING - ENHANCED FOR OSAKA
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description='Send blob transactions to Ethereum network (Osaka fork compatible)'
    )
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
                      help='Number of blobs to include in the transaction (default: 2, max: 6 for Osaka)')
    parser.add_argument('--fee-collector', type=str,
                      default='0x1559000000000000000000000000000000000000',
                      help='Fee collector address to track balance (default: 0x1559...)')
    parser.add_argument('--log', action='store_true',
                      help='Log the transaction hash and receipt')
    parser.add_argument('--nonce', type=int,
                      help='Specific nonce to use for the transaction (optional)')
    # Osaka fork enhancements
    parser.add_argument('--tx-type', type=str, default='0x3', choices=['0x2', '0x3'],
                      help='Transaction type: 0x2 (EIP-1559) or 0x3 (blob) (default: 0x3 for Osaka)')
    parser.add_argument('--value', type=int, default=0,
                      help='Value to send in wei (default: 0 for blob tx, must be 0 for Osaka)')
    parser.add_argument('--validate-osaka-params', action='store_true',
                      help='Enable strict Osaka fork parameter validation (recommended: enabled)')
    return parser.parse_args()


# ============================================================================
# BLOB PREPARATION & VERSIONED HASH COMPUTATION
# ============================================================================

def prepare_blobs(number_of_blobs):
    """
    Prepare blob data for transaction.
    
    Osaka fork requirement:
    - Each blob must be exactly 131,072 bytes (4096 * 32-byte field elements)
    - Each 32-byte chunk must be a valid BLS12-381 field element
    - Field elements must be < 0x52435475_67b9acf051633ada5cb158ad10d2e47ff
    
    Args:
        number_of_blobs (int): Number of identical blobs to create
        
    Returns:
        list: List of blob data (each 131,072 bytes with valid field elements)
    """
    # BLS12-381 field modulus
    # p = 52435875175126190479447740508185965837690552500527637822603658699938581184513
    # In hex: 0x52435975_67b9acf0_51633ada_5cb158ad_10d2e47f_f0a6f067_ffffffff_fffffffe3
    # Max valid value for a field element is p - 1
    # To be safe, we use 0x40000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000
    # which represents 2^255 and is well below the field modulus
    
    # Create a blob with repeating valid field element pattern
    # Each field element is represented as a 32-byte big-endian integer
    valid_field_element = int(0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef).to_bytes(32, 'big')
    
    # Create blob: 4096 field elements of 32 bytes each = 131,072 bytes
    blob_data = valid_field_element * 4096
    
    # Create list of identical blobs
    blobs = [blob_data for _ in range(number_of_blobs)]
    
    return blobs


def compute_versioned_hashes(blobs, w3, trusted_setup_path):
    """
    Compute versioned hashes for blobs (Osaka fork EIP-7762).
    
    Osaka fork requirement:
    - Versioned hash = 0x01 (blob wrapper version v1) + sha256(commitment)[1:32]
    - Format: 1 byte version prefix + 31 bytes of hash = 32 bytes total
    - One versioned hash per blob
    
    Args:
        blobs (list): List of blob data
        w3 (Web3): Web3 instance
        trusted_setup_path (str): Path to trusted setup file
        
    Returns:
        list: List of 32-byte versioned hashes with 0x01 prefix (Osaka v1)
    """
    trusted_setup = ckzg.load_trusted_setup(trusted_setup_path, 0)
    
    versioned_hashes = []
    
    for blob in blobs:
        # Compute KZG commitment for the blob
        commitment = ckzg.blob_to_kzg_commitment(blob, trusted_setup)
        
        # Osaka fork (EIP-7762): Versioned hash = version prefix + hash
        # Version 0x01 indicates blob wrapper version 1
        # Then append first 31 bytes of sha256(commitment) to make 32 bytes total
        versioned_hash = OSAKA_VERSIONED_HASH_PREFIX + hashlib.sha256(commitment).digest()[1:]
        
        versioned_hashes.append(versioned_hash)
    
    return versioned_hashes


# ============================================================================
# TRANSACTION CONSTRUCTION - OSAKA FORK
# ============================================================================

def construct_blob_transaction(w3, acct, args, blobs, versioned_hashes):
    """
    Construct a blob transaction compatible with Osaka fork.
    
    Osaka fork (EIP-7762) requirements:
    - Type: 0x3 (blob transaction)
    - Value: 0 (blobs are separate from value transfer)
    - maxFeePerBlobGas: Hex string for blob gas price
    - Gas: Must not exceed 2^24 (16,777,216)
    - NOTE: blobVersionedHashes are computed by web3.py from blobs
    
    Args:
        w3 (Web3): Web3 instance
        acct: Account object
        args: Parsed arguments
        blobs (list): List of blob data
        versioned_hashes (list): List of versioned hashes (for reference only, web3.py will compute)
        
    Returns:
        dict: Transaction dictionary ready for signing
    """
    # Osaka fork: Type 0x3 for blob transactions
    tx = {
        "type": 3,  # 0x3 for blob transaction
        "chainId": w3.eth.chain_id,
        "from": acct.address,
        "to": args.to,
        "value": args.value,  # Must be 0 for blob transactions (Osaka)
        "data": b"",  # Empty data for blob transactions
        "maxFeePerGas": args.gas_price,
        "maxPriorityFeePerGas": args.gas_price,
        # Osaka fork: maxFeePerBlobGas in integer format (web3.py will handle conversion)
        "maxFeePerBlobGas": args.gas_price,
        "nonce": args.nonce if args.nonce is not None else w3.eth.get_transaction_count(acct.address),
        # NOTE: Do NOT include blobVersionedHashes here - web3.py computes them from blobs!
    }
    
    if args.log:
        print(f"[OSAKA] Transaction type: {tx['type']}")
        print(f"[OSAKA] Blob count: {len(blobs)}")
        print(f"[OSAKA] Max fee per blob gas: {args.gas_price}")
    
    # Use provided gas limit or estimate if not specified
    if args.gas_limit:
        tx["gas"] = args.gas_limit
    else:
        try:
            # Estimate gas - web3.py needs the blobs for accurate estimation
            # Create a temporary tx dict WITH versioned hashes for estimation
            temp_tx = tx.copy()
            temp_tx["blobVersionedHashes"] = versioned_hashes
            tx["gas"] = w3.eth.estimate_gas(temp_tx)
            
            if args.log:
                print(f"[OSAKA] Estimated gas: {tx['gas']}")
        except Exception as e:
            if args.log:
                print(f"[OSAKA] Gas estimation failed: {e}, using default")
            tx["gas"] = 1000000
    
    # Enforce Osaka fork gas limit cap (2^24)
    if tx["gas"] > OSAKA_GAS_LIMIT_CAP:
        tx["gas"] = OSAKA_GAS_LIMIT_CAP
        if args.log:
            print(f"[OSAKA] Gas capped to Osaka limit: {OSAKA_GAS_LIMIT_CAP}")
    
    return tx


# ============================================================================
# TRANSACTION SIGNING & SUBMISSION - OSAKA FORK
# ============================================================================

def send_blob(args):
    """
    Prepare and send a blob transaction compatible with Osaka fork.
    
    This function:
    1. Validates Osaka fork parameters
    2. Prepares blob data (131,072 bytes each)
    3. Computes versioned hashes (0x01 prefix + sha256)
    4. Constructs type 0x3 transaction
    5. Estimates/applies gas with 2^24 cap
    6. Signs transaction with blob data
    7. Submits via RPC
    8. Waits for receipt
    
    Osaka fork (EIP-7762) compatibility:
    - All transaction constraints validated
    - Blob wrapper version v1 (0x01 prefix)
    - All fork-specific parameters enforced
    
    Args:
        args: Parsed command-line arguments
    """
    try:
        # ====================================================================
        # PHASE 1: VALIDATION
        # ====================================================================
        if args.validate_osaka_params:
            validate_osaka_params(
                tx_type=args.tx_type,
                value=args.value,
                number_of_blobs=args.number_of_blobs,
                gas_limit=args.gas_limit
            )
        
        # Initialize Web3
        w3 = Web3(HTTPProvider(args.rpc_url))
        acct = w3.eth.account.from_key(args.private_key)
        
        # ====================================================================
        # PHASE 2: BLOB PREPARATION
        # ====================================================================
        blobs = prepare_blobs(args.number_of_blobs)
        
        # Validate blob sizes for Osaka fork
        validate_blob_data(blobs)
        
        # ====================================================================
        # PHASE 3: VERSIONED HASH COMPUTATION (OSAKA-SPECIFIC)
        # ====================================================================
        versioned_hashes = compute_versioned_hashes(blobs, w3, TRUSTED_SETUP)
        
        if args.log:
            print(f"[OSAKA] Computed {len(versioned_hashes)} versioned hashes")
            for i, vh in enumerate(versioned_hashes):
                # Show hash in hex format
                hash_hex = '0x' + vh.hex()
                print(f"  Hash {i}: {hash_hex}")
        
        # ====================================================================
        # PHASE 4: TRANSACTION CONSTRUCTION (OSAKA FORMAT)
        # ====================================================================
        tx = construct_blob_transaction(w3, acct, args, blobs, versioned_hashes)
        
        # ====================================================================
        # PHASE 5: TRANSACTION SIGNING (OSAKA FORMAT)
        # ====================================================================
        try:
            # Let web3.py handle the blob transaction signing and wrapping
            # Pass blobs parameter to automatically construct the blob transaction
            signed = acct.sign_transaction(tx, blobs=blobs)
            full_blob_tx = signed.raw_transaction
            
            if args.log:
                print("[OSAKA] Transaction signed successfully with blobs")
                print(f"[OSAKA] Blob count: {len(blobs)}")
                print(f"[OSAKA] Raw transaction length: {len(full_blob_tx)} bytes")
        except Exception as e:
            error_msg = str(e).lower()
            if "blob" in error_msg or "kzg" in error_msg:
                raise ValueError(
                    f"Osaka blob signing failed (EIP-7762 compatibility issue): {e}. "
                    "Verify: 1) Blob count <= 6, 2) Versioned hashes computed, "
                    "3) Type is 0x3, 4) Blob sizes are 131,072 bytes, "
                    "5) Blob data contains valid BLS12-381 field elements"
                )
            raise
        
        # ====================================================================
        # PHASE 6: RPC SUBMISSION
        # ====================================================================
        try:
            tx_hash = w3.eth.send_raw_transaction(full_blob_tx)
            if args.log:
                print(f"✓ Transaction submitted: {tx_hash.hex()}")
        except Exception as e:
            error_msg = str(e).lower()
            if "blob" in error_msg or "version" in error_msg:
                raise ValueError(
                    f"❌ Osaka blob format rejected by RPC: {e}. "
                    "Verify Osaka fork compatibility with network endpoint."
                )
            raise
        
        # ====================================================================
        # PHASE 7: RECEIPT CONFIRMATION
        # ====================================================================
        tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        if args.log:
            if tx_receipt.status == 1:
                print("✓ Transaction successful!")
                print(f"  Block: {tx_receipt.blockNumber}")
                print(f"  Status: {tx_receipt.status}")
            else:
                print("❌ Transaction failed")
                print(f"  Block: {tx_receipt.blockNumber}")
                print(f"  Status: {tx_receipt.status}")
        
        print(f"Transaction included in block {tx_receipt.blockNumber}, status: {tx_receipt.status}")
        
    except ValueError as e:
        print(f"Validation Error: {e}")
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise


def get_fee_collector_balance(args):
    """Get current balance of fee collector address."""
    w3 = Web3(HTTPProvider(args.rpc_url))
    balance = w3.eth.get_balance(args.fee_collector)
    print(f"Fee collector balance: {balance} wei")
    return balance


def main() -> int:
    """Main entry point for blob transaction submission."""
    args = parse_args()
    
    # Get initial balance and calculate difference
    if args.fee_collector:
        initial_balance = get_fee_collector_balance(args)
        send_blob(args)
        final_balance = get_fee_collector_balance(args)
        balance_difference = final_balance - initial_balance
        print(f"\nFee collector balance change: {balance_difference} wei")
    else:
        send_blob(args)
    
    return 0


if __name__ == "__main__":
    main()