from web3 import Web3
from eth_account import Account
from eth_utils import remove_0x_prefix, to_hex
from web3.types import HexStr, ChecksumAddress, Wei, TxParams, Nonce
import sys
import json
import argparse
from loguru import logger
from typing import Optional, Dict, Any, cast

def setup_logging(log_file: Optional[str] = None):
    """Configure loguru logger with console and optional file output"""
    # Remove default logger
    logger.remove()
    
    # Add console logger with color for INFO and above
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    # Add file logger if specified (includes DEBUG level)
    if log_file:
        logger.add(
            log_file,
            rotation="100 MB",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
            level="DEBUG"
        )

def parse_args():
    parser = argparse.ArgumentParser(description='Ethereum validator consolidation script')
    parser.add_argument('--rpc-url', required=True,
                      help='RPC URL for the Ethereum node')
    parser.add_argument('--private-key', required=True,
                      help='Private key for the transaction sender')
    parser.add_argument('--source-validator', required=True,
                      help='48-byte hex string of the source validator\'s public key')
    parser.add_argument('--target-validator', required=True,
                      help='48-byte hex string of the target validator\'s public key')
    parser.add_argument('--log-file',
                      help='Path to the log file (optional)')
    return parser.parse_args()

def print_curl_command(url: str, method: str, params: list):
    """Print equivalent curl command for debugging"""
    json_data = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1
    }
    curl_cmd = (
        f"curl -X POST -H 'Content-Type: application/json' "
        f"--data '{json.dumps(json_data)}' {url}"
    )
    logger.debug("\nEquivalent curl command:")
    logger.debug(curl_cmd)

def send_consolidation_transaction(
    web3: Web3,
    account: Account,
    account_address: ChecksumAddress,
    chain_id: int,
    validator_pubkey: str,
    target_pubkey: str,
    current_fee: int,
    contract_address: ChecksumAddress,
    rpc_url: str,
    private_key: str
) -> None:
    """Send a consolidation transaction with the given parameters."""
    # Create transaction data by concatenating the validator pubkeys (total 96 bytes)
    tx_data = HexStr('0x' + validator_pubkey + target_pubkey)
    
    # Additional validation of the final transaction data
    data_without_prefix = remove_0x_prefix(tx_data)
    total_bytes = len(data_without_prefix) // 2
    logger.debug("Transaction data validation:")
    logger.debug(f"Total length: {len(data_without_prefix)} characters ({total_bytes} bytes)")
    logger.debug(f"Expected: 192 characters (96 bytes)")
    logger.debug(f"Source validator part: {data_without_prefix[:96]}")
    logger.debug(f"Target validator part: {data_without_prefix[96:]}")
    
    if total_bytes != 96:
        raise ValueError(f"Invalid total transaction data length. Expected 96 bytes, got {total_bytes} bytes")
        
    logger.debug(f"Transaction data: {tx_data}")

    # Get nonce
    nonce = web3.eth.get_transaction_count(account_address)
    logger.debug(f"Nonce: {nonce}")

    # Prepare transaction
    transaction: TxParams = {
        'from': account_address,
        'to': contract_address,
        'value': Wei(current_fee),
        'gas': 200000,
        'gasPrice': web3.eth.gas_price,
        'nonce': Nonce(nonce),
        'chainId': chain_id,
        'data': tx_data
    }

    # Print transaction details
    logger.info("Transaction details:")
    for key, value in transaction.items():
        if key == 'value':
            logger.info(f"{key}: {value} wei ({web3.from_wei(value, 'ether')} ETH)") # type: ignore
        else:
            logger.info(f"{key}: {value}")

    # Sign transaction
    signed_txn = Account.sign_transaction(transaction, private_key)
    logger.info("Transaction signed successfully")
    logger.debug(f"Raw transaction: {signed_txn.raw_transaction.hex()}")
    
    # Send transaction
    try:
        tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
        logger.info(f"Transaction sent! Hash: {tx_hash.hex()}")

        # Wait for receipt
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
        logger.info("Transaction receipt:")
        logger.info(f"Status: {'Success' if receipt['status'] == 1 else 'Failed'}")
        logger.info(f"Block number: {receipt['blockNumber']}")
        logger.info(f"Gas used: {receipt['gasUsed']}")

        if receipt['status'] != 1:
            logger.error("Transaction reverted on-chain. Getting revert reason...")
            try:
                # For eth_call, we only need the basic transaction parameters
                call_params: TxParams = {
                    'from': account_address,
                    'to': contract_address,
                    'value': Wei(0),  # No value needed for call
                    'data': tx_data,
                    'gas': 200000,  # Add required fields for TxParams
                    'gasPrice': web3.eth.gas_price,
                    'nonce': Nonce(0),  # Nonce not needed for call
                    'chainId': chain_id
                }
                # Call at the block where the transaction was mined
                block_identifier = receipt['blockNumber']
                web3.eth.call(call_params, block_identifier)
            except Exception as e:
                logger.error(f"Revert reason: {str(e)}")

    except Exception as e:
        logger.error(f"Failed to send transaction: {e}")
        params = [signed_txn.raw_transaction.hex()]
        print_curl_command(rpc_url, 'eth_sendRawTransaction', params)

def main():
    try:
        args = parse_args()
        setup_logging(args.log_file)

        # Contract address from EIP-7251
        CONTRACT_ADDRESS = Web3.to_checksum_address('0x0000BBdDc7CE488642fb579F8B00f3a590007251')

        # Connect to Ethereum node
        web3 = Web3(Web3.HTTPProvider(args.rpc_url))
        if not web3.is_connected():
            raise ConnectionError("Failed to connect to the Ethereum network")

        logger.info("Connected to Ethereum network")
        chain_id = web3.eth.chain_id
        logger.info(f"Chain ID: {chain_id} (hex: {hex(chain_id)})")

        # Check if contract exists
        code = web3.eth.get_code(CONTRACT_ADDRESS)
        logger.info(f"Contract code exists: {len(code) > 0}")
        if len(code) > 0:
            logger.debug(f"Contract code length: {len(code)} bytes")
            logger.debug(f"Contract code: {code.hex()}")
        else:
            raise ValueError("Contract not deployed")

        # Account setup
        account = Account.from_key(args.private_key)
        account_address = Web3.to_checksum_address(account.address)
        logger.info(f"Account: {account_address}")
        balance = web3.eth.get_balance(account_address)
        logger.info(f"Balance: {balance} wei ({web3.from_wei(balance, 'ether')} ETH)")

        # Get current gas price and use a lower value
        gas_price = web3.eth.gas_price
        gas_price = int(gas_price * 0.8)  # Use 80% of current gas price
        logger.info(f"Current gas price: {gas_price} wei")

        # Get current consolidation fee
        try:
            current_fee = web3.eth.call({
                'to': CONTRACT_ADDRESS,
                'data': HexStr('0x')
            })
            current_fee = int.from_bytes(current_fee, byteorder='big')
            logger.info(f"Current consolidation fee: {current_fee} wei")

            # Ensure we're not sending 0 fee
            if current_fee == 0:
                logger.warning("Consolidation fee is 0, using 1 wei as minimum value")
                current_fee = 1
        except Exception as e:
            logger.error(f"Failed to retrieve the current consolidation fee: {e}")
            logger.warning("Using 1 wei as minimum value")
            current_fee = 1

        # Remove 0x prefixes from both validator pubkeys and ensure they are the correct length (96 hex characters for 48 bytes)
        source_pubkey = remove_0x_prefix(HexStr(args.source_validator))
        target_pubkey = remove_0x_prefix(HexStr(args.target_validator))

        if len(source_pubkey) != 96:
            raise ValueError(f"Invalid source validator pubkey length: {len(source_pubkey)}")
        if len(target_pubkey) != 96:
            raise ValueError(f"Invalid target validator pubkey length: {len(target_pubkey)}")

        # Validate pubkey formats
        try:
            int(source_pubkey, 16)
            int(target_pubkey, 16)
            logger.info("Source validator pubkey format is valid")
            logger.debug(f"Source pubkey length: {len(source_pubkey)} characters ({len(source_pubkey)//2} bytes)")
            logger.debug(f"First 32 bytes of source: {source_pubkey[:64]}")
            logger.debug(f"Last 16 bytes of source: {source_pubkey[-32:]}")

            logger.info("Target validator pubkey format is valid")
            logger.debug(f"Target pubkey length: {len(target_pubkey)} characters ({len(target_pubkey)//2} bytes)")
            logger.debug(f"First 32 bytes of target: {target_pubkey[:64]}")
            logger.debug(f"Last 16 bytes of target: {target_pubkey[-32:]}")
        except ValueError as e:
            raise ValueError(f"Invalid validator pubkey format: {e}")

        # Send first consolidation transaction
        logger.info("Sending consolidation request ...")
        send_consolidation_transaction(
            web3=web3,
            account=account,
            account_address=account_address,
            chain_id=chain_id,
            validator_pubkey=target_pubkey,
            target_pubkey=target_pubkey,
            current_fee=current_fee,
            contract_address=CONTRACT_ADDRESS,
            rpc_url=args.rpc_url,
            private_key=args.private_key
        )

        # Send second consolidation transaction
        logger.info("Sending consolidation transaction ...")
        send_consolidation_transaction(
            web3=web3,
            account=account,
            account_address=account_address,
            chain_id=chain_id,
            validator_pubkey=source_pubkey,
            target_pubkey=target_pubkey,
            current_fee=current_fee,
            contract_address=CONTRACT_ADDRESS,
            rpc_url=args.rpc_url,
            private_key=args.private_key
        )

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            error_details = e.args[0]
            if isinstance(error_details, dict):
                logger.error(f"Error code: {error_details.get('code')}")
                logger.error(f"Error message: {error_details.get('message')}")
            else:
                logger.error(f"Error details: {error_details}")
        sys.exit(1)

if __name__ == "__main__":
    main()