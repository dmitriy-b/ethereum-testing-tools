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
CLIENT_REPO_URL=""
CLIENT_REPO_DIR=""
CLEANUP_CLIENT_REPO=false
HIVE_DIR=""
CLEANUP_HIVE=false
DOCKER_IMAGE_NAME=""

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

    # Cleanup local Docker image
    if [ -n "$DOCKER_IMAGE_NAME" ]; then
        log_info "Cleaning up Docker image: $DOCKER_IMAGE_NAME"
        docker rmi -f "$DOCKER_IMAGE_NAME" 2>/dev/null || true
    fi

    # Cleanup Docker images built by Hive
    log_info "Cleaning up Hive-built Docker images..."
    docker images --filter "reference=hive/clients/*" -q | xargs -r docker rmi -f 2>/dev/null || true
    docker images --filter "reference=hive/simulators/*" -q | xargs -r docker rmi -f 2>/dev/null || true
    
    # Clean dangling images and build cache
    log_info "Cleaning up Docker build cache and dangling images..."
    docker image prune -f 2>/dev/null || true
    docker builder prune -f --all 2>/dev/null || true
    docker system prune -f 2>/dev/null || true

    if [ -n "$ORIGINAL_BRANCH" ] && [ -d "$CLIENT_REPO_DIR" ]; then
        cd "$CLIENT_REPO_DIR"
        log_info "Returning to original branch/commit: $ORIGINAL_BRANCH"
        git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true

        # Restore stashed changes if any
        if git stash list | grep -q "Temporary stash by find_broken_commit_hive script"; then
            log_info "Restoring stashed changes..."
            git stash pop 2>/dev/null || log_warning "Could not restore stashed changes automatically"
        fi
    fi

    # Cleanup cloned client repository if needed
    if [ "$CLEANUP_CLIENT_REPO" = true ] && [ -n "$CLIENT_REPO_DIR" ] && [ -d "$CLIENT_REPO_DIR" ]; then
        log_info "Cleaning up cloned client repository: $CLIENT_REPO_DIR"
        rm -rf "$CLIENT_REPO_DIR"
    fi

    # Cleanup cloned hive repository if needed
    if [ "$CLEANUP_HIVE" = true ] && [ -n "$HIVE_DIR" ] && [ -d "$HIVE_DIR" ]; then
        log_info "Cleaning up cloned hive repository: $HIVE_DIR"
        rm -rf "$HIVE_DIR"
    fi

    exit $exit_code
}

# Function to setup hive (called once)
setup_hive() {
    local hive_repo_url=$1
    local hive_branch=$2
    local repo_token=$3

    log_info "Setting up Hive..."

    # Generate temporary directory name for hive
    HIVE_DIR="/tmp/hive_$$"
    CLEANUP_HIVE=true

    # Prepare clone URL with token if provided
    local clone_url="$hive_repo_url"
    if [ -n "$repo_token" ]; then
        if [[ "$hive_repo_url" =~ ^https:// ]]; then
            clone_url="${hive_repo_url/https:\/\//https://${repo_token}@}"
        fi
    fi

    # Clone hive repository
    log_info "Cloning Hive repository: $hive_repo_url"
    if ! git clone "$clone_url" "$HIVE_DIR" 2>&1; then
        log_error "Failed to clone Hive repository"
        exit 1
    fi

    cd "$HIVE_DIR" || exit 1

    # Checkout specific branch if provided
    if [ -n "$hive_branch" ]; then
        log_info "Checking out Hive branch: $hive_branch"
        if ! git checkout "$hive_branch" 2>&1; then
            log_error "Failed to checkout Hive branch: $hive_branch"
            exit 1
        fi
    fi

    # Download Go dependencies
    log_info "Downloading Hive Go dependencies..."
    if ! go get -v ./... > /tmp/hive_go_get.log 2>&1; then
        log_warning "go get had warnings (may be normal)"
        tail -10 /tmp/hive_go_get.log
    fi

    # Build hive
    log_info "Building Hive..."
    if ! go build -v -o hive hive.go > /tmp/hive_go_build.log 2>&1; then
        log_error "Failed to build Hive"
        cat /tmp/hive_go_build.log
        exit 1
    fi

    if [ ! -f "./hive" ]; then
        log_error "Hive binary not found after build"
        exit 1
    fi

    log_success "Hive setup complete at $HIVE_DIR"
}

# Function to create hive config for local image
# Hive's existing Dockerfiles already support baseimage/tag build args
create_hive_config() {
    local client_name=$1
    local docker_image=$2
    local config_file="$HIVE_DIR/configs/custom_client.yaml"

    log_info "Creating Hive config for client: $client_name"
    log_info "  Using local Docker image: $docker_image"

    # Ensure configs directory exists
    mkdir -p "$(dirname "$config_file")"

    # Extract image name and tag
    local baseimage="${docker_image%:*}"
    local tag="${docker_image##*:}"
    if [ "$baseimage" = "$docker_image" ]; then
        tag="latest"
    fi

    # Create config - Hive's existing Dockerfile supports baseimage/tag
    cat > "$config_file" << EOF
- client: $client_name
  build_args:
    baseimage: $baseimage
    tag: $tag
EOF

    log_info "Created config file: $config_file"
    cat "$config_file"
}

# Function to extract github repo from URL
# e.g., https://github.com/NethermindEth/nethermind.git -> NethermindEth/nethermind
extract_github_repo() {
    local url=$1
    # Remove .git suffix
    url="${url%.git}"
    # Remove https://github.com/ prefix
    url="${url#https://github.com/}"
    # Remove http://github.com/ prefix (just in case)
    url="${url#http://github.com/}"
    echo "$url"
}

# Function to build client Docker image locally
build_client_image() {
    local commit_hash=$1
    local docker_image=$2
    local docker_build_context=$3
    local dockerfile_path=$4

    log_info "Building client Docker image: $docker_image"

    # Remove previous image if exists
    docker rmi -f "$docker_image" 2>/dev/null || true

    # Build Docker image
    local build_cmd="docker build -t $docker_image"
    if [ -n "$dockerfile_path" ]; then
        build_cmd="$build_cmd -f $dockerfile_path"
    fi
    build_cmd="$build_cmd $docker_build_context"

    log_info "Running: $build_cmd"
    if ! eval "$build_cmd" > /tmp/docker_build_${commit_hash}.log 2>&1; then
        log_error "Docker build failed for commit $commit_hash"
        tail -30 /tmp/docker_build_${commit_hash}.log
        return 1
    fi

    log_success "Docker image built successfully: $docker_image"
    return 0
}

# Function to test a commit (build locally, then run Hive)
test_commit() {
    local commit_hash=$1
    local commit_date=$2
    local docker_image=$3
    local docker_build_context=$4
    local dockerfile_path=$5
    local client_name=$6
    local hive_command=$7
    local success_string=$8
    local error_string=$9
    local timeout_seconds=${10}

    log_info "Testing commit: $commit_hash (Date: $commit_date)"

    # Navigate to client repo and checkout commit
    cd "$CLIENT_REPO_DIR" || return 2

    if ! git checkout -q "$commit_hash" 2>&1; then
        log_error "Failed to checkout commit $commit_hash"
        if ! git checkout -f -q "$commit_hash" 2>&1; then
            log_error "Force checkout also failed for commit $commit_hash"
            return 2
        fi
    fi

    # Build client Docker image locally
    if ! build_client_image "$commit_hash" "$docker_image" "$docker_build_context" "$dockerfile_path"; then
        log_error "Failed to build client image for commit $commit_hash"
        return 2
    fi

    # Navigate to hive directory
    cd "$HIVE_DIR" || return 2

    # Create config for custom client using local image
    create_hive_config "$client_name" "$docker_image"

    # Check if --docker.pull is in the command and warn/remove it
    local cleaned_hive_command="$hive_command"
    if [[ "$hive_command" == *"--docker.pull"* ]]; then
        log_warning "Removing --docker.pull from hive command (incompatible with local images)"
        cleaned_hive_command="${hive_command//--docker.pull/}"
        # Clean up any double spaces
        cleaned_hive_command=$(echo "$cleaned_hive_command" | tr -s ' ')
    fi

    # Run hive tests
    local full_hive_command="$cleaned_hive_command --client-file configs/custom_client.yaml"
    log_info "Running hive command: $full_hive_command"

    local test_output_file="/tmp/commit_${commit_hash}_logs.txt"
    local test_exit_code=0

    # Run with timeout if specified
    if [ -n "$timeout_seconds" ] && [ "$timeout_seconds" -gt 0 ]; then
        log_info "Running with timeout: ${timeout_seconds}s"
        timeout "$timeout_seconds" bash -c "$full_hive_command" > "$test_output_file" 2>&1
        test_exit_code=$?
        if [ $test_exit_code -eq 124 ]; then
            log_warning "Test timed out after ${timeout_seconds}s"
        fi
    else
        bash -c "$full_hive_command" > "$test_output_file" 2>&1
        test_exit_code=$?
    fi

    log_info "Test exit code: $test_exit_code"

    # Check results based on exit code, success string, or error string
    local is_broken=false

    # First check exit code (non-zero and not timeout)
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
            # If success string is found, override other checks
            is_broken=false
        fi
    fi

    # Show last lines of output for debugging
    log_info "Last 30 lines of test output:"
    tail -30 "$test_output_file"

    # Cleanup Docker images and build cache to save space
    log_info "Cleaning up Docker images and build cache..."
    docker rmi -f "$docker_image" 2>/dev/null || true
    docker images --filter "reference=hive/clients/${client_name}*" -q | xargs -r docker rmi -f 2>/dev/null || true
    # Clean dangling images
    docker image prune -f 2>/dev/null || true
    # Clean build cache (this is the main space consumer)
    docker builder prune -f 2>/dev/null || true

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
    log_error "Usage: $0 --date <date> --hive-command <command> --client-repo-url <url> [OPTIONS]"
    log_error ""
    log_error "Required arguments:"
    log_error "  --date <date>              : Date when the tests started failing (e.g., '2024-10-01')"
    log_error "  --hive-command <command>   : Hive command to run (e.g., './hive --sim ethereum/engine')"
    log_error "  --client-repo-url <url>    : Client repository URL (e.g., 'https://github.com/NethermindEth/nethermind.git')"
    log_error ""
    log_error "Optional arguments:"
    log_error "  --client-repo-branch <branch> : Client branch to test (default: master)"
    log_error "  --client-name <name>       : Client name for hive (default: nethermind)"
    log_error "  --docker-image <image>     : Docker image name to build (default: nethermind:bisect)"
    log_error "  --docker-build-context <path> : Docker build context path (default: '.')"
    log_error "  --dockerfile <path>        : Dockerfile path (default: auto-detect)"
    log_error "  --hive-repo-url <url>      : Hive repository URL (default: https://github.com/ethereum/hive.git)"
    log_error "  --hive-branch <branch>     : Hive branch (default: master)"
    log_error "  --repo-token <token>       : GitHub token for private repositories"
    log_error "  --good-ref <ref>           : Known good commit/branch in client repo"
    log_error "  --bad-ref <ref>            : Known bad commit/branch in client repo (default: HEAD)"
    log_error "  --success-string <string>  : String that must be present in output for success"
    log_error "  --error-string <string>    : String in output that indicates failure"
    log_error "  --timeout <seconds>        : Timeout for each test run (default: 3600 = 1 hour)"
    log_error ""
    log_error "Flow: For each commit, the script builds a Docker image locally, then runs Hive"
    log_error "      tests against that image using a custom Dockerfile."
    log_error ""
    log_error "Note: --docker.pull in hive command is automatically removed (incompatible with"
    log_error "      local images). Other images (simulators, etc.) won't be pulled either."
    log_error ""
    log_error "Examples:"
    log_error "  $0 --date '2024-10-01' \\"
    log_error "     --client-repo-url 'https://github.com/NethermindEth/nethermind.git' \\"
    log_error "     --hive-command './hive --sim ethereum/engine'"
    log_error ""
    log_error "  $0 --date '2024-10-01' \\"
    log_error "     --client-repo-url 'https://github.com/NethermindEth/nethermind.git' \\"
    log_error "     --client-name nethermind \\"
    log_error "     --hive-command './hive --sim ethereum/engine --sim.limit /AccountRange' \\"
    log_error "     --error-string 'FAIL'"
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
    local client_repo_url=""
    local client_repo_branch="master"
    local client_name="nethermind"
    local docker_image="nethermind:bisect"
    local docker_build_context="."
    local dockerfile_path=""
    local hive_repo_url="https://github.com/ethereum/hive.git"
    local hive_branch="master"
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
            --client-repo-url)
                client_repo_url="$2"
                shift 2
                ;;
            --client-repo-branch)
                client_repo_branch="$2"
                shift 2
                ;;
            --client-name)
                client_name="$2"
                shift 2
                ;;
            --docker-image)
                docker_image="$2"
                shift 2
                ;;
            --docker-build-context)
                docker_build_context="$2"
                shift 2
                ;;
            --dockerfile)
                dockerfile_path="$2"
                shift 2
                ;;
            --hive-repo-url)
                hive_repo_url="$2"
                shift 2
                ;;
            --hive-branch)
                hive_branch="$2"
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
    if [ -z "$start_date" ] || [ -z "$hive_command" ] || [ -z "$client_repo_url" ]; then
        log_error "Missing required arguments"
        show_usage
    fi

    # Store docker image name globally for cleanup
    DOCKER_IMAGE_NAME="$docker_image"

    # Initial Docker cleanup to free up space before starting
    log_info "Initial Docker cleanup to free disk space..."
    docker system prune -f 2>/dev/null || true
    docker builder prune -f 2>/dev/null || true
    log_info "Available disk space:"
    df -h / 2>/dev/null || df -h . 2>/dev/null || true

    # Verify prerequisites
    log_info "Verifying prerequisites..."

    if ! command -v go >/dev/null 2>&1; then
        log_error "Go is not installed. Please install Go first."
        exit 1
    fi
    go version

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    docker --version

    if ! command -v git >/dev/null 2>&1; then
        log_error "Git is not installed. Please install Git first."
        exit 1
    fi
    git --version

    # Clone client repository
    log_info "Cloning client repository: $client_repo_url"

    # Prepare clone URL with token if provided
    local clone_url="$client_repo_url"
    if [ -n "$repo_token" ]; then
        if [[ "$client_repo_url" =~ ^https:// ]]; then
            clone_url="${client_repo_url/https:\/\//https://${repo_token}@}"
        fi
    fi

    # Generate temporary directory name
    CLIENT_REPO_DIR="/tmp/client_bisect_repo_$$"
    CLEANUP_CLIENT_REPO=true

    # Clone the repository
    if ! git clone "$clone_url" "$CLIENT_REPO_DIR" 2>&1; then
        log_error "Failed to clone client repository"
        exit 1
    fi

    cd "$CLIENT_REPO_DIR" || exit 1
    log_success "Client repository cloned successfully to $CLIENT_REPO_DIR"

    # Checkout specific branch if provided
    if [ -n "$client_repo_branch" ]; then
        log_info "Checking out client branch: $client_repo_branch"
        if ! git checkout "$client_repo_branch" 2>&1; then
            log_error "Failed to checkout client branch: $client_repo_branch"
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

    # Setup Hive
    setup_hive "$hive_repo_url" "$hive_branch" "$repo_token"

    # Return to client repo for commit listing
    cd "$CLIENT_REPO_DIR" || exit 1

    log_info "Starting binary search for broken commit"
    log_info "Configuration:"
    log_info "  Client repository: $client_repo_url"
    log_info "  Client branch: $client_repo_branch"
    log_info "  Client name: $client_name"
    log_info "  Docker image: $docker_image"
    log_info "  Docker build context: $docker_build_context"
    log_info "  Dockerfile: ${dockerfile_path:-auto-detect}"
    log_info "  Hive repository: $hive_repo_url"
    log_info "  Hive branch: $hive_branch"
    log_info "  Hive command: $hive_command"
    log_info "  Timeout: ${timeout_seconds}s"
    log_info "  Success string: '$success_string'"
    log_info "  Error string: '$error_string'"
    log_info "  Date when tests started failing: $start_date"
    log_info ""
    log_info "Flow: Build client Docker image locally -> Create Hive config -> Run Hive tests"

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
        log_info "  From: $good_ref (or commits since $start_date)"
        log_info "  To: $bad_ref"

        COMMITS=()
        while IFS= read -r line; do
            COMMITS+=("$line")
        done < <(git log --since="$start_date" "${good_ref}..${bad_ref}" --pretty=format:"%H" --reverse)
    else
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
        test_commit "$commit_hash" "$commit_date" "$docker_image" "$docker_build_context" "$dockerfile_path" "$client_name" "$hive_command" "$success_string" "$error_string" "$timeout_seconds"
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

    # Return to client repo
    cd "$CLIENT_REPO_DIR" || exit 1

    # Verify left commit (should be good)
    if [ $left -ge 0 ] && [ $left -lt ${#COMMITS[@]} ]; then
        commit_hash=${COMMITS[$left]}
        commit_date=$(git show -s --format=%ci "$commit_hash")
        log_info "Verifying last potentially GOOD commit..."
        test_commit "$commit_hash" "$commit_date" "$docker_image" "$docker_build_context" "$dockerfile_path" "$client_name" "$hive_command" "$success_string" "$error_string" "$timeout_seconds"
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
        test_commit "$commit_hash" "$commit_date" "$docker_image" "$docker_build_context" "$dockerfile_path" "$client_name" "$hive_command" "$success_string" "$error_string" "$timeout_seconds"
        if [ $? -eq 1 ]; then
            first_broken_commit=$commit_hash
            log_error "Confirmed: This is the FIRST BROKEN commit"
        fi
        echo ""
    fi

    # Return to client repo for final output
    cd "$CLIENT_REPO_DIR" || exit 1

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
