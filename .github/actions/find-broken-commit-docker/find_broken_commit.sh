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
DOCKER_IMAGE_NAME=""
DOCKER_BUILD_CONTEXT="."
REPO_URL=""
REPO_DIR=""
CLEANUP_REPO=false

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
    cleanup_docker

    if [ -n "$ORIGINAL_BRANCH" ]; then
        log_info "Returning to original branch/commit: $ORIGINAL_BRANCH"
        git checkout -q "$ORIGINAL_BRANCH" 2>/dev/null || true
    fi

    # Restore stashed changes if any
    if git stash list | grep -q "Temporary stash by find_broken_commit script"; then
        log_info "Restoring stashed changes..."
        git stash pop 2>/dev/null || log_warning "Could not restore stashed changes automatically"
    fi

    # Cleanup cloned repository if needed
    if [ "$CLEANUP_REPO" = true ] && [ -n "$REPO_DIR" ] && [ -d "$REPO_DIR" ]; then
        log_info "Cleaning up cloned repository: $REPO_DIR"
        cd ..
        rm -rf "$REPO_DIR"
    fi

    exit $exit_code
}

# Function to cleanup docker containers and images
cleanup_docker() {
    log_info "Cleaning up Docker containers and images..."
    local image_pattern="${DOCKER_IMAGE_NAME//:/.*}"
    docker ps -a --filter "ancestor=$DOCKER_IMAGE_NAME" -q | xargs -r docker rm -f 2>/dev/null || true
    docker images --filter "reference=$DOCKER_IMAGE_NAME" -q | xargs -r docker rmi -f 2>/dev/null || true
}

# Function to test a commit
test_commit() {
    local commit_hash=$1
    local commit_date=$2
    local docker_args=$3
    local wait_time=$4
    local error_string=$5

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

    # Cleanup any previous docker artifacts
    cleanup_docker

    # Build docker image
    log_info "Building Docker image: $DOCKER_IMAGE_NAME"
    if ! docker build -t "$DOCKER_IMAGE_NAME" "$DOCKER_BUILD_CONTEXT" > /tmp/docker_build.log 2>&1; then
        log_error "Docker build failed for commit $commit_hash"
        cat /tmp/docker_build.log | tail -20
        return 2
    fi

    # Run docker container with custom args
    log_info "Running Docker container with args: $docker_args"
    CONTAINER_ID=$(docker run -d "$DOCKER_IMAGE_NAME" $docker_args 2>&1)

    if [ -z "$CONTAINER_ID" ] || [[ "$CONTAINER_ID" == *"Error"* ]]; then
        log_error "Failed to start container"
        echo "$CONTAINER_ID"
        return 2
    fi

    log_info "Container started: $CONTAINER_ID"
    log_info "Waiting ${wait_time} seconds for container to initialize..."
    sleep "$wait_time"

    # Check docker logs
    log_info "Checking container logs..."
    LOGS=$(docker logs "$CONTAINER_ID" 2>&1)

    # Save logs to file for debugging
    echo "$LOGS" > "/tmp/commit_${commit_hash}_logs.txt"

    # Check if logs contain the error message
    if echo "$LOGS" | grep -q "$error_string"; then
        log_error "Found error in logs: '$error_string'"
        log_error "This commit is BROKEN"
        docker rm -f "$CONTAINER_ID" > /dev/null 2>&1 || true
        return 1  # Broken commit
    else
        log_success "No error found in logs"
        log_success "This commit is GOOD"
        docker rm -f "$CONTAINER_ID" > /dev/null 2>&1 || true
        return 0  # Good commit
    fi
}

# Function to show usage
show_usage() {
    log_error "Usage: $0 --date <date> --docker-image <image> [OPTIONS]"
    log_error ""
    log_error "Required arguments:"
    log_error "  --date <date>              : Date when the app started failing (e.g., '2024-10-01')"
    log_error "  --docker-image <image>     : Docker image name and tag (e.g., 'myapp:test')"
    log_error ""
    log_error "Optional arguments:"
    log_error "  --repo-url <url>           : Git repository URL to clone (if not already in a repo)"
    log_error "  --repo-branch <branch>     : Branch to checkout after cloning (default: default branch)"
    log_error "  --repo-token <token>       : GitHub token for private repositories"
    log_error "  --good-ref <ref>           : Known good commit/branch"
    log_error "  --bad-ref <ref>            : Known bad commit/branch (default: HEAD)"
    log_error "  --docker-args <args>       : Docker run arguments (default: empty)"
    log_error "  --docker-build-context <path> : Docker build context path (default: '.')"
    log_error "  --wait-time <seconds>      : Seconds to wait after container start (default: 30)"
    log_error "  --error-string <string>    : String to search in logs (default: 'error')"
    log_error ""
    log_error "Examples:"
    log_error "  $0 --date '2024-10-01' --docker-image 'myapp:test'"
    log_error "  $0 --date '2024-10-01' --docker-image 'myapp:test' --good-ref abc123"
    log_error "  $0 --date '2024-10-01' --docker-image 'myapp:test' --repo-url 'https://github.com/user/repo.git'"
    log_error "  $0 --date '2024-10-01' --docker-image 'myapp:test' --docker-args '--env KEY=value' --wait-time 60"
    exit 1
}

# Main script
main() {
    # Parse named arguments
    local start_date=""
    local good_ref=""
    local bad_ref="HEAD"
    local docker_args=""
    local wait_time="30"
    local error_string="error"
    local repo_url=""
    local repo_branch=""
    local repo_token=""

    # Parse command-line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --date)
                start_date="$2"
                shift 2
                ;;
            --docker-image)
                DOCKER_IMAGE_NAME="$2"
                shift 2
                ;;
            --docker-build-context)
                DOCKER_BUILD_CONTEXT="$2"
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
            --docker-args)
                docker_args="$2"
                shift 2
                ;;
            --wait-time)
                wait_time="$2"
                shift 2
                ;;
            --error-string)
                error_string="$2"
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
    if [ -z "$start_date" ] || [ -z "$DOCKER_IMAGE_NAME" ]; then
        log_error "Missing required arguments"
        show_usage
    fi

    # Clone repository if URL is provided
    if [ -n "$repo_url" ]; then
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
        REPO_DIR="/tmp/bisect_repo_$$"
        CLEANUP_REPO=true

        # Clone the repository
        if ! git clone "$clone_url" "$REPO_DIR" 2>&1; then
            log_error "Failed to clone repository"
            exit 1
        fi

        cd "$REPO_DIR" || exit 1
        log_success "Repository cloned successfully"

        # Checkout specific branch if provided
        if [ -n "$repo_branch" ]; then
            log_info "Checking out branch: $repo_branch"
            if ! git checkout "$repo_branch" 2>&1; then
                log_error "Failed to checkout branch: $repo_branch"
                exit 1
            fi
        fi
    else
        # Verify we're in a git repository
        if ! git rev-parse --git-dir > /dev/null 2>&1; then
            log_error "Not in a git repository and no --repo-url provided"
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
    log_info "  Docker image: $DOCKER_IMAGE_NAME"
    log_info "  Docker build context: $DOCKER_BUILD_CONTEXT"
    log_info "  Docker args: $docker_args"
    log_info "  Wait time: ${wait_time}s"
    log_info "  Error string: '$error_string'"
    log_info "  Date when app started failing: $start_date"

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

    # Check if working directory is clean
    if ! git diff-index --quiet HEAD 2>/dev/null; then
        log_warning "Working directory has uncommitted changes"
        log_info "Stashing changes..."
        git stash push -u -m "Temporary stash by find_broken_commit script" || {
            log_error "Failed to stash changes. Please commit or stash your changes manually."
            exit 1
        }
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
        log_error "  2. Specify a known good commit/branch as second argument:"
        log_error "     Example: $0 '$start_date' <good-commit> $bad_ref"
        log_error ""
        log_error "To find a good starting point, try:"
        log_error "  git log --oneline --since='$start_date'"
        exit 1
    fi

    log_info "Found ${#COMMITS[@]} commits to search through"
    log_info "Commit range:"
    log_info "  First (oldest): ${COMMITS[0]} - $(git log -1 --format='%ci' ${COMMITS[0]})"
    log_info "  Last (newest):  ${COMMITS[-1]} - $(git log -1 --format='%ci' ${COMMITS[-1]})"

    # Store original branch/commit to return to later
    ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)

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
        test_commit "$commit_hash" "$commit_date" "$docker_args" "$wait_time" "$error_string"
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
            # Error occurred during testing, move forward
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
        test_commit "$commit_hash" "$commit_date" "$docker_args" "$wait_time" "$error_string"
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
        test_commit "$commit_hash" "$commit_date" "$docker_args" "$wait_time" "$error_string"
        if [ $? -eq 1 ]; then
            first_broken_commit=$commit_hash
            log_error "Confirmed: This is the FIRST BROKEN commit"
        fi
        echo ""
    fi

    # Cleanup
    cleanup_docker

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
        log_info "Error found in logs: '$error_string'"
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
        log_info "Error found in logs: '$error_string'"
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
