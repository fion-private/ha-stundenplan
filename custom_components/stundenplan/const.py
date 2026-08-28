"""Konstanten für die Stundenplan24 / Indiware Integration."""
from __future__ import annotations

DOMAIN = "stundenplan"

BASE_URL = "https://www.stundenplan24.de"
REQUEST_TIMEOUT = 20  # Sekunden
PROBE_DAYS = 14  # Wie viele Tage im Config-/Options-Flow nach einem Plan gesucht wird

CONF_SCHULNUMMER = "schulnummer"
CONF_KLASSE = "klasse"
CONF_ABRUFZEIT = "abrufzeit"
CONF_IGNORIERTE_FAECHER = "ignorierte_faecher"
CONF_IGNORIERTE_KURSE = "ignorierte_kurse"
CONF_FERIEN_KALENDER = "ferien_kalender"

DEFAULT_ABRUFZEIT = "18:00:00"

STATUS_REGULAR = "regulaer"
STATUS_CHANGED = "geaendert"
STATUS_CANCELLED = "entfaellt"
