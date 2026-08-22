ARG PYTORCH_IMAGE=pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime@sha256:11691e035a3651d25a87116b4f6adc113a27a29d8f5a6a583f8569e0ee5ff897

FROM ${PYTORCH_IMAGE} AS converter

ARG URGENT_COMMIT=b1dc3ad1e86419ff0bd666f455bda7936bff0e9a
ARG HF_COMMIT=d4add2435a74b3f2dd54a9bbd417a058c68983b1
ARG FLOW_CHECKPOINT_SHA256=f9201821243797fd5f9b852779040057b6f204267935712f96ccf0353cd9d438

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl git libsndfile1 patch \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt

RUN git clone --no-checkout https://github.com/urgent-challenge/urgent2026_challenge_track1.git /opt/urgent \
    && git -C /opt/urgent checkout "$URGENT_COMMIT" \
    && test "$(git -C /opt/urgent rev-parse HEAD)" = "$URGENT_COMMIT"

COPY urgent-device.patch /tmp/urgent-device.patch
RUN git -C /opt/urgent apply --check /tmp/urgent-device.patch \
    && git -C /opt/urgent apply /tmp/urgent-device.patch

RUN curl --fail --location --retry 5 --retry-delay 2 \
      "https://huggingface.co/lichenda/icassp_2026_urgent_baseline/resolve/${HF_COMMIT}/flow_bsrnn.ckpt" \
      -o /tmp/flow_bsrnn.ckpt \
    && echo "$FLOW_CHECKPOINT_SHA256  /tmp/flow_bsrnn.ckpt" | sha256sum -c --strict

COPY convert_checkpoint.py /opt/convert_checkpoint.py
RUN PYTHONPATH=/opt/urgent python /opt/convert_checkpoint.py \
      --checkpoint /tmp/flow_bsrnn.ckpt \
      --output-dir /opt/model \
      --source-commit "$URGENT_COMMIT" \
      --checkpoint-sha256 "$FLOW_CHECKPOINT_SHA256" \
    && rm /tmp/flow_bsrnn.ckpt


FROM ${PYTORCH_IMAGE} AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY --from=converter /opt/urgent/baseline_code /opt/urgent/baseline_code
COPY --from=converter /opt/urgent/LICENSE.txt /opt/urgent/LICENSE.txt
COPY --from=converter /opt/model /models
COPY app.py /service/app.py

ENV PYTHONPATH=/opt/urgent \
    PYTHONUNBUFFERED=1 \
    FLOW_MODEL_CONFIG=/models/flow_bsrnn.config.json \
    FLOW_MODEL_WEIGHTS=/models/flow_bsrnn.safetensors \
    PRELOAD_MODEL=1 \
    FLOW_STEPS=15 \
    MAX_AUDIO_SECONDS=30 \
    FLOW_CHUNK_SAMPLES=96000 \
    FLOW_OVERLAP_SAMPLES=8000

WORKDIR /service
USER app
CMD ["bash", "-lc", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 1 --timeout 300 app:app"]
