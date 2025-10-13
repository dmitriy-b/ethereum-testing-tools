#!/usr/bin/env python3

import argparse
import subprocess
import time
import sys
import shlex
import asyncio
import signal
import re
from typing import List, Optional, Tuple

def parse_blob_tx_command(command: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse a blob transaction command to extract private key and RPC URL.
    Returns (private_key, rpc_url) if it's a blob transaction command, (None, None) otherwise.
    """
    if not "send_blob_transactions.py" in command:
        return None, None
    
    # Clean up the command - remove newlines and extra spaces
    command = ' '.join(command.replace('\n', ' ').split())
    print(f"Parsing command: {command}")
    
    # Updated regex patterns to be more flexible
    private_key_pattern = r"--private-key\s+['\"]?(?:0x)?([a-fA-F0-9]{64})['\"]?"
    rpc_url_pattern = r"--rpc-url\s+['\"]?(https?://[^'\"\s]+)['\"]?"
    
    private_key_match = re.search(private_key_pattern, command)
    rpc_url_match = re.search(rpc_url_pattern, command)
    
    if private_key_match:
        private_key = '0x' + private_key_match.group(1)
        print(f"Found private key: {private_key}")
    else:
        print(f"Failed to extract private key. Pattern: {private_key_pattern}")
        print(f"Command segment: {command[:100]}...")
        return None, None
    
    if rpc_url_match:
        rpc_url = rpc_url_match.group(1)
        print(f"Found RPC URL: {rpc_url}")
    else:
        print(f"Failed to extract RPC URL. Pattern: {rpc_url_pattern}")
        print(f"Command segment: {command[:100]}...")
        return None, None
    
    return private_key, rpc_url

def get_current_nonce(private_key: str, rpc_url: str) -> int:
    """Get the current nonce for an account."""
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        account = w3.eth.account.from_key(private_key)
        return w3.eth.get_transaction_count(account.address, 'pending')
    except Exception as e:
        print(f"Error getting nonce: {e}")
        sys.exit(1)

async def execute_command_async(command: str, execution_number: int, total_executions: int, max_retries: int = 3) -> None:
    """
    Execute a single command asynchronously.
    
    Args:
        command (str): The command to execute
        execution_number (int): Current execution number
        total_executions (int): Total number of executions
        max_retries (int): Maximum number of retries for nonce errors
    """
    for attempt in range(max_retries):
        print(f"\nStarting execution {execution_number + 1}/{total_executions} (attempt {attempt + 1}/{max_retries})")
        print(f"Command: {command}")
        
        try:
            if sys.platform == "win32":
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            else:
                process = await asyncio.create_subprocess_exec(
                    *shlex.split(command),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                print(f"Execution {execution_number + 1} completed successfully")
                if stdout:
                    print(f"Output: {stdout.decode()}")
                return  # Success, exit the retry loop
            else:
                error_output = stderr.decode() if stderr else ""
                print(f"Error in execution {execution_number + 1}. Return code: {process.returncode}")
                if error_output:
                    print(f"Error output: {error_output}")
                
                # Check if it's a nonce error
                if "nonce too low" in error_output or "ALREADY_EXISTS" in error_output:
                    if attempt < max_retries - 1:
                        print("Nonce error detected, retrying with updated nonce...")
                        await asyncio.sleep(1)  # Short delay before retry
                        continue
                break  # Exit loop for non-nonce errors or if max retries reached
                    
        except Exception as e:
            print(f"Error during execution {execution_number + 1}: {e}")
            break

async def execute_commands_async(command: str, times: int, max_concurrent: int, delay: float) -> None:
    """
    Execute commands asynchronously with a limit on concurrent executions and delay between starts.
    
    Args:
        command (str): The command to execute
        times (int): Number of times to execute the command
        max_concurrent (int): Maximum number of concurrent executions
        delay (float): Delay in seconds between starting each command
    """
    # Check if this is a blob transaction command with {REPLACE} placeholder
    private_key, rpc_url = parse_blob_tx_command(command)
    
    if private_key and rpc_url and "{REPLACE}" in command:
        print("Using nonce replacement mode")
    else:
        if "{REPLACE}" in command:
            print("Error: {REPLACE} found but couldn't extract private key and RPC URL from command")
            sys.exit(1)
    
    # Create a semaphore to limit concurrent executions
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def bounded_execute(cmd: str, execution_number: int, total_executions: int) -> None:
        # Add delay before starting each command (except the first one)
        if execution_number > 0:
            print(f"Waiting {delay} seconds before starting execution {execution_number + 1}...")
            await asyncio.sleep(delay)
        
        # Replace nonce if needed
        current_cmd = cmd
        if private_key and rpc_url:
            # Get fresh nonce for each transaction
            current_nonce = get_current_nonce(private_key, rpc_url)
            current_cmd = cmd.replace("{REPLACE}", str(current_nonce))
            print(f"Using nonce {current_nonce} for execution {execution_number + 1}")
            
        async with semaphore:
            await execute_command_async(current_cmd, execution_number, total_executions)
    
    # Create tasks sequentially to maintain delay between starts
    tasks = []
    for i in range(times):
        task = asyncio.create_task(bounded_execute(command, i, times))
        tasks.append(task)
    
    await asyncio.gather(*tasks)

def execute_command(command: str, times: int, delay: float) -> None:
    """
    Execute a command multiple times with a delay between executions.
    
    Args:
        command (str): The command to execute
        times (int): Number of times to execute the command
        delay (float): Delay in seconds between executions
    """
    # Check if this is a blob transaction command with {REPLACE} placeholder
    private_key, rpc_url = parse_blob_tx_command(command)
    
    if private_key and rpc_url and "{REPLACE}" in command:
        print("Using nonce replacement mode")
    else:
        if "{REPLACE}" in command:
            print("Error: {REPLACE} found but couldn't extract private key and RPC URL from command")
            sys.exit(1)
    
    for i in range(times):
        print(f"\nExecution {i + 1}/{times}")
        
        # Replace nonce if needed
        current_command = command
        if private_key and rpc_url:
            # Get fresh nonce for each transaction
            current_nonce = get_current_nonce(private_key, rpc_url)
            current_command = command.replace("{REPLACE}", str(current_nonce))
            print(f"Using nonce {current_nonce} for execution {i + 1}")
        
        print(f"Command: {current_command}")
        
        try:
            # Use shlex.split for proper command parsing
            if sys.platform == "win32":
                process = subprocess.run(current_command, shell=True, check=True)
            else:
                process = subprocess.run(shlex.split(current_command), check=True)
            
            print(f"Execution {i + 1} completed successfully")
            
            # Don't delay after the last execution
            if i < times - 1:
                print(f"Waiting {delay} seconds before next execution...")
                time.sleep(delay)
                
        except subprocess.CalledProcessError as e:
            print(f"Error during execution {i + 1}: {e}")
            if input("Continue with next execution? (y/n): ").lower() != 'y':
                print("Execution stopped by user")
                break
        except KeyboardInterrupt:
            print("\nExecution interrupted by user")
            break

def main():
    parser = argparse.ArgumentParser(description="Execute a command multiple times with optional async execution")
    parser.add_argument("command", help="The command to execute (use quotes for commands with arguments). Use {REPLACE} for nonce replacement")
    parser.add_argument("-t", "--times", type=int, default=1, help="Number of times to execute the command (default: 1)")
    parser.add_argument("-d", "--delay", type=float, default=1.0, help="Delay in seconds between starting each command (default: 1.0)")
    parser.add_argument("--async", action="store_true", help="Execute commands asynchronously")
    parser.add_argument("-c", "--concurrent", type=int, default=3, help="Maximum number of concurrent executions in async mode (default: 3)")
    
    args = parser.parse_args()
    
    if getattr(args, 'async'):
        # Set up asyncio event loop with proper signal handling
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(
                execute_commands_async(args.command, args.times, args.concurrent, args.delay)
            )
        except KeyboardInterrupt:
            print("\nExecution interrupted by user")
            # Cancel all running tasks
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
        finally:
            loop.close()
    else:
        execute_command(args.command, args.times, args.delay)

if __name__ == "__main__":
    main() 