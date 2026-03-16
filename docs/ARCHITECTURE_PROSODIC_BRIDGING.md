## Architectural Note: Prosodic Bridging

Lavrentiy does something architecturally unique that neither USDM (Kim et al., NeurIPS 2024) nor SpeechEmotionLlama (Kang et al., Interspeech 2025) does: it bridges the prosodic information gap between a completely frozen, API-only LLM (GPT-4o) and a completely separate ASR system (Whisper) using **structured text as the transport layer**.

USDM requires end-to-end training of a speech-text model on 512 A100 GPUs with 87,000 hours of data. SpeechEmotionLlama requires training a 1B-parameter speech encoder against a frozen LLM. Lavrentiy extracts the same underlying features — F0, energy, speaking rate — with numpy autocorrelation, compares them against the speaker's personal baseline from stored sessions, and describes the result in English. The LLM was never trained on this format, but the Kang paper proves it responds to paralinguistic descriptions anyway.

The F0/HNR reuse is the cleanest part of the implementation. `extract_f0()` and `compute_hnr()` are the same autocorrelation computation reading different outputs from the same signal — HNR reads the peak magnitude (how harmonic vs noisy), F0 reads the peak lag position (what frequency). One signal processing primitive, two distinct features, both feeding into the same prompt injection architecture.

The infrastructure cost of Layer 5.5 (prosodic bridging) on top of Layer 5 (paralinguistic detection) was ~200 lines of new logic, not 200 lines of new signal processing. The acoustic foundation was already there.

**Research validation chain:**
- USDM proved prosodic information survives aggressive tokenization and carries emotional/contextual state
- SpeechEmotionLlama proved a frozen LLM produces dramatically better responses when given text descriptions of paralinguistic state (emotion understanding: 5.59 → 7.56)
- "Beyond the Labels" (Pešán et al., 2024) warned that learned models can detect lexical content instead of actual paralinguistic features — Lavrentiy's approach uses acoustic physics (HNR, F0), which cannot accidentally learn text content

Together: extract what Whisper destroys, describe it in text, inject it into the prompt. The LLM does the rest.
