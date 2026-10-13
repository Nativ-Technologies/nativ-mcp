#!/usr/bin/env bash
# Dedicated Cloud Run MCP service. Run from this repository after tests pass.
set -euo pipefail
cd "$(dirname "$0")"

MCP_PROJECT="${MCP_PROJECT:-nativ-backend}"
MCP_REGION="${MCP_REGION:-us-central1}"
MCP_SERVICE="${MCP_SERVICE:-nativ-mcp}"
MCP_BUCKET="${MCP_BUCKET:-${MCP_PROJECT}-mcp-outputs}"
MCP_ACCOUNT="nativ-mcp@${MCP_PROJECT}.iam.gserviceaccount.com"
MCP_PUBLIC_URL="${MCP_PUBLIC_URL:-https://mcp.usenativ.com/mcp}"

gcloud services enable iamcredentials.googleapis.com --project "$MCP_PROJECT"
if ! gcloud iam service-accounts describe "$MCP_ACCOUNT" --project "$MCP_PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create nativ-mcp --display-name "Nativ hosted MCP" --project "$MCP_PROJECT"
fi
if ! gcloud storage buckets describe "gs://${MCP_BUCKET}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${MCP_BUCKET}" --project "$MCP_PROJECT" \
        --location "$MCP_REGION" --uniform-bucket-level-access --public-access-prevention
fi
gcloud storage buckets update "gs://${MCP_BUCKET}" --lifecycle-file deploy/lifecycle.json
gcloud storage buckets add-iam-policy-binding "gs://${MCP_BUCKET}" \
    --member "serviceAccount:${MCP_ACCOUNT}" --role roles/storage.objectUser
gcloud iam service-accounts add-iam-policy-binding "$MCP_ACCOUNT" --project "$MCP_PROJECT" \
    --member "serviceAccount:${MCP_ACCOUNT}" --role roles/iam.serviceAccountTokenCreator

# Cloud Run's generated service hostname is stable for this project/region.
# Also retrieve the existing URL when updating a deployment.
MCP_RUN_HOST="$(gcloud run services describe nativ-backend --project "$MCP_PROJECT" --region "$MCP_REGION" --format='value(status.url)' | sed "s|https://nativ-backend-|${MCP_SERVICE}-|")"
MCP_PROJECT_NUMBER="$(gcloud projects describe "$MCP_PROJECT" --format='value(projectNumber)')"
MCP_RUN_HOST="${MCP_RUN_HOST},${MCP_SERVICE}-${MCP_PROJECT_NUMBER}.${MCP_REGION}.run.app"
gcloud run deploy "$MCP_SERVICE" --source . --project "$MCP_PROJECT" --region "$MCP_REGION" \
    --service-account "$MCP_ACCOUNT" --allow-unauthenticated --port 8080 \
    --memory 2Gi --cpu 1 --concurrency 4 --min-instances 0 --max-instances 10 --timeout 3600 \
    --set-env-vars "^|^NATIV_API_URL=https://api.usenativ.com|NATIV_MCP_PUBLIC_URL=${MCP_PUBLIC_URL}|NATIV_MCP_ALLOWED_HOSTS=${MCP_RUN_HOST}|NATIV_MCP_OUTPUT_BUCKET=${MCP_BUCKET}|NATIV_MCP_SIGNING_ACCOUNT=${MCP_ACCOUNT}" \
    --quiet
MCP_SERVICE_URL="$(gcloud run services describe "$MCP_SERVICE" --project "$MCP_PROJECT" --region "$MCP_REGION" --format='value(status.url)')"
echo "MCP endpoint: ${MCP_SERVICE_URL}/mcp"
echo "REST connector schema: ${MCP_SERVICE_URL}/openapi.json"
