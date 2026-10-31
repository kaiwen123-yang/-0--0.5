"""A one-parameter contact-solver intervention, never the original benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import evaluate
from sim import ColorEnv


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--impratio", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args, rest = parser.parse_known_args()

    class ContactProbeEnv(ColorEnv):
        def __init__(self, render=False):
            super().__init__(render=render)
            self.model.opt.impratio = args.impratio

    evaluate.ColorEnv = ContactProbeEnv
    sys.argv = [sys.argv[0], "--output", str(args.output), *rest]
    try:
        evaluate.main()
    finally:
        if args.output.exists():
            record = {"diagnostic_only": True, "original_benchmark_success_rate_eligible": False,
                      "changed_parameter": "mjModel.opt.impratio", "original_value": 1.0,
                      "intervention_value": args.impratio, "model_updated": False,
                      "friction_coefficient_changed": False, "gripper_force_changed": False,
                      "success_conditions_changed": False,
                      "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            (args.output / "contact_intervention.json").write_text(json.dumps(record, indent=2))
