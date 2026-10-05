#!/usr/bin/env bash
# Conventional Commits check for repos that carry no commitlint dependency. The type list matches the other
# repos' commitlint configs, and attribution trailers are refused.
#
#   scripts/hooks/commit-msg.sh <message file>
set -uo pipefail

file=${1:?message file required}
subject=$(grep -vE '^\s*(#|$)' "$file" | head -n 1)

if [[ ! "$subject" =~ ^(feat|fix|docs|style|refactor|test|chore|perf|ci|revert)(\([a-z0-9._/-]+\))?!?:\ .+ ]]; then
  echo "commit-msg: the subject must look like 'type(scope): summary' with type one of feat, fix, docs, style, refactor, test, chore, perf, ci, revert" >&2
  exit 1
fi
if [ "${#subject}" -gt 100 ]; then
  echo "commit-msg: the subject is ${#subject} characters, the limit is 100" >&2
  exit 1
fi
if grep -Eiq '^Co-Authored-By:|Generated with|noreply@anthropic\.com' "$file"; then
  echo "commit-msg: attribution trailers are not allowed" >&2
  exit 1
fi
