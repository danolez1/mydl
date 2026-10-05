#!/usr/bin/env bash
# Runs one git hook step and records that it passed for this exact tree, so the pre-commit and pre-push
# hooks, or a push retried after a later step failed, do not repeat it.
#
#   scripts/hooks/step.sh <name> --tree index|head [--ttl-hours N] -- <command...>
#
# --tree index  the tree being committed (pre-commit)
# --tree head   the tree being pushed (pre-push)
# --ttl-hours   the stamp expires, for steps whose answer changes with time (advisory databases)
# HOOK_FORCE=1  run every step even when it has a stamp; the result is still recorded
set -uo pipefail

name=${1:?step name required}
shift
mode=""
ttl=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tree) mode=${2:?--tree needs index or head}; shift 2 ;;
    --ttl-hours) ttl=${2:?--ttl-hours needs a number}; shift 2 ;;
    --) shift; break ;;
    *) echo "hook-step: unknown option $1" >&2; exit 2 ;;
  esac
done
[ "$#" -gt 0 ] || { echo "hook-step: no command given" >&2; exit 2; }

# A step reads the working tree, so a pass only vouches for the committed tree when the two match.
case "$mode" in
  index) tree=$(git write-tree); git diff --quiet && clean=1 || clean=0 ;;
  head) tree=$(git rev-parse 'HEAD^{tree}'); git diff --quiet HEAD && clean=1 || clean=0 ;;
  *) echo "hook-step: --tree must be index or head" >&2; exit 2 ;;
esac

dir=$(git rev-parse --git-path hook-stamps)
stamp="$dir/$name"
now=$(date +%s)

if [ "${HOOK_FORCE:-0}" != "1" ] && [ -f "$stamp" ]; then
  read -r stamped_tree stamped_at _ < "$stamp" || true
  age=$(( now - ${stamped_at:-0} ))
  if [ "$stamped_tree" = "$tree" ] && { [ "$ttl" -eq 0 ] || [ "$age" -lt $(( ttl * 3600 )) ]; }; then
    echo "[$name] already passed on tree ${tree:0:10} $(( age / 60 )) min ago, skipped"
    exit 0
  fi
fi

echo "[$name] running"
"$@"
status=$?
rm -f "$stamp"
if [ "$status" -eq 0 ] && [ "$clean" -eq 1 ]; then
  mkdir -p "$dir"
  printf '%s %s %s\n' "$tree" "$now" "$(git rev-parse --short HEAD 2>/dev/null || echo none)" > "$stamp"
elif [ "$status" -eq 0 ]; then
  echo "[$name] passed, but the working tree has changes outside this tree, so no stamp was recorded"
fi
exit "$status"
