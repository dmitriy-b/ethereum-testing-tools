#!/bin/bash

rm -rf teku/
# Create teku directories first
mkdir -p teku/keystores
mkdir -p teku/secrets

# Copy only keystore files
cp validator_keys/keystore-*.json teku/

# Process each keystore file
for file in teku/keystore-*.json; do
    # Extract pubkey from the file
    pubkey=$(jq -r '.pubkey' "$file" | sed 's/^0x//')
    
    if [ -z "$pubkey" ]; then
        echo "Error: Could not extract pubkey from $file"
        continue
    fi
    
    # Rename the keystore file
    mv "$file" "teku/keystores/${pubkey}.json"
    echo "Renamed $file to teku/keystores/${pubkey}.json"
    
    # Create the password file
    echo "chiadovalidator" > "teku/secrets/${pubkey}.txt"
    echo "Created teku/secrets/${pubkey}.txt"
done