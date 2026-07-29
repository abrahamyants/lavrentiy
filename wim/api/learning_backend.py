"""Shared Layer 3 profile-learning request and response contract."""

import json


LEARNING_SYSTEM_PROMPT = (
    "Analyze these voice transcription pairs (raw speech -> cleaned output). "
    "Extract patterns:\n"
    "1. corrections: recurring words misheard by speech-to-text that map to "
    "different intended words (for example, \"Duncan\" -> \"Dankeschoen\"). "
    "Only include clear, confident mappings.\n"
    "2. fillers: filler words or sounds the speaker uses in any language. "
    "Only include words used as fillers, not meaningful content.\n"
    "3. vocabulary: domain-specific or preferred terms the speaker consistently uses.\n"
    "Return ONLY valid JSON: "
    "{\"corrections\": {}, \"fillers\": [], \"vocabulary\": []}. "
    "If nothing is reliable, return empty collections."
)


class LearningResponseError(ValueError):
    pass


def parse_learning_response(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise LearningResponseError("Learning response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LearningResponseError("Learning response must be an object")
    corrections = payload.get("corrections", {})
    fillers = payload.get("fillers", [])
    vocabulary = payload.get("vocabulary", [])
    if not isinstance(corrections, dict):
        raise LearningResponseError("corrections must be an object")
    if not isinstance(fillers, list) or not isinstance(vocabulary, list):
        raise LearningResponseError("fillers and vocabulary must be arrays")
    return {
        "corrections": corrections,
        "fillers": fillers,
        "vocabulary": vocabulary,
    }


def learn_from_pairs(client, model, pairs):
    if client is None:
        raise LearningResponseError("No learning API client is configured")
    if not isinstance(pairs, str) or not pairs.strip():
        raise LearningResponseError("No transcription pairs were supplied")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": LEARNING_SYSTEM_PROMPT},
            {"role": "user", "content": pairs[:12000]},
        ],
        max_tokens=300,
        temperature=0,
    )
    text = (response.choices[0].message.content or "").strip()
    return parse_learning_response(text)
