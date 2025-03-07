import sys
import json
import math
import argparse
from typing import cast, Optional

from web3 import HTTPProvider, Web3
from web3.types import HexStr
from web3.middleware import SignAndSendRawMiddlewareBuilder

EXCESS_INHIBITOR = 2**256 - 1

DECIMAL_FACTOR = 10**9


# From: https://eips.ethereum.org/EIPS/eip-7002#fee-calculation
def calculate_fee(factor: int, numerator: int, denominator: int) -> int:
    i = 1
    output = 0
    numerator_accum = factor * denominator
    while numerator_accum > 0:
        output += numerator_accum
        numerator_accum = (numerator_accum * numerator) // (denominator * i)
        i += 1
    return output // denominator


def send_withdrawal(
    w3: Web3,
    password: Optional[str],
    pubkey: str,
    amount: float,
    keystore_path: Optional[str] = None,
    contract_address: str = "0x00000961Ef480Eb55e80D19ad83579A64c007002",
    private_key: Optional[bytes] = None,
):
    # Check if this is a voluntary exit (amount = 0) or a withdrawal
    is_exit = amount == 0
    
    if is_exit:
        print(f"Preparing voluntary exit for validator {pubkey}")
    else:
        print(f"Preparing partial withdrawal of {amount} ETH for validator {pubkey}")
    
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

    # Validate withdrawal amount only if not an exit
    if not is_exit:
        if amount < 0:
            print("Error: Withdrawal amount must be greater than or equal to 0")
            return
        
        if amount >= 32:
            print("Warning: Attempting to withdraw 32 ETH or more. This may be a full withdrawal.")
            confirm = input("Continue? (y/n): ")
            if confirm.lower() != 'y':
                print("Withdrawal cancelled")
                return
    else:
        # For voluntary exit, show additional warning
        print("\nWARNING: Voluntary exit is IRREVERSIBLE!")
        print("Once your validator has exited, it cannot be reactivated.")
        print("You will be able to withdraw your stake after the exit is processed and finalized.")
        confirm = input("Are you ABSOLUTELY SURE you want to exit this validator? (y/n): ")
        if confirm.lower() != 'y':
            print("Voluntary exit cancelled")
            return

    excess = w3.eth.get_storage_at(
        Web3.to_checksum_address(contract_address),
        0,
    )
    excess_int = int(excess.hex(), 16)
    if excess_int == EXCESS_INHIBITOR:
        print("Excess inhibitor is set, cannot send withdrawal or exit")
        return
    withdrawal_fee = calculate_fee(
        factor=1,
        numerator=excess_int,
        denominator=17,
    )
    
    print(f"Transaction fee: {w3.from_wei(withdrawal_fee, 'gwei')} gwei ({w3.from_wei(withdrawal_fee, 'ether')} ETH)")
    
    if balance < withdrawal_fee:
        print(f"Insufficient funds. Need at least {w3.from_wei(withdrawal_fee, 'gwei')} gwei")
        print(f"Please send some ETH to address {account.address} to cover the transaction fee.")
        print("Note: This is NOT your validator address, but the address derived from your keystore file.")
        return

    # Convert amount to the correct format with DECIMAL_FACTOR
    real_amount = int(math.floor((amount * DECIMAL_FACTOR)))
    print(f"Encoded amount: {real_amount} (raw value)")
    
    withdrawal_tx_data = f"0x{pubkey[2:]}{hex(real_amount)[2:].zfill(16)}"
    
    if is_exit:
        print(f"Preparing transaction for voluntary exit")
    else:
        print(f"Preparing transaction for partial withdrawal of {amount} ETH")
    
    try:
        withdrawal_tx_hash = w3.eth.send_transaction(
            {
                "from": account.address,
                "to": Web3.to_checksum_address(contract_address),
                "value": Web3.to_wei(withdrawal_fee, 'wei'),
                "data": Web3.to_bytes(hexstr=cast(HexStr, withdrawal_tx_data)),
            }
        )
        print("Transaction sent successfully!")
        print("Transaction hash: 0x" + withdrawal_tx_hash.hex())
        if is_exit:
            print(f"Voluntary exit initiated. Check the transaction status on the blockchain explorer.")
            print("It may take several epochs (hours) for the exit to be processed on the beacon chain.")
        else:
            print(f"Partial withdrawal of {amount} ETH initiated. Check the transaction status on the blockchain explorer.")
    except Exception as e:
        print(f"Error sending transaction: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Send withdrawal or voluntary exit to Ethereum contract')
    parser.add_argument('--rpc-url', required=True, help='RPC URL for Ethereum node')
    parser.add_argument('--pubkey', required=True, help='Public key for withdrawal or exit')
    parser.add_argument('--amount', required=True, type=float, help='Amount to withdraw in ETH (use 0 for voluntary exit)')
    parser.add_argument('--keystore-path', 
                        default=None,
                        help='Path to keystore file')
    parser.add_argument('--private-key',
                        default=None,
                        help='Private key for transaction signing (alternative to keystore)')
    parser.add_argument('--contract-address', 
                        default="0x00000961Ef480Eb55e80D19ad83579A64c007002",
                        help='Withdrawals/exits contract address')
    parser.add_argument('--fund-account', action='store_true',
                        help='Only display the account address that needs funding, without attempting withdrawal/exit')
    
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
        print("to this address to cover the transaction fee.")
        print("\nAfter funding, run the script again without the --fund-account flag to perform the action.")
        sys.exit(0)
    
    # Validate amount
    if args.amount < 0:
        print("Error: Amount must be greater than or equal to 0")
        sys.exit(1)
    
    # Special validation for withdrawals (not exits)
    if args.amount > 0 and args.amount >= 32:
        print("Warning: You're attempting to withdraw 32 ETH or more, which may be a full withdrawal.")
        print("For partial withdrawals, the amount should be less than 32 ETH.")
        confirm = input("Continue anyway? (y/n): ")
        if confirm.lower() != 'y':
            print("Withdrawal cancelled")
            sys.exit(1)

    send_withdrawal(
        w3,
        password,
        args.pubkey,
        args.amount,
        args.keystore_path,
        args.contract_address,
        bytes.fromhex(args.private_key.replace('0x', '')) if args.private_key else None,
    )