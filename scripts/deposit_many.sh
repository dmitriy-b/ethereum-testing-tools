#!/bin/bash

if [ $# -ne 1 ]; then
    echo "Usage: $0 <number_of_deposits>"
    exit 1
fi

num_deposits=$1

# Validate input is a positive integer
if ! [[ "$num_deposits" =~ ^[0-9]+$ ]]; then
    echo "Error: Please provide a positive integer for number of deposits"
    exit 1
fi

echo "Making $num_deposits deposits..."

for ((i=1; i<=$num_deposits; i++))
do
    echo "Processing deposit $i of $num_deposits"
    docker run --rm --env-file $(pwd)/.env.chiado \
        -v validator_keys/deposit_data.json:/tmp/deposit_data.json \
        ghcr.io/gnosischain/deposit-script:latest /tmp/deposit_data.json
    
    # Add a small delay between deposits
    sleep 2
done

echo "Completed $num_deposits deposits"
