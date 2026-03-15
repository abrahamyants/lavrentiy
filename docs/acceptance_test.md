# Acceptance Test — API Boundary Verification

**Date:** 2026-03-15
**Result:** 18/18 PASSED, 0 FAILED
**Cost:** ~$0.02
**Script:** `acceptance_test.py` (local, not in repo — requires mic + API key)

## Purpose

All 843 automated tests use **mocked** API responses. They verify that the pipeline logic is correct given assumed API behavior. The acceptance test verifies that the **real API actually behaves the way the mocks assume**.

## What it tests

### Test A: Whisper verbose JSON response format (11 checks)

Records 5 seconds from the local microphone, sends to real Whisper API with `response_format="verbose_json"`, and verifies:

- Response contains `text`, `segments` fields
- Each segment contains `start`, `end`, `text`, `avg_logprob`, `no_speech_prob`
- These are the exact fields that `test_pipeline.py` and `test_whisper_voting.py` mock

**Result:** All fields present. Segment keys: `['id', 'avg_logprob', 'compression_ratio', 'end', 'no_speech_prob', 'seek', 'start', 'temperature', 'text', 'tokens']`

### Test B: GPT-4o-mini reconstruction (5 checks)

Sends a synthetic disfluent string through GPT-4o-mini with the L4 reconstruction prompt:

- Input: `"I I I want to um go to the the store p- p- please"`
- Verifies output is non-empty, shorter than input, preserves content words, removes fillers
- Output: `"I want to go to the store, please."`

### Test C: Falcon meaning validation (2 checks)

Sends two pairs through a meaning validator:

- Same meaning (raw ≈ clean) → expects `true`
- Different meaning (raw ≠ altered) → expects `false`

## Boundary assumptions confirmed

1. **API response format matches mocks** — Whisper returns `avg_logprob` and `no_speech_prob` per segment, exactly as mocked in `test_pipeline.py`
2. **Reconstruction quality holds** — GPT-4o-mini correctly cleans disfluent input with the L4 prompt
3. **Validation logic works** — meaning comparison correctly distinguishes preserved vs altered content

## When to re-run

- After any OpenAI API update or model version change
- After changing Whisper parameters (temperature, response format)
- Monthly as a routine check
- If automated tests all pass but the app behaves incorrectly in production
