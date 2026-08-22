# WiM BSRNN-Flow noise cleaner

Private Cloud Run GPU service used before WiM cloud transcription.

The image pins the official ICASSP 2026 URGENT baseline source and the
`flow_bsrnn.ckpt` checkpoint by commit and SHA-256. The build selects the
published EMA weights and stores only inference weights in safetensors; the
runtime never downloads or unpickles the training checkpoint. It accepts a raw WAV, M4A,
FLAC, or MP3 body at `POST /v1/enhance` and returns mono 16 kHz PCM WAV.

The published checkpoint was trained on short clips. Long WiM takes are split
into 96,000-sample windows with a 24,000-sample overlap and crossfaded back
together before the clean WAV is returned.

Production settings: one L4 GPU, concurrency 1, minimum instances 0, maximum
instances 1. Keep the service private and grant Run Invoker only to the
`wim-backend@bakers-agent.iam.gserviceaccount.com` service account.

Build and deploy:

```sh
IMAGE="us-central1-docker.pkg.dev/bakers-agent/cloud-run-source-deploy/wim-flowse:<git-sha>"
gcloud builds submit --project=bakers-agent --region=us-central1 \
  --config=cloudbuild.yaml --substitutions="_IMAGE=$IMAGE" .
WIM_FLOW_IMAGE="$IMAGE" ./deploy.sh
gcloud run services add-iam-policy-binding wim-flowse \
  --project=bakers-agent --region=us-central1 \
  --member=serviceAccount:wim-backend@bakers-agent.iam.gserviceaccount.com \
  --role=roles/run.invoker
```
