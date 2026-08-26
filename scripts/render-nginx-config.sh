#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 HOSTNAME OUTPUT [SOURCE]" >&2
}

[[ $# -ge 2 && $# -le 3 ]] || { usage; exit 2; }

hostname=$1
output=$2
source=${3:-nginx.conf}

if [[ ! "$hostname" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]] ||
   [[ "$hostname" == *..* ]] || [[ "$hostname" != *.* ]]; then
  echo "Invalid deployment hostname: $hostname" >&2
  exit 2
fi

[[ -f "$source" ]] || { echo "Missing Nginx source config: $source" >&2; exit 1; }

# nginx.conf is the checked-in template and raspberrypi.local is its explicit
# default. Render every root and subdomain server_name/redirect consistently.
sed "s/raspberrypi\.local/$hostname/g" "$source" > "$output"

has_server_name() {
  local expected=$1
  awk -v expected="$expected" '
    /^[[:space:]]*server_name[[:space:]]/ {
      for (field_number = 2; field_number <= NF; field_number += 1) {
        name = $field_number
        sub(/;$/, "", name)
        if (name == expected) found = 1
      }
    }
    END { exit(found ? 0 : 1) }
  ' "$output"
}

for expected in "$hostname" "app.$hostname" "tools.$hostname" "mtg.$hostname" "maps.$hostname"; do
  has_server_name "$expected" || {
    echo "Rendered Nginx config is missing server_name $expected" >&2
    exit 1
  }
done

if [[ "$hostname" != "raspberrypi.local" ]] && grep -Fq 'raspberrypi.local' "$output"; then
  echo "Rendered Nginx config still contains the default hostname" >&2
  exit 1
fi
