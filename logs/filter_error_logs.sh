#!/bin/bash

# Default JSON file
JSON_FILE="test_logs.json"

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "Error: jq is not installed. Please install it first."
    echo "You can install it with: brew install jq (on macOS)"
    exit 1
fi

# Default keywords
KEYWORDS="error exception fail timeout"

# Default fields to output (empty means output all)
FIELDS=""

# Process command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --file)
            # Specify JSON file
            shift
            if [[ $# -gt 0 ]]; then
                JSON_FILE="$1"
            else
                echo "Error: --file requires a file path"
                exit 1
            fi
            shift
            ;;
        --keywords)
            # Replace default keywords with custom ones
            shift
            if [[ $# -gt 0 ]]; then
                # Use the comma-separated list directly
                KEYWORDS=$(echo "$1" | tr ',' ' ')
            else
                echo "Error: --keywords requires a comma-separated list of keywords"
                exit 1
            fi
            shift
            ;;
        --add-keywords)
            # Add keywords to the default list
            shift
            if [[ $# -gt 0 ]]; then
                # Add to existing keywords
                ADDITIONAL=$(echo "$1" | tr ',' ' ')
                KEYWORDS="$KEYWORDS $ADDITIONAL"
            else
                echo "Error: --add-keywords requires a comma-separated list of keywords"
                exit 1
            fi
            shift
            ;;
        --fields)
            # Specify fields to output
            shift
            if [[ $# -gt 0 ]]; then
                FIELDS="$1"
            else
                echo "Error: --fields requires a comma-separated list of field names"
                exit 1
            fi
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --file FILE           Specify the JSON log file to process (default: test_logs.json)"
            echo "  --keywords KEYWORDS   Replace default keywords with a comma-separated list"
            echo "  --add-keywords KEYWORDS Add keywords to the default list (comma-separated)"
            echo "  --fields FIELDS       Specify which fields to output (comma-separated, e.g., 'log' or 'datetime,log')"
            echo "  --help                Show this help message"
            echo ""
            echo "Default keywords: error,exception,fail,timeout"
            echo "Available fields: timestamp, datetime, labels, log, or any nested field like labels.host"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check if the input file exists
if [ ! -f "$JSON_FILE" ]; then
    echo "Error: File '$JSON_FILE' not found."
    exit 1
fi

# Create a temporary jq script file
TMP_JQ_FILE=$(mktemp)

# Create a temporary output file
TMP_OUTPUT_FILE=$(mktemp)

# Write the jq filter to the temporary file
cat > "$TMP_JQ_FILE" << 'EOF'
# Filter logs where the log message contains any error patterns
.[] | 
select(
  # Standard log levels
  (.log | test(" ERROR\\|") or test(" WARN\\|") or test(" FATAL\\|") or test(" CRITICAL\\|"))
  
  # Keyword patterns will be added here
  
  # Detected level in labels
  or (.labels.detected_level == "error" or .labels.detected_level == "warn" or .labels.detected_level == "fatal" or .labels.detected_level == "critical")
) |
# Exclude false positives
select(
  (.log | test("method\\s+\\|\\s+successes\\s+\\|\\s+avg") | not)
)
EOF

# Add keyword patterns to the jq filter
for keyword in $KEYWORDS; do
    # Insert the keyword pattern after the "Keyword patterns will be added here" line
    sed -i.bak "/# Keyword patterns will be added here/a\\
  or (.log | test(\"(?i)${keyword}\"))" "$TMP_JQ_FILE"
done

# Add field selection if specified
if [ -n "$FIELDS" ]; then
    # Check if it's a single field request
    if [[ "$FIELDS" != *","* ]]; then
        # For a single field, output just the value without JSON formatting
        echo "| .$FIELDS" >> "$TMP_JQ_FILE"
        JQ_OPTS="-r"
    else
        # Convert comma-separated fields to jq format
        JQ_FIELDS=""
        IFS=',' read -ra FIELD_ARRAY <<< "$FIELDS"
        for field in "${FIELD_ARRAY[@]}"; do
            if [ -n "$JQ_FIELDS" ]; then
                JQ_FIELDS="$JQ_FIELDS, "
            fi
            JQ_FIELDS="$JQ_FIELDS\"$field\": .$field"
        done
        
        # Append field selection to the jq filter
        echo "| {$JQ_FIELDS}" >> "$TMP_JQ_FILE"
        JQ_OPTS=""
    fi
else
    JQ_OPTS=""
fi

# Run the jq filter and save to temporary output file
jq $JQ_OPTS -f "$TMP_JQ_FILE" "$JSON_FILE" > "$TMP_OUTPUT_FILE"

# Check if there was any output
if [ -s "$TMP_OUTPUT_FILE" ]; then
    # If there was output, display it
    cat "$TMP_OUTPUT_FILE"
else
    # If there was no output, display a message
    echo "No matching logs found for keywords: $KEYWORDS"
fi

# Clean up
rm "$TMP_JQ_FILE" "$TMP_JQ_FILE.bak" "$TMP_OUTPUT_FILE" 2>/dev/null

echo "Filtering complete." 