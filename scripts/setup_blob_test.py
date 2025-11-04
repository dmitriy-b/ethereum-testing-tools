#!/usr/bin/env python3

import os
import argparse
import json
from pathlib import Path
import subprocess

def setup_test_accounts(num_users: int, eth_amount: float, rpc_url: str, funder_key: str):
    """
    Set up test accounts for blob transaction testing.
    
    1. Generate new accounts
    2. Fund them with ETH
    3. Save account info for the test
    """
    # Check minimum ETH amount
    MIN_ETH_AMOUNT = 0.5  # 0.5 ETH minimum to cover blob transaction costs
    if eth_amount < MIN_ETH_AMOUNT:
        print(f"\nWARNING: Recommended minimum ETH amount is {MIN_ETH_AMOUNT} ETH per account for blob transactions")
        print(f"Current amount {eth_amount} ETH might be insufficient")
        response = input("Do you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborting setup")
            return None
    
    print(f"Setting up {num_users} test accounts...")
    
    # Create accounts directory if it doesn't exist
    accounts_dir = Path("accounts")
    accounts_dir.mkdir(exist_ok=True)
    
    # Generate accounts
    print("\n1. Generating new accounts...")
    gen_accounts_cmd = [
        "python3", "scripts/generate_account.py",
        "-n", str(num_users),
        "-o", "accounts",
        "-p", "blob_test_accounts",
        "--no-print"
    ]
    
    result = subprocess.run(gen_accounts_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error generating accounts: {result.stderr}")
        return None
    
    # Get the latest generated accounts file
    account_files = sorted(accounts_dir.glob("blob_test_accounts_*.json"))
    if not account_files:
        print("No account file found!")
        return None
    
    latest_account_file = account_files[-1]
    print(f"Accounts generated and saved to: {latest_account_file}")
    
    # Read the generated accounts
    with open(latest_account_file) as f:
        accounts = json.load(f)
    
    # Fund the accounts
    print(f"\n2. Funding {len(accounts)} accounts with {eth_amount} ETH each...")
    print(f"Total ETH needed: {eth_amount * len(accounts)} ETH")
    fund_cmd = [
        "python3", "scripts/transfer_eth.py",
        "--from-key", funder_key,
        "--to-file", str(latest_account_file),
        "--amount", str(eth_amount),
        "--rpc-url", rpc_url
    ]
    
    result = subprocess.run(fund_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error funding accounts: {result.stderr}")
        return None
    
    print("\nAccounts funded successfully!")
    
    # Save test configuration
    config = {
        "accounts_file": str(latest_account_file),
        "rpc_url": rpc_url,
        "num_users": num_users
    }
    
    config_file = accounts_dir / "current_test_config.json"
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=4)
    
    print(f"\nTest configuration saved to: {config_file}")
    print("\nSetup completed successfully!")
    return str(latest_account_file)

def main():
    parser = argparse.ArgumentParser(description='Set up accounts for blob transaction testing')
    parser.add_argument('--num-users', type=int, required=True,
                      help='Number of test users/accounts to create')
    parser.add_argument('--eth-amount', type=float, default=1.0,
                      help='Amount of ETH to fund each account with (default: 1.0 ETH)')
    parser.add_argument('--rpc-url', type=str, required=True,
                      help='RPC URL for the network')
    parser.add_argument('--funder-key', type=str, required=True,
                      help='Private key of the account that will fund the test accounts')
    
    args = parser.parse_args()
    
    setup_test_accounts(
        num_users=args.num_users,
        eth_amount=args.eth_amount,
        rpc_url=args.rpc_url,
        funder_key=args.funder_key
    )

if __name__ == "__main__":
    main() 