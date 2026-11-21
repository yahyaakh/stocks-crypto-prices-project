#!/usr/bin/env bash
# Download LOBSTER's free AAPL sample day (2012-06-21, 10 levels, ~7.3 MB zip) into data/lobster/.
# The data is not committed to git; this script makes the replay reproducible from a clean clone.
# Source: https://lobsterdata.com/info/DataSamples.php  (sample files based on Nasdaq TotalView-ITCH)
set -euo pipefail

URL="https://php.lobsterdata.com/info/sample/LOBSTER_SampleFile_AAPL_2012-06-21_10.zip"
DIR="$(cd "$(dirname "$0")/.." && pwd)/data/lobster"
mkdir -p "$DIR"

if ls "$DIR"/AAPL_2012-06-21_*_message_10.csv >/dev/null 2>&1; then
  echo "already present: $DIR"
  exit 0
fi

curl -fSL --retry 3 -o "$DIR/AAPL_10.zip" "$URL"
unzip -o -q "$DIR/AAPL_10.zip" -d "$DIR"
echo "extracted to $DIR:"
ls -1 "$DIR"
