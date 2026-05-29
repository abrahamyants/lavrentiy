#!/usr/bin/env bash
# Lavrentiy hosted demo — Cloud Run deploy.
#
# One-time setup (run once per project):
#   gcloud secrets create lavrentiy-openai-key    --replication-policy="automatic"
#   gcloud secrets create lavrentiy-anthropic-key --replication-policy="automatic"
#   printf 'sk-...' | gcloud secrets versions add lavrentiy-openai-key    --data-file=-
#   printf 'sk-ant-...' | gcloud secrets versions add lavrentiy-anthropic-key --data-file=-
#
# Then from the repo root (NOT from hosted/):
#   bash hosted/deploy.sh
set -euo pipefail

PROJECT="${LAV_GCP_PROJECT:-bakers-agent}"
REGION="${LAV_REGION:-us-central1}"
SERVICE="${LAV_SERVICE:-lavrentiy-demo}"
IMAGE="gcr.io/${PROJECT}/${SERVICE}"

echo "==> Building image ${IMAGE} from $(pwd)"
gcloud builds submit \
  --project "${PROJECT}" \
  --config hosted/cloudbuild.yaml \
  .

echo "==> Deploying to Cloud Run (${SERVICE} in ${REGION})"
gcloud run deploy "${SERVICE}" \
  --project "${PROJECT}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --concurrency 8 \
  --max-instances 5 \
  --set-secrets "OPENAI_API_KEY=lavrentiy-openai-key:latest,ANTHROPIC_API_KEY=lavrentiy-anthropic-key:latest"

URL=$(gcloud run services describe "${SERVICE}" --project "${PROJECT}" --region "${REGION}" --format='value(status.url)')
echo
echo "==> Deployed: ${URL}"
echo "==> Quick check: curl ${URL}/healthz"
