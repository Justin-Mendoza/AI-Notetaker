#!/usr/bin/env bash
set -euo pipefail

duration_seconds="${1:-120}"
output_path="${2:-/private/tmp/meeting-fixture.mp3}"
if ! [[ "$duration_seconds" =~ ^[0-9]+$ ]] || (( duration_seconds < 1 || duration_seconds > 5400 )); then
  echo "Duration must be 1 to 5400 seconds" >&2
  exit 1
fi
ffmpeg -nostdin -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=440:sample_rate=16000" \
  -t "$duration_seconds" -ac 1 -c:a libmp3lame -b:a 64k "$output_path"
echo "$output_path"
