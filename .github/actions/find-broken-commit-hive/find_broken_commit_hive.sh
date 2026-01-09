#!/bin/bash

# Disable git pager for CI/automated environments
export GIT_PAGER=cat

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Global variables for configuration
REPO_URL=""
REPO_DIR=""
CLEANUP_REPO=false
HIVE_COMMAND=""

# Function to print colored messages
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to cleanup and restore original state
cleanup_and_exit() {
    local exit_code=$?
    log_info "Cleaning up..."

    if [ -n "$ORIGINAL_BRANCH" ]; then
        log_info "Returning to original branch/commit: $ORIGINAL_BRANCH"
        git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true
    fi

    # Restore stashed changes if any
    if git stash list | grep -q "Temporary stash by find_broken_commit_hive script"; then
        log_info "Restoring stashed changes..."
        git stash pop 2>/dev/null || log_warning "Could not restore stashed changes automatically"
    fi

    # Cleanup cloned repository if needed
    if [ "$CLEANUP_REPO" = true ] && [ -n "$REPO_DIR" ] && [ -d "$REPO_DIR" ]; then
        log_info "Cleaning up cloned repository: $REPO_DIR"
        cd /tmp
        rm -rf "$REPO_DIR"
    fi

    exit $exit_code
}

# Function to setup hive environment (called once)
setup_hive_environment() {
    log_info "Verifying Go installation..."
    if ! command -v go >/dev/null 2>&1; then
        log_error "Go is not installed. Please install Go first."
        exit 1
    fi
    go version

    log_info "Verifying Docker installation..."
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    docker --version
}

# Function to build and test hive at a specific commit
test_commit() {
    local commit_hash=$1
    local commit_date=$2
    local hive_command=$3
    local success_string=$4
    local error_string=$5
    local timeout_seconds=$6

    log_info "Testing commit: $commit_hash (Date: $commit_date)"

    # Checkout the commit
    if ! git checkout -q "$commit_hash" 2>&1; then
        log_error "Failed to checkout commit $commit_hash"
        # Try force checkout
        if ! git checkout -f -q "$commit_hash" 2>&1; then
            log_error "Force checkout also failed for commit $commit_hash"
            return 2
        fi
    fi

    # Clean previous build artifacts
    log_info "Cleaning previous build artifacts..."
    rm -f ./hive 2>/dev/null || true
    go clean -cache 2>/dev/null || true

    # Download dependencies
    log_info "Downloading Go dependencies..."
    if ! go get -v ./... > /tmp/go_get.log 2>&1; then
        log_warning "go get had warnings (may be normal)"
        cat /tmp/go_get.log | tail -10
    fi

    # Build hive
    log_info "Building hive..."
    if ! go build -v -o hive hive.go > /tmp/go_build.log 2>&1; then
        log_error "Go build failed for commit $commit_hash"
        cat /tmp/go_build.log | tail -20
        return 2
    fi

    if [ ! -f "./hive" ]; then
        log_error "Hive binary not found after build"
        return 2
    fi

    log_success "Hive built successfully"

    # Run hive tests
    log_info "Running hive command: $hive_command"
    
    local test_output_file="/tmp/commit_${commit_hash}_logs.txt"
    local test_exit_code=0

    # Run with timeout if specified
    if [ -n "$timeout_seconds" ] && [ "$timeout_seconds" -gt 0 ]; then
        log_info "Running with timeout: ${timeout_seconds}s"
        timeout "$timeout_seconds" bash -c "$hive_command" > "$test_output_file" 2>&1
        test_exit_code=$?
        if [ $test_exit_code -eq 124 ]; then
            log_warning "Test timed out after ${timeout_seconds}s"
        fi
    else
        bash -c "$hive_command" > "$test_output_file" 2>&1
        test_exit_code=$?
    fi

    log_info "Test exit code: $test_exit_code"

    # Check results based on exit code, success string, or error string
    local is_broken=false

    # First check exit code
    if [ $test_exit_code -ne 0 ] && [ $test_exit_code -ne 124 ]; then
        log_warning "Non-zero exit code: $test_exit_code"
        is_broken=true
    fi

    # Check for error string in output (if specified and not empty)
    if [ -n "$error_string" ]; then
        if grep -q "$error_string" "$test_output_file"; then
            log_error "Found error string in output: '$error_string'"
            is_broken=true
        fi
    fi

    # Check for success string in output (if specified and not empty)
    if [ -n "$success_string" ]; then
        if ! grep -q "$success_string" "$test_output_file"; then
            log_error "Success string not found in output: '$success_string'"
            is_broken=true
        else
            log_success "Found success string in output"
        fi
    fi

    # Show last lines of output for debugging
    log_info "Last 20 lines of test output:"
    tail -20 "$test_output_file"

    if [ "$is_broken" = true ]; then
        log_error "This commit is BROKEN"
        return 1  # Broken commit
    else
        log_success "This commit is GOOD"
        return 0  # Good commit
    fi
}

# Function to show usage
show_usage() {
    log_error "Usage: $0 --date <date> --hive-command <command> [OPTIONS]"
    log_error ""
    log_error "Required arguments:"
    log_error "  --date <date>              : Date when the tests started failing (e.g., '2024-10-01')"
    log_error "  --hive-command <command>   : Hive command to run (e.g., './hive --client nethermind --sim ethereum/engine')"
    log_error ""
    log_error "Optional arguments:"
    log_error "  --repo-url <url>           : Git repository URL to clone (default: https://github.com/ethereum/hive.git)"
    log_error "  --repo-branch <branch>     : Branch to checkout after cloning (default: master)"
    log_error "  --repo-token <token>       : GitHub token for private repositories"
    log_error "  --good-ref <ref>           : Known good commit/branch"
    log_error "  --bad-ref <ref>            : Known bad commit/branch (default: HEAD)"
    log_error "  --success-string <string>  : String that must be present in output for success"
    log_error "  --error-string <string>    : String in output that indicates failure"
    log_error "  --timeout <seconds>        : Timeout for each test run (default: 3600 = 1 hour)"
    log_error ""
    log_error "Examples:"
    log_error "  $0 --date '2024-10-01' --hive-command './hive --client nethermind --sim ethereum/engine'"
    log_error "  $0 --date '2024-10-01' --hive-command './hive --client geth --sim devp2p' --timeout 1800"
    log_error "  $0 --date '2024-10-01' --hive-command './hive --client nethermind' --error-string 'FAIL'"
    exit 1
}

# Main script
main() {
    # Parse named arguments
    local start_date=""
    local good_ref=""
    local bad_ref="HEAD"
    local hive_command=""
    local success_string=""
    local error_string=""
    local timeout_seconds="3600"
    local repo_url="https://github.com/ethereum/hive.git"
    local repo_branch="master"
    local repo_token=""

    # Parse command-line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --date)
                start_date="$2"
                shift 2
                ;;
            --hive-command)
                hive_command="$2"
                shift 2
                ;;
            --repo-url)
                repo_url="$2"
                shift 2
                ;;
            --repo-branch)
                repo_branch="$2"
                shift 2
                ;;
            --repo-token)
                repo_token="$2"
                shift 2
                ;;
            --good-ref)
                good_ref="$2"
                shift 2
                ;;
            --bad-ref)
                bad_ref="$2"
                shift 2
                ;;
            --success-string)
                success_string="$2"
                shift 2
                ;;
            --error-string)
                error_string="$2"
                shift 2
                ;;
            --timeout)
                timeout_seconds="$2"
                shift 2
                ;;
            --help|-h)
                show_usage
                ;;
            *)
                log_error "Unknown argument: $1"
                show_usage
                ;;
        esac
    done

    # Validate required arguments
    if [ -z "$start_date" ] || [ -z "$hive_command" ]; then
        log_error "Missing required arguments"
        show_usage
    fi

    # Setup environment first
    setup_hive_environment

    # Clone repository
    log_info "Cloning repository: $repo_url"
    
    # Prepare clone URL with token if provided
    local clone_url="$repo_url"
    if [ -n "$repo_token" ]; then
        # Insert token into URL (works for both github.com and other git hosts)
        if [[ "$repo_url" =~ ^https://github.com/ ]]; then
            clone_url="${repo_url/https:\/\//https://${repo_token}@}"
        elif [[ "$repo_url" =~ ^https:// ]]; then
            clone_url="${repo_url/https:\/\//https://${repo_token}@}"
        fi
    fi

    # Generate temporary directory name
    REPO_DIR="/tmp/hive_bisect_repo_$$"
    CLEANUP_REPO=true

    # Clone the repository
    if ! git clone "$clone_url" "$REPO_DIR" 2>&1; then
        log_error "Failed to clone repository"
        exit 1
    fi

    cd "$REPO_DIR" || exit 1
    log_success "Repository cloned successfully to $REPO_DIR"

    # Checkout specific branch if provided
    if [ -n "$repo_branch" ]; then
        log_info "Checking out branch: $repo_branch"
        if ! git checkout "$repo_branch" 2>&1; then
            log_error "Failed to checkout branch: $repo_branch"
            exit 1
        fi
    fi

    # Store original branch/commit to return to later
    ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ "$ORIGINAL_BRANCH" = "HEAD" ]; then
        ORIGINAL_BRANCH=$(git rev-parse HEAD)
    fi

    # Setup trap to cleanup on exit
    trap 'cleanup_and_exit' EXIT INT TERM

    log_info "Starting binary search for broken commit"
    log_info "Configuration:"
    log_info "  Repository: $repo_url"
    log_info "  Branch: $repo_branch"
    log_info "  Hive command: $hive_command"
    log_info "  Timeout: ${timeout_seconds}s"
    log_info "  Success string: '$success_string'"
    log_info "  Error string: '$error_string'"
    log_info "  Date when tests started failing: $start_date"

    # Validate references if provided
    if [ -n "$good_ref" ]; then
        if ! git rev-parse --verify "$good_ref" >/dev/null 2>&1; then
            log_error "Invalid good commit/branch reference: $good_ref"
            exit 1
        fi
    fi

    if ! git rev-parse --verify "$bad_ref" >/dev/null 2>&1; then
        log_error "Invalid bad commit/branch reference: $bad_ref"
        exit 1
    fi

    # Get all commits from the specified date to now
    log_info "Fetching commits..."

    # Build the git log command based on provided arguments
    if [ -n "$good_ref" ]; then
        # If good_ref is provided, use it as the starting point
        log_info "  From: $good_ref (or commits since $start_date)"
        log_info "  To: $bad_ref"

        # Get commits in the range, but also filter by date
        COMMITS=()
        while IFS= read -r line; do
            COMMITS+=("$line")
        done < <(git log --since="$start_date" "${good_ref}..${bad_ref}" --pretty=format:"%H" --reverse)
    else
        # Original behavior: get all commits since the date
        log_info "  From: $start_date"
        log_info "  To: $bad_ref"

        COMMITS=()
        while IFS= read -r line; do
            COMMITS+=("$line")
        done < <(git log --since="$start_date" "$bad_ref" --pretty=format:"%H" --reverse)
    fi

    if [ ${#COMMITS[@]} -eq 0 ]; then
        log_error "No commits found in the specified range"
        log_error ""
        log_error "Suggestions:"
        log_error "  1. Check if the date is correct"
        log_error "  2. Try an earlier date"
        if [ -n "$good_ref" ]; then
            log_error "  3. Verify that $good_ref exists and has commits after $start_date"
            log_error "  4. Check the range: git log --oneline ${good_ref}..${bad_ref}"
        fi
        exit 1
    fi

    if [ ${#COMMITS[@]} -eq 1 ]; then
        log_warning "Only 1 commit found in the range - cannot perform binary search"
        log_error ""
        log_error "You need at least 2 commits to perform binary search."
        log_error ""
        log_error "Suggestions:"
        log_error "  1. Use an earlier date to include more commits"
        log_error "  2. Specify a known good commit/branch:"
        log_error "     Example: --good-ref <good-commit>"
        log_error ""
        log_error "To find a good starting point, try:"
        log_error "  git log --oneline --since='$start_date'"
        exit 1
    fi

    log_info "Found ${#COMMITS[@]} commits to search through"
    log_info "Commit range:"
    log_info "  First (oldest): ${COMMITS[0]} - $(git log -1 --format='%ci' ${COMMITS[0]})"
    log_info "  Last (newest):  ${COMMITS[-1]} - $(git log -1 --format='%ci' ${COMMITS[-1]})"

    # Binary search variables
    left=0
    right=$((${#COMMITS[@]} - 1))
    last_good_commit=""
    first_broken_commit=""

    log_info "Starting binary search to find exact breaking point..."
    echo ""

    # Binary search until we narrow down to adjacent commits
    while [ $((right - left)) -gt 1 ]; do
        mid=$(( (left + right) / 2 ))
        commit_hash=${COMMITS[$mid]}
        commit_date=$(git show -s --format=%ci "$commit_hash")

        echo ""
        log_info "=========================================="
        log_info "Binary search iteration:"
        log_info "  Range: [$left, $right] (gap: $((right - left)) commits)"
        log_info "  Testing index: $mid"
        log_info "  Commit: $commit_hash"
        log_info "=========================================="
        echo ""

        # Test the commit
        test_commit "$commit_hash" "$commit_date" "$hive_command" "$success_string" "$error_string" "$timeout_seconds"
        result=$?

        echo ""
        log_info "Test result: $result (0=good, 1=broken, 2=error)"

        if [ $result -eq 1 ]; then
            # Commit is broken, search in the left half (earlier commits)
            log_warning "Commit is BROKEN. Searching earlier commits..."
            log_info "Updating range: right=$right -> $mid"
            right=$mid
        elif [ $result -eq 0 ]; then
            # Commit is good, search in the right half (later commits)
            log_success "Commit is GOOD. Searching later commits..."
            log_info "Updating range: left=$left -> $mid"
            left=$mid
        else
            # Error occurred during testing (build failure etc), move forward
            log_error "Error testing commit. Moving to next range..."
            log_info "Updating range: left=$left -> $((mid + 1))"
            left=$((mid + 1))
        fi

        log_info "New range will be: [$left, $right] (gap: $((right - left)))"
        sleep 2
    done

    # Now we have narrowed it down - left should be good, right should be broken
    # Let's verify both commits
    echo ""
    log_info "=========================================="
    log_info "Narrowed down to 2 adjacent commits!"
    log_info "Verifying the exact breaking point..."
    log_info "=========================================="
    echo ""

    # Verify left commit (should be good)
    if [ $left -ge 0 ] && [ $left -lt ${#COMMITS[@]} ]; then
        commit_hash=${COMMITS[$left]}
        commit_date=$(git show -s --format=%ci "$commit_hash")
        log_info "Verifying last potentially GOOD commit..."
        test_commit "$commit_hash" "$commit_date" "$hive_command" "$success_string" "$error_string" "$timeout_seconds"
        if [ $? -eq 0 ]; then
            last_good_commit=$commit_hash
            log_success "Confirmed: This is the LAST GOOD commit"
        fi
        echo ""
        sleep 2
    fi

    # Verify right commit (should be broken)
    if [ $right -ge 0 ] && [ $right -lt ${#COMMITS[@]} ]; then
        commit_hash=${COMMITS[$right]}
        commit_date=$(git show -s --format=%ci "$commit_hash")
        log_info "Verifying first potentially BROKEN commit..."
        test_commit "$commit_hash" "$commit_date" "$hive_command" "$success_string" "$error_string" "$timeout_seconds"
        if [ $? -eq 1 ]; then
            first_broken_commit=$commit_hash
            log_error "Confirmed: This is the FIRST BROKEN commit"
        fi
        echo ""
    fi

    # Return to original branch
    if [ -n "$ORIGINAL_BRANCH" ]; then
        log_info "Returning to original branch: $ORIGINAL_BRANCH"
        git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true
    fi

    echo ""
    echo "=========================================="
    echo "=========================================="
    if [ -n "$last_good_commit" ] && [ -n "$first_broken_commit" ]; then
        log_success "FOUND THE EXACT BREAKING POINT!"
        echo ""
        echo -e "${GREEN}✓ LAST GOOD COMMIT: $last_good_commit${NC}"
        echo ""
        git --no-pager log -1 --stat "$last_good_commit"
        echo ""
        echo "=========================================="
        echo ""
        echo -e "${RED}✗ FIRST BROKEN COMMIT: $first_broken_commit${NC}"
        echo ""
        git --no-pager log -1 --stat "$first_broken_commit"
        echo ""
        log_info "To see the diff between these commits:"
        echo "  git diff $last_good_commit $first_broken_commit"
        echo ""
        log_info "To see what changed in the breaking commit:"
        echo "  git show $first_broken_commit"
        echo ""
        log_info "Logs saved in:"
        echo "  /tmp/commit_${last_good_commit}_logs.txt (GOOD)"
        echo "  /tmp/commit_${first_broken_commit}_logs.txt (BROKEN)"
    elif [ -n "$first_broken_commit" ]; then
        log_success "FOUND THE FIRST BROKEN COMMIT!"
        echo ""
        echo -e "${RED}✗ FIRST BROKEN COMMIT: $first_broken_commit${NC}"
        echo ""
        git --no-pager log -1 --stat "$first_broken_commit"
        echo ""
        log_info "Logs saved in: /tmp/commit_${first_broken_commit}_logs.txt"
    else
        log_warning "Could not determine the exact breaking point"
        log_warning "The issue might require manual investigation"
    fi
    echo "=========================================="
    echo "=========================================="
}

# Run main function
main "$@"

