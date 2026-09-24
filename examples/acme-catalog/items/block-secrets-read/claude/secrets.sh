#!/bin/sh
# Claude Code PreToolUse hook: exit 2 blocks the tool call.
input=$(cat)
case "$input" in
  *'.env"'*|*'.pem"'*|*'secrets/'*) echo "blocked: secrets are off limits" >&2; exit 2 ;;
esac
exit 0
