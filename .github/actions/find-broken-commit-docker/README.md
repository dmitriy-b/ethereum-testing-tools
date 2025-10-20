# Find Broken Commit via Docker

A generic binary search tool to find which git commit broke Docker container functionality. This action/script performs an automated git bisect by building and testing each commit's Docker container.

## Features

- **Generic**: Works with any repository and Docker image
- **Binary Search**: Efficiently finds the breaking commit using binary search algorithm
- **Flexible**: Supports public and private repositories
- **Configurable**: Customizable Docker build context, run arguments, and error detection
- **Safe**: Automatically cleans up Docker artifacts and restores git state
- **CI/CD Ready**: Can be used as a GitHub Action or standalone script

## Usage

### As a GitHub Action

#### Basic Example (Public Repository)

```yaml
name: Find Broken Commit
on:
  workflow_dispatch:
    inputs:
      date:
        description: 'Date when it started failing (YYYY-MM-DD)'
        required: true
        default: '2024-10-01'

jobs:
  bisect:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history needed for bisect

      - name: Find broken commit
        uses: ./.github/actions/find-broken-commit-docker
        with:
          date: ${{ github.event.inputs.date }}
          docker_image: 'myapp:bisect'
          error_string: 'Fatal error'
          wait_time: '60'
```

#### Advanced Example (Private Repository with Custom Docker Args)

```yaml
name: Find Broken Commit
on:
  workflow_dispatch:

jobs:
  bisect:
    runs-on: ubuntu-latest
    steps:
      - name: Find broken commit in private repo
        uses: dmitriy-b/ethereum-testing-tools/.github/actions/find-broken-commit-docker@main
        with:
          date: '2024-10-01'
          docker_image: 'myapp:test'
          repo_url: 'https://github.com/myorg/private-repo.git'
          repo_token: ${{ secrets.GITHUB_TOKEN }}
          repo_branch: 'develop'
          good_ref: 'v1.0.0'
          bad_ref: 'HEAD'
          docker_args: '--env DATABASE_URL=postgres://test -p 8080:8080'
          docker_build_context: './backend'
          wait_time: '45'
          error_string: 'Connection refused'

      - name: Create issue if broken commit found
        if: steps.bisect.outputs.first_broken_commit
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: 'Broken commit found: ${{ steps.bisect.outputs.first_broken_commit }}',
              body: 'Binary search found the breaking commit:\n\nLast good: ${{ steps.bisect.outputs.last_good_commit }}\nFirst broken: ${{ steps.bisect.outputs.first_broken_commit }}'
            })
```

### As a Standalone Script

#### Basic Example

```bash
./find_broken_commit.sh \
  --date '2024-10-01' \
  --docker-image 'myapp:test'
```

#### Advanced Example

```bash
./find_broken_commit.sh \
  --date '2024-10-01' \
  --docker-image 'nethermind:test' \
  --repo-url 'https://github.com/NethermindEth/nethermind.git' \
  --good-ref 'v1.25.0' \
  --bad-ref 'main' \
  --docker-args '--env NETHERMIND_CONFIG=volta --env NETHERMIND_NETWORK=volta' \
  --docker-build-context '.' \
  --wait-time 60 \
  --error-string 'Unexpected genesis hash'
```

#### With Private Repository

```bash
# Export token as environment variable for security
export GH_TOKEN="ghp_your_token_here"

./find_broken_commit.sh \
  --date '2024-10-01' \
  --docker-image 'myapp:test' \
  --repo-url 'https://github.com/myorg/private-repo.git' \
  --repo-token "$GH_TOKEN" \
  --repo-branch 'develop'
```

## Parameters

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--date` | Date when the application started failing | `'2024-10-01'` |
| `--docker-image` | Docker image name and tag to build/test | `'myapp:bisect'` |

### Optional Parameters

| Parameter | Description | Default | Example |
|-----------|-------------|---------|---------|
| `--repo-url` | Git repository URL to clone | Current directory | `'https://github.com/user/repo.git'` |
| `--repo-branch` | Branch to checkout after cloning | Default branch | `'develop'` |
| `--repo-token` | GitHub token for private repositories | None | `${{ secrets.GITHUB_TOKEN }}` |
| `--good-ref` | Known good commit/branch reference | Auto-detect | `'v1.0.0'` or `'abc123'` |
| `--bad-ref` | Known bad commit/branch reference | `HEAD` | `'main'` or `'def456'` |
| `--docker-args` | Arguments passed to `docker run` | Empty | `'--env KEY=val -p 8080:8080'` |
| `--docker-build-context` | Path to Docker build context | `'.'` | `'./backend'` |
| `--wait-time` | Seconds to wait after container starts | `30` | `60` |
| `--error-string` | String in logs that indicates failure | `'error'` | `'Fatal error'` |

## How It Works

1. **Initialization**
   - Validates all parameters
   - Clones repository if URL provided
   - Stores current git state for restoration

2. **Binary Search**
   - Gets all commits between `date` and `bad-ref` (or between `good-ref` and `bad-ref`)
   - Performs binary search through commits
   - For each commit:
     - Checks out the commit
     - Builds Docker image with specified name
     - Runs container with specified arguments
     - Waits specified time for initialization
     - Checks logs for error string
     - Determines if commit is good or broken

3. **Narrowing Down**
   - Continues until finding adjacent commits where one is good and one is broken
   - Verifies both the last good and first broken commits

4. **Cleanup**
   - Removes all Docker containers and images created during search
   - Restores original git branch/commit
   - Restores any stashed changes
   - Removes cloned repository if applicable

## Output Examples

### Success Output

```
========================================
========================================
[SUCCESS] FOUND THE EXACT BREAKING POINT!

✓ LAST GOOD COMMIT: abc123def456

commit abc123def456
Author: Developer <dev@example.com>
Date:   Mon Oct 1 10:00:00 2024 +0000

    Feature: Add new functionality

 src/main.go | 10 ++++++++++
 1 file changed, 10 insertions(+)

==========================================

✗ FIRST BROKEN COMMIT: def789ghi012

commit def789ghi012
Author: Developer <dev@example.com>
Date:   Mon Oct 1 11:00:00 2024 +0000

    Fix: Update configuration

 config/app.yml | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

[INFO] To see the diff between these commits:
  git diff abc123def456 def789ghi012

[INFO] To see what changed in the breaking commit:
  git show def789ghi012

[INFO] Error found in logs: 'Fatal error'
[INFO] Logs saved in:
  /tmp/commit_abc123def456_logs.txt (GOOD)
  /tmp/commit_def789ghi012_logs.txt (BROKEN)
========================================
========================================
```

## Security Considerations

### Token Handling

- **Never hardcode tokens** in your scripts or workflow files
- Use `${{ secrets.GITHUB_TOKEN }}` in GitHub Actions
- Use environment variables when running locally
- Tokens are only inserted into git URLs, never logged

### Private Repositories

- Use `repo_token` input for private repositories
- GitHub Actions automatically provides `secrets.GITHUB_TOKEN` with appropriate permissions
- For cross-repository access, create a Personal Access Token with `repo` scope

### Docker Security

- Containers are run with default Docker security settings
- All containers are cleaned up after testing
- Consider using `--read-only` or other Docker security flags in `docker_args` if needed

## Troubleshooting

### "No commits found in the specified range"

- Try an earlier date
- Verify that `good_ref` and `bad_ref` are valid
- Check: `git log --oneline --since='<date>' <bad-ref>`

### "Docker build failed"

- Check the last 20 lines in `/tmp/docker_build.log`
- Ensure Dockerfile exists in the build context
- Verify all build dependencies are available

### "Failed to clone repository"

- Verify repository URL is correct
- For private repos, ensure token has correct permissions
- Check network connectivity

### "Error string not found in logs"

- Container might need more time to initialize (increase `wait_time`)
- Error string might be case-sensitive or spelled differently
- Check `/tmp/commit_*_logs.txt` files to see actual log output

## Examples for Common Use Cases

### Testing a Node.js Application

```bash
./find_broken_commit.sh \
  --date '2024-10-01' \
  --docker-image 'node-app:test' \
  --docker-args '--env NODE_ENV=production -p 3000:3000' \
  --wait-time 45 \
  --error-string 'Error: Cannot find module'
```

### Testing a Blockchain Node

```bash
./find_broken_commit.sh \
  --date '2024-10-01' \
  --docker-image 'blockchain-node:test' \
  --docker-args '--env NETWORK=mainnet --env CHAIN_ID=1' \
  --wait-time 120 \
  --error-string 'genesis hash mismatch'
```

### Testing a Microservice

```bash
./find_broken_commit.sh \
  --date '2024-10-01' \
  --docker-image 'api-service:test' \
  --docker-build-context './services/api' \
  --docker-args '--env DATABASE_URL=postgres://test -p 8080:8080' \
  --wait-time 30 \
  --error-string 'Failed to connect'
```

## Requirements

- `bash` 4.0+
- `git` 2.0+
- `docker` 20.0+
- Full git history (use `fetch-depth: 0` in GitHub Actions)

## License

See repository LICENSE file.

