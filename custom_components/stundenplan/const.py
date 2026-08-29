"""Constants for the Stundenplan integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "stundenplan"

BASE_URL = "https://www.stundenplan24.de"
REQUEST_TIMEOUT = 20  # seconds
PROBE_DAYS = 14  # how many days ahead the config/options flow searches for a plan
UPDATE_INTERVAL = timedelta(hours=1)  # how often today's and tomorrow's plan are fetched

CONF_SCHOOL_NUMBER = "school_number"
CONF_CLASS_NAME = "class_name"
CONF_IGNORED_SUBJECTS = "ignored_subjects"
CONF_IGNORED_COURSES = "ignored_courses"
CONF_HOLIDAY_CALENDAR = "holiday_calendar"

STATUS_REGULAR = "regular"
STATUS_CHANGED = "changed"
STATUS_CANCELLED = "cancelled"
