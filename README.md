# ethereum-testing-tools

A list of scripts to test ethereum based blockchains

## Ethereum Testing Tools

A collection of useful tools for Ethereum testing and development.

## Scripts

The `scripts` directory contains a variety of tools for interacting with Ethereum and related networks:

### Account Management

#### generate_account.py

Generate one or multiple Ethereum accounts.

```bash
python scripts/generate_account.py [OPTIONS]

Options:
  -n, --num-accounts    Number of accounts to generate (default: 1)
  -o, --output-dir      Directory to save the generated accounts
  -p, --prefix          Prefix for the output file name (default: eth_accounts)
  --no-print            Suppress printing accounts to console
  --save-public         Save public keys to a separate .txt file
```

#### get_public_key.py

Extract an Ethereum address from a private key.

```bash
python scripts/get_public_key.py [PRIVATE_KEY]
```

### Transaction Tools

#### send_transactions.py

Send regular transactions to Ethereum network.

```bash
python scripts/send_transactions.py [OPTIONS]

Options:
  --rpc-url             RPC URL for the Ethereum node (default: http://127.0.0.1:8545)
  --private-key         Private key for the sending account
  --gas-price           Gas price in wei for legacy transactions (default: 1 Gwei)
  --max-fee             Max fee per gas in wei for EIP-1559 transactions (default: 1 Gwei)
  --max-priority-fee    Max priority fee per gas for EIP-1559 transactions (default: 1 Gwei)
  --gas-limit           Gas limit for the transaction (estimated if not specified)
  --to                  Recipient address
  --value               Amount of ETH to send in wei (default: 0)
  --data                Transaction data in hex format (default: empty)
  --tx-type             Transaction type: 0x1 (legacy) or 0x2 (EIP-1559) (default: 0x2)
  --log                 Log the transaction hash and receipt
```

#### send_blob_transactions.py

Send blob transactions to Ethereum network (EIP-4844).

```bash
python scripts/send_blob_transactions.py [OPTIONS]

Options:
  --rpc-url             RPC URL for the Ethereum node (default: http://127.0.0.1:8545)
  --private-key         Private key for the sending account
  --gas-price           Gas price in wei (default: 1 Twei)
  --gas-limit           Gas limit for the transaction (estimated if not specified)
  --to                  Recipient address
  --number-of-blobs     Number of blobs to include in the transaction (default: 2)
  --fee-collector       Fee collector address to track balance
  --log                 Log the transaction hash and receipt
  --nonce               Specific nonce to use for the transaction (optional)
```

#### get_pending_transactions.py

Get information about pending transactions.

```bash
python scripts/get_pending_transactions.py [OPTIONS]

Options:
  --node-url            Ethereum node URL (required)
  --address             Ethereum account address to check pending transactions for
  --pool                Show pending transactions in the pool by type
  --status              Show transaction pool status (pending and queued counts)
```

### Transfer Tools

#### transfer_eth.py

Transfer ETH to one or multiple addresses.

```bash
python scripts/transfer_eth.py [OPTIONS]

Options:
  --from-key            Private key to send from (with 0x prefix) (required)
  --to                  Single address to send to
  --to-file             File containing addresses (one per line for .txt, or JSON format)
  --amount              Amount of ETH to send to each address (required)
  --gas-price           Gas price in Gwei (optional)
  --rpc-url             Custom RPC URL (required)
```

#### transfer_tokens.py

Transfer ERC-20 tokens to one or multiple addresses.

```bash
python scripts/transfer_tokens.py [OPTIONS]

Options:
  --from-key            Private key to send from (with 0x prefix) (required)
  --to                  Single address to send to
  --to-file             File containing addresses (one per line for .txt, or JSON format)
  --amount              Amount of tokens to send to each address (required)
  --token-address       Token contract address (required)
  --gas-price           Gas price in Gwei (optional)
  --rpc-url             Custom RPC URL (required)
```

### Validator Management

#### consolidation.py

Ethereum validator consolidation script for transferring stake from one validator to another (EIP-7251).

```bash
python scripts/consolidation.py [OPTIONS]

Options:
  --rpc-url             RPC URL for the Ethereum node (required)
  --private-key         Private key for the transaction sender (required)
  --source-validator    48-byte hex string of the source validator's public key (required)
  --target-validator    48-byte hex string of the target validator's public key (required)
  --log-file            Path to the log file (optional)
```

#### voluntary_exits.py
Submit a voluntary exit for an Ethereum validator.

```bash
python scripts/voluntary_exits.py [OPTIONS]

Options:
  --rpc-url             RPC URL for Ethereum node (required)
  --pubkey              Public key of the validator (required)
  --validator-index     Index of the validator on the beacon chain (required)
  --keystore-path       Path to keystore file
  --private-key         Private key for transaction signing (alternative to keystore)
  --contract-address    Voluntary exit contract address
  --fund-account        Only display the account address that needs funding
```

#### withdrawals.py
Send withdrawal or voluntary exit to Ethereum contract.

```bash
python scripts/withdrawals.py [OPTIONS]

Options:
  --rpc-url             RPC URL for Ethereum node (required)
  --pubkey              Public key for withdrawal or exit (required)
  --amount              Amount to withdraw in ETH (use 0 for voluntary exit) (required)
  --keystore-path       Path to keystore file
  --private-key         Private key for transaction signing (alternative to keystore)
  --contract-address    Withdrawals/exits contract address
  --fund-account        Only display the account address that needs funding
```

## Logs Directory

All log-related tools and scripts have been moved to the `logs` directory for better organization:

- Error log filtering scripts (filter_error_logs.sh, filter_error_logs_pretty.sh, filter_failed_replacement.sh)
- Grafana logs downloader scripts
- Test log files and jq scripts
- Multi-instance logs downloader and error filter script

## Work with docker

### Build docker image

```bash
docker build -t ethereum-testing-tools .
```

### Run any script in docker container

```bash
docker run -it ethereum-testing-tools [script_name] [OPTIONS]
```

for example:

```bash
docker run -v $(PWD)/accounts:/app/accounts --rm ethereum-testing-tools:latest scripts/generate_account.py -n 10 -o ./accounts -p devnet --save-public
```

### Passing environment variables to docker container

It is possible to use environment variables from .env file as arguments for the script. For this, you need to start container from `source .env && docker run --env-file=./.env` command.

In the example below, the script will use the value of `NUMBER_OF_ACCOUNTS` environment variable from `.env` file as the number of accounts to generate.

```bash
source .env && docker run --env-file=./.env -v $(PWD)/accounts:/app/accounts --rm ethereum-testing-tools:latest scripts/generate_account.py -n $NUMBER_OF_ACCOUNTS -o ./accounts -p devnet --save-public
```
