"""config/weights.yaml: it parses, its weights sum to one, and the frozen v1.0 file is unchanged.

PREREGISTRATION.md section 1 records the SHA-256 of config/weights.yaml at the v1.0 freeze. The hash
test is the guard against an accidental edit of the frozen file; an intentional change belongs to a
new method version with its own pre-registration, and then this constant moves with it.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

FROZEN_WEIGHTS_SHA256 = "ea1a823c00533496e89b08afaa0869a2e71ca324584c49d05cb0c7c47be15cc2"


def test_weights_yaml_parses_to_a_mapping(root: Path) -> None:
    cfg = yaml.safe_load((root / "config" / "weights.yaml").read_text())
    assert isinstance(cfg, dict)
    for key in ("weights", "elo", "resume", "board_model", "board_size", "method_version"):
        assert key in cfg, key


def test_resume_weights_sum_to_one(weights_cfg: dict) -> None:
    w = weights_cfg["resume"]["weights"]
    assert set(w) == {"rating", "quality_wins"}
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert all(v >= 0 for v in w.values())


def test_composite_weights_sum_to_one(weights_cfg: dict) -> None:
    w = weights_cfg["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-9     # rankings.main asserts the same at run time
    assert all(v >= 0 for v in w.values())


def test_resume_horizons_and_engine_are_well_formed(weights_cfg: dict) -> None:
    rc = weights_cfg["resume"]
    horizons = {float(k): float(v) for k, v in rc["horizons"].items()}
    limits = sorted(horizons)
    assert [horizons[k] for k in limits] == sorted(horizons.values(), reverse=True)   # older wins weigh less
    assert all(0.0 <= v <= 1.0 for v in horizons.values())
    eng = rc["engine"]
    assert 0.0 < eng["protected_loss_mult"] < eng["consecutive_loss_mult"] < eng["dominant_loss_mult"] <= 1.0
    assert 0.0 <= eng["card_weight"] <= 1.0


def test_weights_yaml_matches_the_frozen_v1_hash(root: Path) -> None:
    digest = hashlib.sha256((root / "config" / "weights.yaml").read_bytes()).hexdigest()
    assert digest == FROZEN_WEIGHTS_SHA256, (
        "config/weights.yaml differs from the frozen v1.0 file recorded in PREREGISTRATION.md; "
        "revert it, or publish a new method version with its own pre-registration"
    )


def test_frozen_hash_constant_agrees_with_preregistration(root: Path) -> None:
    text = (root / "PREREGISTRATION.md").read_text()
    m = re.search(r"`config/weights\.yaml`\s+([0-9a-f]{64})", text)
    assert m, "PREREGISTRATION.md no longer records the weights.yaml hash"
    assert m.group(1) == FROZEN_WEIGHTS_SHA256
