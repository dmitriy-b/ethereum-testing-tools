#!/usr/bin/env bash
set -euo pipefail

# update_bootnodes.sh
# Replace bootnode lists in docker-compose.yml from two JSON files.
# Keeps bootnode flags in sync with JSON sources, supporting dry-run previews.

# ---- Config / Args ----
COMPOSE_FILE="${1:-docker-compose.yml}"
EXEC_JSON="${2:-bootnodes-execution.json}"
BEACON_JSON="${3:-bootnodes-beacon.json}"
DRY_RUN="${DRY_RUN:-0}"   # export DRY_RUN=1 to preview without writing

# ---- Checks ----
for f in "$COMPOSE_FILE" "$EXEC_JSON" "$BEACON_JSON"; do
  [[ -f "$f" ]] || { echo "Error: file not found: $f" >&2; exit 1; }
done
command -v jq >/dev/null     || { echo "Error: jq is required." >&2; exit 1; }
command -v python3 >/dev/null || { echo "Error: python3 is required." >&2; exit 1; }

# ---- Build lists from JSON values (preserves order) ----
ENODES="$(jq -r '[ .[] ] | join(",")' "$EXEC_JSON")"
ENRS="$(jq -r '[ .[] ] | join(",")' "$BEACON_JSON")"

[[ -n "$ENODES" ]] || { echo "Error: no enode values found in $EXEC_JSON" >&2; exit 1; }
[[ -n "$ENRS" ]]   || { echo "Error: no enr values found in $BEACON_JSON" >&2; exit 1; }

echo "Found $(grep -o 'enode://' <<<"$ENODES" | wc -l | tr -d ' ') execution bootnodes."
echo "Found $(grep -o 'enr:'    <<<"$ENRS"   | wc -l | tr -d ' ') beacon bootnodes."

# (Optional) quick sanity check of first items
# echo "First enode: $(grep -o 'enode://[^,"]\+' <<<"$ENODES" | head -n1)"
# echo "First enr:   $(grep -o 'enr:[^,"]\+'    <<<"$ENRS"   | head -n1)"

# ---- Replacement function (preserves indentation, prints unified diff on dry run) ----
replace_flag() {
  local file="$1" flag_name="$2" replacement="$3"
  [[ "$DRY_RUN" == "1" ]] && echo "---- DRY RUN: $flag_name ----"

  python3 - "$file" "$flag_name" "$replacement" "$DRY_RUN" <<'PY'
import difflib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
flag = sys.argv[2]
replacement = sys.argv[3]
dry_run = sys.argv[4] == "1"

original_text = path.read_text()
lines = original_text.splitlines(keepends=True)
needle = f"- {flag}="

changed = False
updated_lines = []

for line in lines:
    stripped_line = line.rstrip("\r\n")
    newline = line[len(stripped_line):]
    leading_spaces_len = len(stripped_line) - len(stripped_line.lstrip())
    indent = stripped_line[:leading_spaces_len]
    body = stripped_line[leading_spaces_len:]

    if body.startswith(needle):
        before_eq, _, _ = body.partition("=")
        new_line = f"{indent}{before_eq}={replacement}{newline}"
        if new_line != line:
            changed = True
        updated_lines.append(new_line)
    else:
        updated_lines.append(line)

updated_text = "".join(updated_lines)

if dry_run:
    if changed:
        diff = difflib.unified_diff(
            original_text.splitlines(),
            updated_text.splitlines(),
            fromfile=str(path),
            tofile="-",
            lineterm=""
        )
        print("\n".join(diff))
else:
    if changed:
        path.write_text(updated_text)
PY
}

# ---- Do replacements ----
# Execution client flags (enode:// list)
replace_flag "$COMPOSE_FILE" '--Network.Bootnodes'       "$ENODES"
replace_flag "$COMPOSE_FILE" '--Discovery.Bootnodes'     "$ENODES"
replace_flag "$COMPOSE_FILE" '--Network.StaticPeers'     "$ENODES"

# Beacon/consensus flag (enr list)
replace_flag "$COMPOSE_FILE" '--p2p-discovery-bootnodes'  "$ENRS"

# ---- Summary ----
if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run complete. No changes written."
else
  echo "Updated $COMPOSE_FILE (backup saved as ${COMPOSE_FILE}.bak)."
fi
