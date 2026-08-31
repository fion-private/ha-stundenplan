"""Shared fixtures for the Stundenplan test suite."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def plan_sample_bytes() -> bytes:
    """Raw bytes of the synthetic sample XML file (including BOM)."""
    return (FIXTURES_DIR / "plan_sample.xml").read_bytes()


@pytest.fixture
def plan_sample_date() -> date:
    """The date encoded in plan_sample.xml's filename."""
    return date(2026, 8, 28)
