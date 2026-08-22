#!/bin/sh
set -eu

: "${WIM_FLOW_IMAGE:?Set WIM_FLOW_IMAGE to the built image URL}"

gcloud run deploy wim-flowse \
  --project=bakers-agent \
  --region=us-central1 \
  --image="$WIM_FLOW_IMAGE" \
  --service-account=wim-backend@bakers-agent.iam.gserviceaccount.com \
  --port=8080 \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --cpu=8 \
  --memory=32Gi \
  --no-cpu-throttling \
  --cpu-boost \
  --no-gpu-zonal-redundancy \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=300s \
  --startup-probe=httpGet.path=/ready,httpGet.port=8080,initialDelaySeconds=0,failureThreshold=30,timeoutSeconds=5,periodSeconds=10 \
  --liveness-probe=httpGet.path=/healthz,httpGet.port=8080,initialDelaySeconds=0,failureThreshold=3,timeoutSeconds=5,periodSeconds=30 \
  --no-allow-unauthenticated

