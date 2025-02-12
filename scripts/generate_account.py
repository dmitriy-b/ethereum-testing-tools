from eth_account import Account
import secrets
import argparse
import json
import os
from datetime import datetime

def generate_ethereum_account():
    # Generate a random private key
    private_key = "0x" + secrets.token_hex(32)

    # Create an account from the private key
    account = Account.from_key(private_key)

    # Get the public key (address)
    public_key = account.address
    return {
        "private_key": private_key,
        "public_key": public_key
    }

def generate_multiple_accounts(num_accounts, output_dir=None, prefix='eth_accounts', save_public=False):
    accounts = []
    for _ in range(num_accounts):
        account = generate_ethereum_account()
        accounts.append(account)
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save full accounts to JSON
        json_filename = f"{prefix}_{timestamp}.json"
        json_filepath = os.path.join(output_dir, json_filename)
        with open(json_filepath, 'w') as f:
            json.dump(accounts, f, indent=4)
        print(f"\nAccounts saved to: {json_filepath}")
        
        # Save public keys to txt if requested
        if save_public:
            txt_filename = f"{prefix}_public_{timestamp}.txt"
            txt_filepath = os.path.join(output_dir, txt_filename)
            with open(txt_filepath, 'w') as f:
                for account in accounts:
                    f.write(f"{account['public_key']}\n")
            print(f"Public keys saved to: {txt_filepath}")
    
    return accounts

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate Ethereum accounts')
    parser.add_argument('-n', '--num-accounts', 
                        type=int, 
                        default=1,
                        help='Number of accounts to generate (default: 1)')
    parser.add_argument('-o', '--output-dir', 
                        type=str,
                        help='Directory to save the generated accounts')
    parser.add_argument('-p', '--prefix',
                        type=str,
                        default='eth_accounts',
                        help='Prefix for the output file name (default: eth_accounts)')
    parser.add_argument('--no-print',
                        action='store_true',
                        help='Suppress printing accounts to console')
    parser.add_argument('--save-public',
                        action='store_true',
                        help='Save public keys to a separate .txt file')

    args = parser.parse_args()

    accounts = generate_multiple_accounts(
        args.num_accounts,
        args.output_dir,
        args.prefix,
        args.save_public
    )

    if not args.no_print:
        print("\nGenerated Accounts Summary:")
        for i, account in enumerate(accounts, 1):
            print(f"\nAccount {i}:")
            print(f"Private Key: {account['private_key']}")
            print(f"Public Key (Address): {account['public_key']}")