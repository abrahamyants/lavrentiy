import os
import sys
import time
import json
import logging
import hashlib
from typing import Dict, List, Any

try:
    from google.cloud import firestore
except ImportError:
    firestore = None

logger = logging.getLogger(__name__)

# Global in-memory cache for idempotency
_last_payload_hash = None

def get_payload_hash(payload: Dict[str, Any]) -> str:
    # Remove volatile keys for hashing
    hashable = {k: v for k, v in payload.items() if k != "updated_at"}
    return hashlib.md5(json.dumps(hashable, sort_keys=True).encode("utf-8")).hexdigest()

def publish_profile_to_firestore(uid: str, trigger_words: List[str], onset_weights: Dict[str, float], covert_profile: Dict[str, Any]) -> bool:
    global _last_payload_hash

    if firestore is None:
        logger.error("google-cloud-firestore not installed. Skip publish.")
        return False

    payload = {
        "trigger_words": trigger_words or [],
        "onset_weights": onset_weights or {},
        "covert_profile": covert_profile or {},
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    current_hash = get_payload_hash(payload)
    if current_hash == _last_payload_hash:
        return True  # Idempotent: nothing changed

    for attempt in range(3):
        try:
            db = firestore.Client()
            doc_ref = db.collection("wim_users").document(uid)
            doc_ref.set(payload, merge=True)
            _last_payload_hash = current_hash
            return True
        except Exception as e:
            logger.error(f"Firestore publish error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return False
    return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Publish learned structures to Firestore.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without actually writing.")
    parser.add_argument("--uid", type=str, required=True, help="Target user ID.")
    args = parser.parse_args()

    dummy_tw = ["example"]
    dummy_ow = {"/k/": 0.8}
    dummy_cp = {"avoidance_pairs": {}}

    payload = {
        "trigger_words": dummy_tw,
        "onset_weights": dummy_ow,
        "covert_profile": dummy_cp,
        "updated_at": "SERVER_TIMESTAMP"
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        sys.exit(0)
    else:
        success = publish_profile_to_firestore(args.uid, dummy_tw, dummy_ow, dummy_cp)
        sys.exit(0 if success else 1)
