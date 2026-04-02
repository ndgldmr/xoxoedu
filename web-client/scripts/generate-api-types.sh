#!/usr/bin/env bash
# Fetch the OpenAPI spec from the running backend and generate TypeScript types.
# Requires the backend to be running at NEXT_PUBLIC_API_URL (default: http://localhost:8000).

set -euo pipefail

API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
SPEC_OUT="src/lib/api/openapi.json"
TYPES_OUT="src/lib/api/types.ts"

echo "Fetching OpenAPI spec from ${API_URL}/openapi.json ..."
if ! curl -sf "${API_URL}/openapi.json" -o "$SPEC_OUT"; then
  echo "ERROR: Could not reach ${API_URL}/openapi.json" >&2
  echo "Make sure the backend is running (cd ../backend && docker compose up -d --wait)" >&2
  exit 1
fi

echo "Generating TypeScript types -> ${TYPES_OUT} ..."
npx openapi-typescript "$SPEC_OUT" -o "$TYPES_OUT"

echo "Done."
