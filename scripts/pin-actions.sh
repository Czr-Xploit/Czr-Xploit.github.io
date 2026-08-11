#!/usr/bin/env bash
# Resolve every `uses: owner/repo@tag` in .github/workflows/ to the commit SHA
# that tag currently points at, and rewrite the file in place.
#
# Why: a tag is mutable. Whoever controls the action repository can move v4 to
# point at anything, and workflows with `pages: write` / `id-token: write` will
# happily run it. Pinning to a SHA makes the dependency immutable; the cost is
# that you must re-run this deliberately to take updates, which is the point.
#
# Requires: git, curl. No GitHub token needed for public repos, though setting
# GITHUB_TOKEN raises the rate limit.
#
# Usage:
#   ./scripts/pin-actions.sh              # rewrite in place
#   ./scripts/pin-actions.sh --dry-run    # show what would change

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKFLOW_DIR="$REPO_ROOT/.github/workflows"

if [[ ! -d "$WORKFLOW_DIR" ]]; then
  echo "no workflows directory at $WORKFLOW_DIR" >&2
  exit 1
fi

api() {
  local url="$1"
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" "$url"
  else
    curl -fsSL -H "Accept: application/vnd.github+json" "$url"
  fi
}

resolve() {
  # $1 = owner/repo, $2 = tag  ->  prints the commit SHA
  local repo="$1" tag="$2" ref sha type
  ref="$(api "https://api.github.com/repos/$repo/git/ref/tags/$tag")" || return 1
  sha="$(printf '%s' "$ref" | grep -o '"sha": *"[0-9a-f]\{40\}"' | head -1 | grep -o '[0-9a-f]\{40\}')"
  type="$(printf '%s' "$ref" | grep -o '"type": *"[a-z]*"' | head -1 | sed 's/.*"\([a-z]*\)"$/\1/')"
  if [[ "$type" == "tag" ]]; then
    # Annotated tag: dereference to the commit it wraps.
    sha="$(api "https://api.github.com/repos/$repo/git/tags/$sha" \
      | grep -A3 '"object"' | grep -o '[0-9a-f]\{40\}' | head -1)"
  fi
  printf '%s' "$sha"
}

changed=0

for workflow in "$WORKFLOW_DIR"/*.yml "$WORKFLOW_DIR"/*.yaml; do
  [[ -e "$workflow" ]] || continue
  echo "==> $(basename "$workflow")"

  # Only lines that still use a tag; already-pinned SHAs are left alone.
  while IFS= read -r line; do
    action="$(printf '%s' "$line" | sed -n 's/.*uses: *\([^@]*\)@\([^ ]*\).*/\1/p')"
    tag="$(printf '%s' "$line" | sed -n 's/.*uses: *\([^@]*\)@\([^ ]*\).*/\2/p')"
    [[ -z "$action" || -z "$tag" ]] && continue
    [[ "$tag" =~ ^[0-9a-f]{40}$ ]] && continue
    [[ "$action" == ./* ]] && continue

    if ! sha="$(resolve "$action" "$tag")" || [[ -z "$sha" ]]; then
      echo "    ! could not resolve $action@$tag" >&2
      continue
    fi

    echo "    $action@$tag -> $sha"
    if [[ $DRY_RUN -eq 0 ]]; then
      # shellcheck disable=SC2001
      sed -i "s|uses: ${action}@${tag}\b.*|uses: ${action}@${sha} # ${tag}|" "$workflow"
      changed=1
    fi
  done < <(grep -E '^\s*uses:' "$workflow" || true)
done

if [[ $DRY_RUN -eq 1 ]]; then
  echo "dry run: nothing written"
elif [[ $changed -eq 1 ]]; then
  echo "workflows updated. Review the diff before committing:"
  echo "  git diff .github/workflows/"
else
  echo "nothing to pin."
fi
