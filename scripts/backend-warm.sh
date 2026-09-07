#!/usr/bin/env bash
# The backend "keep awake" switch for the wim-reconstruct Cloud Function —
# the one function both WiM Android and Lavrentiy desktop talk to. Its source
# lives in this repo at wim/api/. The same script sits in
# wim-android/scripts/backend-warm.sh; keep the two identical.
#
#   scripts/backend-warm.sh status   # 0 = off (Google sleeps it when idle), 1 = on
#   scripts/backend-warm.sh on       # keep one copy awake, ~$7/month, no cold start
#   scripts/backend-warm.sh off      # let it sleep; first take after idle pays a wake-up
#
# Nothing in either app changes. This is a Google-side setting only.
# Found ON since 2026-08-10 and switched OFF 2026-09-06 on George's word:
# flip it ON right before the first public release with cloud users (the
# installer build writes a reminder into its job summary).
set -euo pipefail
SERVICE=wim-reconstruct
REGION=us-central1
PROJECT=bakers-agent
case "${1:-status}" in
  on)  gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT" --min-instances=1 --quiet ;;
  off) gcloud run services update "$SERVICE" --region "$REGION" --project "$PROJECT" --min-instances=0 --quiet ;;
  status) ;;
  *) echo "usage: $0 [status|on|off]" >&2; exit 2 ;;
esac
n=$(gcloud functions describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(serviceConfig.minInstanceCount)')
case "${n:-0}" in
  0|"") echo "backend warm switch: OFF (min instances 0 — sleeps when idle)" ;;
  *)    echo "backend warm switch: ON (min instances $n — billing while idle)" ;;
esac
