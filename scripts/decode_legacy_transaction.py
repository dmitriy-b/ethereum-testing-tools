from eth_account._utils.legacy_transactions import TypedTransaction
from hexbytes import HexBytes
import argparse


def print_transaction(path: str) -> None:
    tr = None
    with open(path, 'r') as f:
        tr = f.read()
    print(TypedTransaction.from_bytes(HexBytes(tr)).as_dict())  

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Parse legacy transaction and print output')
    parser.add_argument('-f', '--transaction-file', 
                        type=str, 
                        help='Txt file with transaction hash')
    args = parser.parse_args()
    print_transaction(args.transaction_file)