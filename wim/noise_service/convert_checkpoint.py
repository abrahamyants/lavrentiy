"""Convert the pinned trusted Lightning checkpoint into inference-only weights."""

import argparse
import json
from pathlib import Path

import torch
from safetensors.torch import save_file

from baseline_code.flow_model import FlowSEModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model = FlowSEModel.load_from_checkpoint(args.checkpoint, map_location="cpu")
    model.eval()
    state = {
        key: value.detach().cpu().contiguous()
        for key, value in model.state_dict().items()
    }
    save_file(
        state,
        str(output_dir / "flow_bsrnn.safetensors"),
        metadata={
            "source_commit": args.source_commit,
            "checkpoint_sha256": args.checkpoint_sha256,
            "weights": "published EMA weights",
        },
    )
    config = vars(model.cfg).copy()
    config["source_commit"] = args.source_commit
    config["checkpoint_sha256"] = args.checkpoint_sha256
    (output_dir / "flow_bsrnn.config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    torch.set_grad_enabled(False)
    main()
