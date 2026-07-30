#!/bin/bash
# Upload champions meta output to Azure Blob Storage
# Usage: AZURE_CHAMPIONS_SAS_TOKEN="sv=..." ./upload_azure.sh [output_dir]

set -euo pipefail

STORAGE_ACCOUNT="androidpokedex"
CONTAINER="champions-meta"
SAS_TOKEN="${AZURE_CHAMPIONS_SAS_TOKEN:-}"
OUTPUT_DIR="${1:-$(dirname "$0")/../output}"

if [ -z "$SAS_TOKEN" ]; then
  echo "❌ Error: AZURE_CHAMPIONS_SAS_TOKEN not set"
  exit 1
fi

if [ ! -d "$OUTPUT_DIR" ]; then
  echo "❌ Error: Output directory not found: $OUTPUT_DIR"
  exit 1
fi

BASE_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER}"
FAILED=0

upload_blob() {
  local src="$1"
  local dest="$2"

  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" -X PUT \
    -H "x-ms-blob-type: BlockBlob" \
    -H "Content-Type: application/json" \
    -H "Cache-Control: no-cache" \
    --data-binary "@${src}" \
    "${BASE_URL}/${dest}?${SAS_TOKEN}")

  if [ "$status" -ge 200 ] && [ "$status" -lt 300 ]; then
    return 0
  else
    echo "  ⚠️ Failed to upload ${dest} (HTTP ${status})"
    FAILED=$((FAILED + 1))
    return 1
  fi
}

# Upload battle_meta.json
echo "📤 Uploading to Azure Blob Storage..."
if upload_blob "${OUTPUT_DIR}/battle_meta.json" "battle_meta.json"; then
  echo "  ✓ battle_meta.json"
fi

# Upload per-pokemon files
COUNT=0
for f in "${OUTPUT_DIR}"/pokemon/*.json; do
  [ -f "$f" ] || continue
  filename=$(basename "$f")
  upload_blob "$f" "pokemon/${filename}" && COUNT=$((COUNT + 1))
done

echo "  ✓ ${COUNT} pokemon files"

# Upload additive singles files under a separate namespace. Existing doubles
# blob destinations above are deliberately unchanged for app compatibility.
SINGLES_COUNT=0
if [ -f "${OUTPUT_DIR}/singles/battle_meta.json" ]; then
  if upload_blob "${OUTPUT_DIR}/singles/battle_meta.json" "singles/battle_meta.json"; then
    echo "  ✓ singles/battle_meta.json"
  fi

  for f in "${OUTPUT_DIR}"/singles/pokemon/*.json; do
    [ -f "$f" ] || continue
    filename=$(basename "$f")
    upload_blob "$f" "singles/pokemon/${filename}" && SINGLES_COUNT=$((SINGLES_COUNT + 1))
  done
  echo "  ✓ ${SINGLES_COUNT} singles pokemon files"
else
  echo "  ⚠️ singles/battle_meta.json not found, skipping singles upload"
fi

if [ "$FAILED" -gt 0 ]; then
  echo "⚠️ ${FAILED} upload(s) failed"
  exit 1
else
  echo "✅ Azure upload complete"
fi
