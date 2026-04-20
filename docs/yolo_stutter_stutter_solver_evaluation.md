# YOLO-Stutter & Stutter-Solver (DysfluentWFST) — Technical Evaluation Memo

**Classification:** Internal Engineering Memo  
**Date:** April 20, 2026  
**Author:** Claude Sonnet 4.6 (Lavrentiy/WiM Engineering Synthesis)  
**Status:** Read-Only Analysis — No Code Modified, No Commits  
**Scope:** Integration feasibility for WiM Android (Kotlin/ARM64) and Lavrentiy desktop (Python/x86_64)

---

## Framing Note — Correcting a Prior Memo Error

The `stutterzero_checkpoint_research.md` (Session 7) described YOLO-Stutter as using "VITS as a neural TTS vocoder" to produce "natural-sounding audio." This framing was incorrect. YOLO-Stutter uses VITS as an **encoder** — specifically, it extracts soft attention alignments from VITS's internal mel-spectrogram alignment mechanism and feeds those features into its detection decoder. YOLO-Stutter produces **dysfluency labels**, not corrected audio.

Likewise, Stutter-Solver (DysfluentWFST) produces **dysfluency transcription and classification output**, not synthesized fluent speech.

**Neither model replaces the WiM L4 reconstruction path.** Both are dysfluency **detection** systems that could augment the existing pipeline by injecting richer disfluency-location signals upstream of GPT-4o. The integration question is not "replace whisper.cpp + L4" but "insert a detection layer between ASR and LLM."

---

## 1. Architecture Analysis

### 1.1 YOLO-Stutter

**Paper:** "YOLO-Stutter: End-to-end Region-Wise Speech Dysfluency Detection"  
**Venue:** Interspeech 2024, DOI: 10.21437/Interspeech.2024-1855  
**arXiv:** 2408.15297  
**GitHub:** https://github.com/rorizzz/yolo-stutter  
**Author:** Xuanru Zhou (UCSF / Berkeley Speech Group)

#### Encoder: VITS Soft Alignment Extractor

YOLO-Stutter does not train the VITS model — it uses a **pretrained VITS checkpoint** (LJSpeech single-speaker, `pretrained_ljs.pth`, or VCTK multi-speaker, `pretrained_vctk.pth`) as a frozen feature extractor. Specifically, it taps VITS's internal monotonic alignment search (MAS) mechanism to extract soft attention alignment tensors of shape `[batch, time, 513]` (mel-spectrogram aligned to text).

The VITS base model is Kim et al. (2021), "Conditional Variational Autoencoder with Adversarial Learning for End-to-End Text-to-Speech," ICML 2021. The VITS encoder is approximately **28M parameters** at the base LJSpeech configuration. **The VITS model is not fine-tuned** — it is used purely as a feature extraction oracle.

**Architectural consequence:** YOLO-Stutter is fundamentally constrained by VITS's need for a text-audio pair. It cannot operate in a purely speech-only mode — it requires a reference text to compute the alignment. For WiM (speech-only input, no reference text), this is a **hard architectural constraint** that must be addressed with forced alignment or ASR pre-transcription.

#### Decoder: Conv1D + Transformer Detection Head

The decoder is a custom `Conv1DTransformerDecoder` (~2–5M parameters estimated from architecture, not explicitly stated in documentation):

- **Input:** 768-channel soft alignment features (padded from VITS alignment output)
- **4 DecoderBlocks:** Conv1D + BatchNorm + GELU, with alternating channel downsampling (768 → 384 → 192 → 96)
- **PositionalEncoding:** Sinusoidal, d_model = 96
- **TransformerEncoder:** 8 layers, 8 attention heads, batch-first
- **Output head:** Linear(96 → 7) producing 7 values per region:
  - 2 boundary coordinates (start, end of dysfluency region)
  - 1 existence confidence score (dysfluency present/absent)
  - 4 class logits: repetition, block, missing (deletion), replacement, prolongation

**Prediction granularity:** 64 maximum regions per utterance, downsampled 16× from spectrogram frames. Output is a set of (time_region, dysfluency_type, confidence) tuples.

#### Vocoder: None

YOLO-Stutter produces no audio output. The "VITS vocoder" description in the StutterZero memo was a mischaracterization of VITS's role in this architecture. **YOLO-Stutter's output is a structured label sequence, not waveform.**

#### Training Configuration

- **Dataset:** VCTK-Stutter (simulated dysfluencies on VCTK multi-speaker recordings) — **synthetic, not clinical speech**
- **Dysfluency types simulated:** repetition, block, missing (deletion), replacement, prolongation
- **Batch size:** 64, AdamW optimizer (lr = 3e-4, weight_decay = 0), 20 epochs
- **Loss functions:** MSELoss (boundary), BCELoss (existence), CrossEntropyLoss (type classification)

#### Reported Metrics

**The public-facing README does not report WER or F1 numbers.** The paper (Interspeech 2024, DOI: 10.21437/Interspeech.2024-1855) contains Tables with detection accuracy, but these are not reproduced in the GitHub documentation. The paper abstract states "achieves state-of-the-art performance with a minimum number of trainable parameters" — the specific numbers require the paper PDF.

From code analysis, metrics tracked during training are:
- `val_disfluency_exists_accuracy` (binary: presence/absence)
- `val_disfluency_type_accuracy` (4-class: rep/block/missing/replacement)
- Per-region boundary MSE

**WER is not a reported metric** — YOLO-Stutter does not perform ASR and therefore cannot produce a WER. Comparison with whisper.cpp on WER is category-invalid.

---

### 1.2 Stutter-Solver / DysfluentWFST

**Paper:** "Dysfluent WFST: A Framework for Zero-Shot Speech Dysfluency Transcription and Detection"  
**Venue:** Interspeech 2025 (accepted)  
**arXiv:** 2505.16351  
**GitHub:** https://github.com/Berkeley-Speech-Group/DysfluentWFST  
**Author:** Berkeley Speech Group (Gopala Anumanchipalli lab, EECS, UC Berkeley)

#### Encoder: Wav2Vec2-XLSR-53 Phoneme CTC

DysfluentWFST uses `facebook/wav2vec2-xlsr-53-phon-cv-ft` (HuggingFace) as its acoustic encoder. This is a 53-language cross-lingual Wav2Vec2 model fine-tuned on CommonVoice for phoneme CTC transcription.

- **Parameters:** ~300M (Wav2Vec2-XLSR-53 base)
- **Output:** Phoneme-level CTC logits, 41 phoneme classes (IPA-based)
- **Input:** Raw waveform, 16kHz
- **Not fine-tuned:** Used as a frozen pretrained model — zero-shot

**Architectural consequence:** The 300M parameter encoder is significantly larger than whisper.cpp (ggml-base.en is ~75M, ggml-small.en is ~242M). On mobile hardware, this is a RAM-budget concern.

#### Decoder: Weighted Finite-State Transducer (WFST via k2)

The decoder is a **rule-based WFST** constructed at runtime using the k2 (GPU-accelerated FST) framework. It has zero learnable parameters.

The FSA architecture consists of four composed transducers:
1. **CTC Topology FSA:** Standard CTC blank-state removal
2. **Reference FSA:** Built from the ground-truth phoneme sequence (requires reference text — same constraint as YOLO-Stutter)
3. **Phoneme Lexicon FSA:** Maps phoneme sequences to words
4. **Dysfluency FSA:** Custom transducer that models four error types:
   - **Repetition:** Back-pointer transitions (j < i), cost proportional to distance
   - **Insertion:** Skip-forward transitions (j > i), cost proportional to distance
   - **Deletion:** Implicit gap in state sequence
   - **Substitution:** Articulation-aware using a 41×41 phoneme similarity matrix (`rule_sim_matrix.npy`), top-3 phonetically similar substitutes per position

**Key parameters:**
- `β (beta)` = 5: FSA cost scaling
- `num_beam` = 25: beam search width
- `skip/back/sub` toggles: enable/disable each dysfluency type

**Phoneme similarity matrix** is derived from articulatory feature proximity — phonemes with similar place of articulation (e.g., /p/ and /b/) have high similarity scores. This is the "DDSP vocoder" claim from the prior research memo: that was also incorrect. DysfluentWFST has no vocoder; the similarity matrix is an articulatory phonology distance matrix, not a signal processing component.

#### Vocoder: None

Same as YOLO-Stutter: DysfluentWFST produces **dysfluency labels and corrected phoneme transcription**, not audio output.

#### Training Data

**None.** DysfluentWFST is zero-shot — the entire pipeline is constructed from:
- A pretrained encoder (from HuggingFace)
- Rule-based FSA transitions (from articulatory phonology principles)
- A phoneme similarity matrix (derived from phonetic theory, not learned)

This is the system's core advantage: it requires no dysfluency-annotated training data, which is the primary bottleneck in the field (no SEP-28k equivalent exists for most languages).

#### Reported Metrics

**No specific numbers are available in public documentation.** The paper abstract claims "state-of-the-art performance in both phonetic error rate and dysfluency detection." The code uses a custom **Weight PER (Phonetic Error Rate)** metric that weights substitution costs by phoneme similarity rather than treating all substitutions equally. This metric is not directly comparable to standard WER used in ASR benchmarks.

The decoder output structure is:
```python
{
  'id': sample_id,
  'ref_phonemes': [...],
  'decode_phonemes': [...],
  'dys_detect': [
    {'phoneme': 'ɛ', 'start_state': 3, 'end_state': 4, 'dysfluency_type': 'repetition'},
    ...
  ]
}
```

---

## 2. Checkpoint Availability Audit

### 2.1 YOLO-Stutter

| Component | Location | Format | Status | Size (estimated) |
|---|---|---|---|---|
| VITS pretrained (LJSpeech) | Google Drive (README link) | `.pth` (PyTorch) | ✓ Available | ~120MB |
| VITS pretrained (VCTK) | Google Drive (README link) | `.pth` (PyTorch) | ✓ Available | ~130MB |
| YOLO-Stutter detector | Google Drive (README link) | `.pth` (PyTorch) | ✓ Available | ~10–25MB (decoder only) |
| Test datasets (VCTK-Stutter) | Google Drive (README link) | `.wav` + `.json` | ✓ Available | ~500MB |

**License:** MIT (confirmed, `LICENSE` file present in repo). Free for commercial use.

**Download mechanism:** Manual Google Drive download. No `pip install` path. No HuggingFace Hub presence. No automated download script in the repo — user must visit the Google Drive links in the README and download manually.

**Version control:** No tagged releases in GitHub. The `main` branch appears to be the only tracked version.

**Checkpoint loading:**
```python
# VITS encoder (frozen)
model_vits = SynthesizerTrn(...)
model_vits.load_state_dict(torch.load("pretrained_ljs.pth"))

# YOLO-Stutter detector  
model_detector = Conv1DTransformerDecoder(...)
model_detector.load_state_dict(torch.load("yolo_stutter_checkpoint.pth"))
```

### 2.2 DysfluentWFST

| Component | Location | Format | Status |
|---|---|---|---|
| Wav2Vec2-XLSR-53-phon encoder | HuggingFace Hub (`facebook/wav2vec2-xlsr-53-phon-cv-ft`) | PyTorch `.bin` / safetensors | ✓ Available (auto-download) |
| WFST decoder rules | GitHub source (`/utils/decoder.py`) | Python source | ✓ In repo |
| Phoneme similarity matrix | GitHub (`/utils/rule_sim_matrix.npy`) | NumPy `.npy` | ✓ In repo |
| Phoneme lexicon | GitHub (`/config/lexicon.json`) | JSON | ✓ In repo |
| IPA↔CMU mapping | GitHub (`/config/ipa2cmu.json`) | JSON | ✓ In repo |

**License:** **MISSING.** No `LICENSE` file in the repository. No license identifier in any source file. Per standard legal interpretation, undeclared license means all rights reserved to the authors. **This is a hard blocker for commercial or clinical deployment without written permission from the Berkeley Speech Group.**

**Encoder download mechanism:** Automatic via HuggingFace `transformers`:
```python
from transformers import Wav2Vec2ForCTC
model = Wav2Vec2ForCTC.from_pretrained("facebook/wav2vec2-xlsr-53-phon-cv-ft")
# ~1.2GB download on first use
```

**Wav2Vec2-XLSR-53 license:** Apache 2.0 (Meta AI). This covers the encoder; the DysfluentWFST wrapper code is separately unlicensed.

---

## 3. Mobile Feasibility

### 3.1 YOLO-Stutter on Android ARM64

**Target hardware:** Qualcomm Snapdragon 8 Gen 2+, Google Tensor G3+, 6–8GB LPDDR5

**Component analysis:**

| Component | Size | ARM64 Feasibility | Notes |
|---|---|---|---|
| VITS encoder | ~120MB (FP32) | ⚠️ Marginal | 28M params; INT8 quantization → ~30MB. Standard Transformer architecture with Conv layers — PyTorch Mobile supports this |
| Conv1D-Transformer detector | ~10–25MB (FP32) | ✓ Good | ~2–5M params; tiny footprint |
| monotonic_align module | Cython `.so` | ❌ Hard blocker | Must be compiled with Cython for target architecture; no prebuilt ARM64 `.so` exists; requires NDK cross-compilation toolchain |
| Total RAM at inference | ~300–500MB | ✓ OK | Within 6–8GB device budget |

**Critical blocker: Cython compilation.**  
The `monotonic_align` module required by VITS (`/yolo-stutter/monotonic_align/`) is a Cython extension module. It must be compiled from source. For Android ARM64:
1. NDK cross-compilation setup required (aarch64-linux-android toolchain)
2. Cython generates C code → compile with NDK clang
3. No prebuilt `.so` for ARM64 exists; no one in the community has documented this path

**Workaround:** Replace monotonic alignment with a pure Python/NumPy approximation for inference (the VITS MAS is only needed during training; inference uses the precomputed alignment from the pretrained checkpoint). This is non-trivial but architecturally feasible. **[Speculative — requires prototyping]**

**ONNX export feasibility:**  
VITS is exportable to ONNX with caveats (dynamic shapes, the MAS module). The detection decoder is straightforward to export. No ONNX export scripts exist in the repo. Estimated effort: 2–3 days.

**ARM inference time estimate (speculative, no benchmark data):**
- VITS soft alignment forward pass: ~100–200ms on Snapdragon 8 Gen 2 NPU (FP16)
- Conv1D-Transformer decoder: ~15–30ms
- **Total estimated latency: ~130–250ms per utterance** at 2–5s clip lengths
- RTF estimate: ~0.05–0.1x (well below real-time)

**PyTorch Mobile compatibility:** PyTorch Mobile 2.1+ supports Conv1D, BatchNorm, GELU, TransformerEncoder. VITS's coupling layers and normalizing flows require validation per-operator. No blocking incompatibilities expected.

**Quantization options:**
- Dynamic INT8: applicable to Linear layers (decoder output head, Transformer QKV). No code changes required.
- Static INT8: requires calibration dataset. Reduces VITS encoder from ~120MB to ~30MB.
- FP16 (NPU native): Snapdragon Hexagon DSP supports FP16 natively; all standard ops supported.

### 3.2 DysfluentWFST on Android ARM64

**Hard verdict: Not feasible without major re-engineering.**

| Component | Issue | Severity |
|---|---|---|
| k2 framework | CUDA-centric; no Android/ARM NDK build path | ❌ Hard blocker |
| Wav2Vec2-XLSR-53 (300M params) | ~1.2GB at FP32; even INT8 → ~300MB; RAM pressure at inference | ❌ Hard blocker |
| `phonemizer` library | Requires eSpeak-NG system dependency; not available in Android sandbox | ❌ Hard blocker |
| `espnet` toolkit | 200MB dependency with system bindings (Sox, ffmpeg); Android incompatible | ❌ Hard blocker |

**k2 specifically:** The k2 framework (https://github.com/k2-fsa/k2) is built on CUDA GPU primitives for FST operations. Its CPU mode is incomplete and undocumented for production use. The authors of DysfluentWFST note in the code: `device = 'cpu'  # only support cpu for now because of k2 framework` — indicating even the k2 CPU path is unstable. An ARM64 k2 build would require a full native port of the FST kernel operations, which is a multi-month project.

**Alternative path (speculative):** Replace k2 with OpenFST (C++, cross-platform) for the FSA operations. OpenFST has Android build support. The WFST logic could be re-implemented in OpenFST. This is a ~4-week re-engineering effort and is **outside scope** for a WiM v1 integration. **[Speculative — research-track only]**

### 3.3 Desktop (Lavrentiy Python/x86_64)

| Model | Desktop Feasibility | Notes |
|---|---|---|
| YOLO-Stutter | ✓ Good | Full PyTorch stack works on Windows x86_64; conda environment provided |
| DysfluentWFST | ✓ Good (if CUDA available) | k2 requires CUDA; CPU-only mode unstable. Lavrentiy desktop likely has GPU access |

**DysfluentWFST desktop caveat:** Lavrentiy runs on George's Dell laptop (Windows 11). GPU availability is unspecified. If integrated graphics only, k2 CPU instability is a risk. If discrete GPU (even NVIDIA GT series), k2 will work.

---

## 4. Integration Path — WiM Android (Kotlin Wrapper Sketch)

**Architecture context:** WiM currently routes audio through `WhisperClient.kt` for ASR, then passes the transcript to `ReconstructClient.kt` for L4 reconstruction. The proposed integration point for YOLO-Stutter is **between `WhisperClient` and `ReconstructClient`** — YOLO-Stutter enriches the raw transcript with dysfluency location metadata before the LLM prompt is built.

**Prerequisite:** YOLO-Stutter model files converted to TorchScript or ONNX and bundled in the APK or downloaded on first use.

### 4.1 Proposed Kotlin Wrapper Sketch (not production code)

```kotlin
// NEW FILE: YoloStutterClient.kt (proposed, not written)

/**
 * Proposed integration sketch — not production code.
 * YOLO-Stutter dysfluency detection wrapper for WiM Android.
 * Requires:
 *   - VITS encoder exported to TorchScript/ONNX (manual step, ~2-3 days effort)
 *   - YOLO-Stutter decoder exported to TorchScript/ONNX (simpler, ~1 day)
 *   - PyTorch Mobile 2.1+ (.aar) added to build.gradle
 */
data class DysfluencyRegion(
    val startMs: Float,      // Millisecond offset in utterance
    val endMs: Float,
    val type: DysfluencyType,
    val confidence: Float
)

enum class DysfluencyType { REPETITION, BLOCK, MISSING, REPLACEMENT, PROLONGATION }

object YoloStutterClient {
    // Called once during app init — loads TorchScript models from assets
    fun initialize(context: Context) { /* load model files */ }

    /**
     * Detect dysfluency regions in an utterance.
     * Input: WAV audio + reference text (from Whisper transcript)
     * Output: list of labeled dysfluency regions
     */
    fun detect(audioPath: String, referenceText: String): List<DysfluencyRegion> {
        // Step 1: Extract VITS soft alignment (frozen VITS encoder forward pass)
        // Step 2: Run Conv1DTransformer decoder
        // Step 3: Decode output [64, 7] tensor into DysfluencyRegion list
        TODO("Implement after ONNX export")
    }
}
```

### 4.2 How It Plugs Into ReconstructClient.kt

In `reconstructDirect()` or the backend JSON body, add a `disfluencyHints` field:

```kotlin
// In the L4 prompt builder (lines 261–350), after the existing Whisper artifact section:
if (dysfluencyRegions.isNotEmpty()) {
    val hintsStr = dysfluencyRegions.joinToString("; ") { region ->
        "${region.type.name.lowercase()} detected at ~${region.startMs.toInt()}ms–${region.endMs.toInt()}ms (confidence: ${(region.confidence * 100).toInt()}%)"
    }
    append("\n\nDETECTED DYSFLUENCY REGIONS (from local model): $hintsStr")
    append("\nUse these as ground-truth labels for the corresponding time positions in the transcript.")
}
```

This enriches the L4 prompt with confirmed dysfluency locations rather than relying on GPT-4o to infer them from the text alone.

### 4.3 JNI / Native Dependencies

| Need | Blocker Level | Solution |
|---|---|---|
| PyTorch Mobile (.aar) | Low | `implementation 'org.pytorch:pytorch_android:2.1.0'` |
| ONNX Runtime Android | Low (alternative) | `implementation 'com.microsoft.onnxruntime:onnxruntime-android:1.16.0'` |
| Cython `monotonic_align` | **High** | Must cross-compile with NDK; or replace with pure Python workaround |
| Audio resampling (16kHz) | Low | Android AudioRecord + torchaudio resample |

**build.gradle additions (sketch):**
```gradle
dependencies {
    // Option A: PyTorch Mobile
    implementation 'org.pytorch:pytorch_android:2.1.0'
    implementation 'org.pytorch:pytorch_android_torchvision:2.1.0'
    
    // Option B: ONNX Runtime (lighter, no PyTorch Mobile dependency)
    implementation 'com.microsoft.onnxruntime:onnxruntime-android:1.16.0'
}
```

**Recommendation: Use ONNX Runtime over PyTorch Mobile.** ONNX Runtime is lighter (no operator registry overhead), has better NPU/NNAPI integration on Android, and avoids PyTorch Mobile's incomplete operator coverage.

---

## 5. Integration Path — Lavrentiy Desktop (Python Wrapper Sketch)

**Architecture context:** Lavrentiy (`lavrentiy.py`) currently uses OpenAI Whisper or faster-whisper for ASR, then passes to the L4 LLM prompt. The integration point is the same as Android — insert between ASR and LLM.

### 5.1 YOLO-Stutter Desktop Wrapper Sketch

```python
# NEW FILE: yolo_stutter_client.py (proposed, not written)

"""
Proposed YOLO-Stutter integration for Lavrentiy desktop.
Prerequisite: conda env from yolo-stutter/environment.yml
"""

import torch
from dataclasses import dataclass
from typing import List, Optional
import sys
sys.path.insert(0, "path/to/yolo-stutter")  # adjust to repo location

@dataclass
class DysfluencyRegion:
    start_sec: float
    end_sec: float
    type: str  # 'repetition', 'block', 'missing', 'replacement', 'prolongation'
    confidence: float

class YoloStutterClient:
    def __init__(self, vits_checkpoint: str, detector_checkpoint: str):
        # Load VITS encoder (frozen)
        self.vits = self._load_vits(vits_checkpoint)
        self.vits.eval()
        
        # Load YOLO-Stutter detector
        self.detector = self._load_detector(detector_checkpoint)
        self.detector.eval()
    
    def detect(self, audio_path: str, reference_text: str) -> List[DysfluencyRegion]:
        """
        Detect dysfluency regions in audio given a reference transcript.
        reference_text: output from faster-whisper or Whisper API (the ASR transcript)
        """
        # Step 1: Extract VITS soft alignment
        alignment = self._extract_alignment(audio_path, reference_text)
        
        # Step 2: Pad/reshape to [1, time, 768]
        features = self._prepare_features(alignment)
        
        # Step 3: Run detector
        with torch.no_grad():
            output = self.detector(features)  # [1, 64, 7]
        
        # Step 4: Decode predictions
        regions = self._decode_output(output, audio_path)
        return regions
    
    def _decode_output(self, output: torch.Tensor, audio_path: str) -> List[DysfluencyRegion]:
        """Convert [1, 64, 7] tensor to DysfluencyRegion list."""
        TYPE_NAMES = ['repetition', 'block', 'missing', 'replacement', 'prolongation']
        regions = []
        for region in output[0]:  # iterate 64 regions
            start, end, confidence = region[0], region[1], region[2]
            type_logits = region[3:]
            if confidence < 0.5:
                continue  # skip low-confidence regions
            type_idx = type_logits.argmax().item()
            audio_duration = get_audio_duration(audio_path)  # helper
            regions.append(DysfluencyRegion(
                start_sec=float(start) * audio_duration,
                end_sec=float(end) * audio_duration,
                type=TYPE_NAMES[type_idx],
                confidence=float(confidence)
            ))
        return regions
    
    def format_for_llm_prompt(self, regions: List[DysfluencyRegion]) -> Optional[str]:
        """Format detection output for injection into L4 LLM prompt."""
        if not regions:
            return None
        hints = "; ".join(
            f"{r.type} at {r.start_sec:.1f}s–{r.end_sec:.1f}s (conf {r.confidence:.0%})"
            for r in regions
        )
        return (
            f"\n\nDETECTED DYSFLUENCY REGIONS (YOLO-Stutter local model, pre-verified):\n"
            f"{hints}\n"
            f"Treat these as confirmed disfluency locations when interpreting the raw transcript."
        )

# Usage in lavrentiy.py reconstruction pipeline:
# yolo_client = YoloStutterClient(vits_ckpt="...", detector_ckpt="...")
# regions = yolo_client.detect(audio_path, whisper_transcript)
# hint_text = yolo_client.format_for_llm_prompt(regions)
# if hint_text:
#     system_prompt += hint_text
```

### 5.2 DysfluentWFST Desktop Wrapper Sketch

```python
# NEW FILE: dysfluent_wfst_client.py (proposed, not written)

"""
Proposed DysfluentWFST integration for Lavrentiy desktop.
Prerequisites:
  - pip install torch==2.5.1 transformers==4.48.0 k2==1.24.4.dev... phonemizer espnet
  - CUDA GPU required for k2 (k2 CPU mode unstable per authors)
  - License: UNRESOLVED — contact Berkeley Speech Group before deployment
"""

import sys
sys.path.insert(0, "path/to/DysfluentWFST")  # adjust to repo location

from utils.decoder import DysfluentWFSTDecoder  # from repo

class DysfluentWFSTClient:
    def __init__(self):
        # Loads Wav2Vec2 from HuggingFace (~1.2GB download on first use)
        self.decoder = DysfluentWFSTDecoder(
            model_name="facebook/wav2vec2-xlsr-53-phon-cv-ft",
            device="cuda"  # CPU mode unstable per authors
        )
    
    def detect(self, audio_path: str, reference_text: str) -> dict:
        """
        Zero-shot dysfluency detection.
        Returns dict with 'dys_detect' list and corrected phoneme sequence.
        """
        result = self.decoder.decode(audio_path, reference_text)
        return result
    
    def format_for_llm_prompt(self, result: dict) -> str:
        """Format WFST output for L4 LLM prompt injection."""
        dys = result.get('dys_detect', [])
        if not dys:
            return ""
        hints = "; ".join(
            f"{d['dysfluency_type']} on phoneme /{d['phoneme']}/ (state {d['start_state']}–{d['end_state']})"
            for d in dys if d['dysfluency_type'] != 'normal'
        )
        return f"\n\nDETECTED DYSFLUENCIES (DysfluentWFST phoneme-level):\n{hints}"
```

**Desktop setup effort:** 
- YOLO-Stutter: ~1 day. `conda env create -f environment.yml`, download checkpoints from Google Drive, verify `monotonic_align` Cython build on Windows.
- DysfluentWFST: ~0.5 days (if CUDA available). `pip install` dependencies, auto-downloads encoder. Requires resolving license before any production use.

---

## 6. Head-to-Head Comparison

### 6.1 What the Comparison Is and Is Not

**Critical framing:** YOLO-Stutter and DysfluentWFST solve a **different problem** than whisper.cpp or Moonshine. Whisper and Moonshine perform ASR (speech → text). YOLO-Stutter and DysfluentWFST perform dysfluency detection (stuttered speech → labeled disfluency regions).

These are not mutually exclusive — they address adjacent problems in a pipeline:

```
[Audio] → [ASR: whisper.cpp / Moonshine] → [Text] → [L4 GPT-4o] → [Corrected text]
                                             ↑
                    [Optional: YOLO-Stutter / DysfluentWFST] → [Dysfluency labels]
```

The correct comparison question is not "which ASR is better" but "do dysfluency labels from YOLO-Stutter or DysfluentWFST improve L4 reconstruction quality over the current heuristic-only approach?"

### 6.2 Comparative Table

| Dimension | whisper.cpp (current ASR) | Moonshine (proposed ASR) | YOLO-Stutter | DysfluentWFST |
|---|---|---|---|---|
| **Problem solved** | ASR (speech → text) | ASR (speech → text) | Dysfluency detection | Dysfluency detection |
| **WER on stuttered speech** | ~36% (Xu 2025) | ~15–25% (estimated for small model on stuttered speech) **[speculative]** | N/A (not ASR) | N/A (reports Weight PER) |
| **Output type** | Text transcript | Text transcript | Dysfluency label sequence | Phoneme + dysfluency labels |
| **Parameter count** | 75M (base.en) / 242M (small.en) | ~37M (Moonshine Small) | ~30M (VITS) + ~5M (decoder) | ~300M (Wav2Vec2) + 0 (WFST) |
| **Checkpoint format** | GGML (quantized) | GGML or safetensors | PyTorch `.pth` | PyTorch `.bin` (via HuggingFace) |
| **Mobile ARM64** | ✓ Excellent (GGML is optimized for ARM) | ✓ Good | ⚠️ Moderate (Cython blocker) | ❌ Not feasible (k2 CUDA) |
| **License** | MIT | Apache 2.0 | MIT | ⚠️ Unspecified |
| **Training data type** | Multilingual diverse speech | Multilingual diverse speech | Synthetic stuttered speech (VCTK) | Zero-shot (no training) |
| **Requires reference text** | No | No | **Yes** | **Yes** |
| **Real-time factor** | ~0.05x (ggml-base.en) | ~0.03x (estimated) | ~0.1–0.3x (estimated) **[speculative]** | ~0.5–1.0x (estimated) **[speculative]** |
| **Integration complexity** | ✓ Already integrated | Moderate (model swap) | High (Cython, ONNX export) | Very High (k2 CUDA, 300M model) |
| **Multilingual** | ✓ Yes (99 languages) | Partial | ❌ No (VCTK-only training) | ✓ Yes (Wav2Vec2-XLSR-53) |

### 6.3 Reference Text Dependency — A Shared Hard Constraint

Both YOLO-Stutter and DysfluentWFST require a **reference text** (phoneme or word sequence) to compute alignment or FSA paths. For WiM's use case — real-time speech correction from voice input — the reference text is not available before ASR runs.

**This creates a chicken-and-egg problem:**
- ASR (Whisper) runs first to produce a transcript
- The transcript contains disfluencies that corrupt the word sequence
- YOLO-Stutter/DysfluentWFST use the (corrupted) transcript as reference to detect disfluencies
- The detected disfluencies inform a cleaned reconstruction

**Implication:** Both models would be processing a disfluent reference text, which may degrade their alignment accuracy. The detection quality is bounded by the quality of the ASR transcript being used as reference. For severely stuttered speech where Whisper WER is 36%+, the detection models receive a noisy reference.

**Mitigation (speculative):** Run a fast "draft" Whisper pass → YOLO-Stutter detection → L4 reconstruction with labels injected. The draft transcript's errors would be partially corrected by YOLO-Stutter's labeled outputs. This is a plausible two-stage pipeline but requires engineering validation. **[Speculative — not benchmarked]**

---

## 7. Recommendation

### 7.1 Integration Verdict

| Scenario | Verdict | Rationale |
|---|---|---|
| **Integrate YOLO-Stutter into WiM Android** | ❌ Not now | Cython blocker requires NDK cross-compilation; ONNX export path not validated; no documented benefit to L4 reconstruction quality yet |
| **Integrate YOLO-Stutter into Lavrentiy desktop** | ⚠️ Research track only | Feasible technically; but synthetic training data (VCTK-Stutter) means detection quality on real clinical speech is unvalidated; integrate only after benchmarking against George's real audio corpus |
| **Integrate DysfluentWFST into WiM Android** | ❌ Hard no | k2 CUDA dependency is a multi-month port; 300M Wav2Vec2 RAM cost; no license |
| **Integrate DysfluentWFST into Lavrentiy desktop** | ⚠️ License-gated | Zero-shot multilingual capability is genuinely valuable; but missing license blocks any deployment; contact Berkeley Speech Group for license clarification before touching |
| **Replace whisper.cpp with YOLO-Stutter** | ❌ Wrong problem | YOLO-Stutter is not an ASR model; it requires ASR output as input; cannot replace whisper.cpp |
| **Replace whisper.cpp with Moonshine** | Out of scope for this memo | Addressed separately |

### 7.2 Recommended Path Forward

**Immediate (0–4 weeks): Neither model in production.**

Both models have validation gaps that prevent production deployment:
1. YOLO-Stutter's training data is entirely synthetic (VCTK-Stutter), and detection quality on real clinical stuttered speech is unverified. The Interspeech 2024 paper numbers exist but are not available without the PDF, and were measured on VCTK-based test splits — not FluencyBank or real-world data.
2. DysfluentWFST lacks a license.
3. Neither model's integration enriches the L4 path without a pipeline re-architecture and A/B validation using the `_phase4_ears_benchmark.py` harness.

**Medium-term (1–3 months): Lavrentiy desktop prototype.**

If the YOLO-Stutter Interspeech 2024 paper confirms competitive detection F1 on real speech:
1. Install YOLO-Stutter in a separate Lavrentiy conda environment
2. Run `_phase4_ears_benchmark.py` Phase 2 on George's existing audio archive, comparing:
   - **Control:** Current L4 path (no detection labels)
   - **Treatment:** L4 path with YOLO-Stutter dysfluency labels injected into system prompt
3. Measure improvement in `word_repeat_collapse_rate`, `fragment_strip_rate`, `covert_recovery` per the benchmark's Phase 2 metrics

**For DysfluentWFST:** Email Berkeley Speech Group (Gopala Anumanchipalli lab) for license clarification. If Apache 2.0 or MIT is granted, run the same A/B test. DysfluentWFST's zero-shot multilingual capability gives it a significant advantage for the 10-language expansion planned in WiM.

**Long-term (3–6 months): Android integration if desktop A/B shows benefit.**

If the desktop A/B test confirms that dysfluency labels improve L4 reconstruction by a meaningful margin (e.g., >10% improvement in `word_repeat_collapse_rate` precision on a test of real stuttered speech), then:
1. YOLO-Stutter ONNX export project (est. 3–5 days)
2. NDK cross-compilation of Cython `monotonic_align` (est. 3–5 days, or pure-Python replacement)
3. PyTorch Mobile / ONNX Runtime integration in WiM Android

This path should only be started if the desktop A/B test is conclusive. The engineering cost (2–3 weeks for Android) is only justified if the quality improvement is confirmed.

### 7.3 Risk-Adjusted Recommendation

**Integrate neither model now.** The engineering cost of integration exceeds the demonstrated quality benefit at this stage. The prior `stutterzero_checkpoint_research.md` memo correctly identified YOLO-Stutter and Stutter-Solver as promising alternatives, but incorrectly characterized them as reconstruction models with vocalizers. They are detection-only, and their value to WiM is conditional on the L4 enrichment path working — which requires a desktop A/B experiment first.

**The single highest-value action from this research:** Contact the Berkeley Speech Group for a DysfluentWFST license. If the license is Apache 2.0 or MIT, DysfluentWFST's zero-shot multilingual detection is the only evaluated model that could serve the 10-language WiM expansion without requiring new training data per language.

---

## 8. Citations

1. **Zhou, X., Mukherjee, S., Sivaraman, A., & Anumanchipalli, G.** (2024). YOLO-Stutter: End-to-end Region-Wise Speech Dysfluency Detection. *Interspeech 2024*, DOI: 10.21437/Interspeech.2024-1855. arXiv:2408.15297. GitHub: https://github.com/rorizzz/yolo-stutter

2. **Berkeley Speech Group.** (2025). Dysfluent WFST: A Framework for Zero-Shot Speech Dysfluency Transcription and Detection. *Interspeech 2025* (accepted). arXiv:2505.16351. GitHub: https://github.com/Berkeley-Speech-Group/DysfluentWFST

3. **Kim, J., Kong, J., & Son, J.** (2021). Conditional Variational Autoencoder with Adversarial Learning for End-to-End Text-to-Speech. *ICML 2021*. GitHub: https://github.com/jaywalnut310/vits. *(VITS, used as YOLO-Stutter's encoder backbone)*

4. **Baevski, A., Zhou, H., Mohamed, A., & Auli, M.** (2020). wav2vec 2.0: A Framework for Self-Supervised Learning of Speech Representations. *NeurIPS 2020*. HuggingFace: `facebook/wav2vec2-xlsr-53-phon-cv-ft`. *(Encoder backbone for DysfluentWFST)*

5. **Xu, Q.** (2025). StutterZero and StutterFormer: End-to-End Speech Conversion for Stuttering Transcription and Correction. *IEEE Access*, 13. arXiv:2510.18938. *(Cited for whisper.cpp WER of 36.1% on stuttered speech baseline)*

6. **Povey, D., et al.** (2020). k2: A Framework for Efficient, GPU-accelerated FST Operations. GitHub: https://github.com/k2-fsa/k2. *(k2 framework used by DysfluentWFST for WFST decoding)*

7. **Anumanchipalli, G. K., et al.** (2024). Dysfluent WFST. ISCA Archive: https://www.isca-archive.org *(Interspeech 2025 paper, see arXiv:2505.16351 for preprint)*

---

## Appendix: Open Unknowns

| Unknown | Impact | Resolution Path |
|---|---|---|
| YOLO-Stutter actual detection F1 on real stuttered speech (not VCTK-Stutter synthetic) | High | Obtain paper PDF (Interspeech 2024); run on FluencyBank test set |
| DysfluentWFST Weight PER numbers | Medium | Obtain Interspeech 2025 paper PDF |
| DysfluentWFST license | **Hard blocker** | Email corresponding author: gopala@berkeley.edu |
| Moonshine WER on stuttered speech (for comparison in Section 6) | Medium | Run `_phase4_ears_benchmark.py` Phase 1 once Moonshine is installed |
| YOLO-Stutter ONNX export feasibility (Cython `monotonic_align` replacement) | High for Android | Prototype on desktop first (1-day experiment) |
| Whether L4 prompt enrichment with detection labels actually improves reconstruction | **Core question** | Desktop A/B test using Phase 2 benchmark — this is the prerequisite for all Android integration work |

---

*End of Memo. File: `lavrentiy/docs/yolo_stutter_stutter_solver_evaluation.md`. Untracked — do not commit.*
