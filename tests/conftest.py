"""Shared pytest fixtures. Every fixture reads local files only; no test touches the network."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:          # pytest.ini sets pythonpath=src; this covers other runners
    sys.path.insert(0, str(SRC))

PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"


@pytest.fixture(scope="session")
def root() -> Path:
    """Repository root (the directory holding config/, data/ and src/)."""
    return ROOT


@pytest.fixture(scope="session")
def bouts() -> pd.DataFrame:
    """data/processed/bouts.csv as ingest.py wrote it, dates parsed."""
    return pd.read_csv(PROC / "bouts.csv", parse_dates=["date"])


@pytest.fixture(scope="session")
def bouts_with_stats() -> pd.DataFrame:
    """data/processed/bouts_with_stats.csv, the input of the rating engines."""
    return pd.read_csv(PROC / "bouts_with_stats.csv", parse_dates=["date"])


@pytest.fixture(scope="session")
def weights_cfg() -> dict:
    """Parsed config/weights.yaml."""
    return yaml.safe_load((CONFIG / "weights.yaml").read_text())
