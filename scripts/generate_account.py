"""Generate Ethereum accounts."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime
from typing import Iterable, Optional

from eth_account import Account


def generate_ethereum_account() -> dict[str, str]:
    """Create a random Ethereum account."""
    private_key = "0x" + secrets.token_hex(32)
    account = Account.from_key(private_key)
    return {"private_key": private_key, "public_key": account.address}


def generate_multiple_accounts(
    num_accounts: int,
    output_dir: Optional[str] = None,
    prefix: str = "eth_accounts",
    save_public: bool = False,
) -> list[dict[str, str]]:
    accounts: list[dict[str, str]] = [generate_ethereum_account() for _ in range(num_accounts)]

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        json_filename = f"{prefix}_{timestamp}.json"
        json_filepath = os.path.join(output_dir, json_filename)
        with open(json_filepath, "w", encoding="utf-8") as file:
            json.dump(accounts, file, indent=4)
        print(f"\nAccounts saved to: {json_filepath}")

        if save_public:
            txt_filename = f"{prefix}_public_{timestamp}.txt"
            txt_filepath = os.path.join(output_dir, txt_filename)
            with open(txt_filepath, "w", encoding="utf-8") as file:
                for account in accounts:
                    file.write(f"{account['public_key']}\n")
            print(f"Public keys saved to: {txt_filepath}")

    return accounts


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Ethereum accounts")
    parser.add_argument(
        "-n",
        "--num-accounts",
        type=int,
        default=1,
        help="Number of accounts to generate (default: 1)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        help="Directory to save the generated accounts",
    )
    parser.add_argument(
        "-p",
        "--prefix",
        type=str,
        default="eth_accounts",
        help="Prefix for the output file name (default: eth_accounts)",
    )
    parser.add_argument(
        "--no-print",
        action="store_true",
        help="Suppress printing accounts to console",
    )
    parser.add_argument(
        "--save-public",
        action="store_true",
        help="Save public keys to a separate .txt file",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)

    accounts = generate_multiple_accounts(
        args.num_accounts,
        args.output_dir,
        args.prefix,
        args.save_public,
    )

    if not args.no_print:
        print("\nGenerated Accounts Summary:")
        for index, account in enumerate(accounts, start=1):
            print(f"\nAccount {index}:")
            print(f"Private Key: {account['private_key']}")
            print(f"Public Key (Address): {account['public_key']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
