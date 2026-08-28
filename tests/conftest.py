"""Gemeinsame Fixtures für die Stundenplan-Testsuite."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def plan_sample_bytes() -> bytes:
    """Rohe Bytes der synthetischen Beispiel-XML-Datei (inkl. BOM)."""
    return (FIXTURES_DIR / "plan_sample.xml").read_bytes()


@pytest.fixture
def plan_sample_date() -> date:
    """Das im Dateinamen von plan_sample.xml kodierte Datum."""
    return date(2026, 8, 28)
