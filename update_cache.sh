#!/bin/bash
# Scryfall Oracle Cards cache updater
# Downloads the latest Oracle Cards bulk data to ~/.hermes/scryfall/
# Prices stale after 24h; gameplay data (Oracle text, types) is good for weeks.

CACHE_DIR="$HOME/.hermes/scryfall"
API_URL="https://api.scryfall.com/bulk-data"
GZ_FILE="$CACHE_DIR/oracle-cards.jsonl.gz"
JSONL_FILE="$CACHE_DIR/oracle-cards.jsonl"

# 1. Get the current download URL from the API
DOWNLOAD_URL=$(curl -s "$API_URL" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data['data']:
    if item['type'] == 'oracle_cards':
        print(item['jsonl_download_uri'])
        break
")

if [ -z "$DOWNLOAD_URL" ]; then
    echo "ERROR: Could not find Oracle Cards download URL from Scryfall API"
    exit 1
fi

echo "Downloading Oracle Cards from: $DOWNLOAD_URL"

# 2. Download the gzipped file
curl -s -L -o "$GZ_FILE" "$DOWNLOAD_URL"

if [ ! -f "$GZ_FILE" ] || [ ! -s "$GZ_FILE" ]; then
    echo "ERROR: Download failed or file is empty"
    exit 1
fi

# 3. Decompress (overwrite existing)
gunzip -f "$GZ_FILE"

if [ ! -f "$JSONL_FILE" ]; then
    echo "ERROR: Decompression failed"
    exit 1
fi

# 4. Report stats
LINE_COUNT=$(wc -l < "$JSONL_FILE")
FILE_SIZE=$(du -h "$JSONL_FILE" | cut -f1)
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

echo "✅ Scryfall Oracle Cards updated: $TIMESTAMP"
echo "   File: $JSONL_FILE"
echo "   Size: $FILE_SIZE"
echo "   Cards: $LINE_COUNT"

# 5. Refresh the derived search index so queries stay fast.
#    Safe to skip: the tool detects a stale index by mtime/size and rebuilds
#    or falls back on its own — this just avoids a slow first query later.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$SCRIPT_DIR/scry" ]; then
    echo "Rebuilding search index..."
    "$SCRIPT_DIR/scry" reindex || echo "WARN: index rebuild failed; queries will use the full scan"
elif [ -x "$SCRIPT_DIR/scryfall" ]; then
    echo "Rebuilding search index..."
    "$SCRIPT_DIR/scryfall" reindex || echo "WARN: index rebuild failed; queries will use the full scan"
else
    echo "NOTE: run 'scry reindex' to refresh the search index (optional)."
fi
