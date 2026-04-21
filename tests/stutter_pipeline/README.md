# Disfluent-Speech Reconstruction Pipeline Test

Curated test corpus for the Lavrentiy + WiM reconstruction pipeline. Runs 10 disfluency patterns through L1–L4 of `wim/api/reconstruct.py` and reports input / output / Falcon verdict / timing.

## Patterns covered

1. Part-word repetition
2. Whole-word repetition
3. Prolongation
4. Silent block
5. Filler stacking (postponement)
6. Covert avoidance (synonym substitution)
7. False start / sentence abandonment
8. Mixed pattern
9. High-stress situational
10. Bilingual EN/RU

## Run

From this directory:

```bash
export OPENAI_API_KEY=$(cat ../../api_key.txt)
PYTHONIOENCODING=utf-8 python3 run_test.py
```

Generates `results_<UTC>.json` + `report_<UTC>.html` side by side.

## Output

Each run records: input, output per layer, Falcon verdict (OK / FAIL), confidence gamma, elapsed time. Falcon FAIL means the validator rejected the GPT output — the app falls back to raw text rather than committing a bad reconstruction.

## Notes

- Test inputs are **text representations** of what an ASR would produce. Audio-based end-to-end testing requires a running Lavrentiy engine and is a separate harness.
- The 10 cases are patterns synthesized from published stuttering research (Brown 1945, Howell 2004, Apple ML 2023). Replace or augment with real stutterer audio transcripts as needed.
- Falcon rejections on the covert-avoidance case indicate the validator correctly catching reconstructions that don't reverse a tracked avoidance. That is the feature working as designed.
