# Stundenplan

*Home Assistant Integration für Indiware Stundenplan*

[![CI](https://github.com/fion-private/ha-stundenplan/actions/workflows/ci.yml/badge.svg)](https://github.com/fion-private/ha-stundenplan/actions/workflows/ci.yml)
[![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/github/license/fion-private/ha-stundenplan)](LICENSE)

A Home Assistant custom integration that fetches a class's timetable and
daily substitution plan from [Stundenplan24.de](https://www.stundenplan24.de)
(Indiware) for **today and tomorrow**, and exposes the first lesson, the
last lesson, and the full filtered day plan for each of those two days as
sensors — ready to be used in automations and, eventually, a dashboard card.

## Installation

### Option A: HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fion-private&repository=ha-stundenplan&category=integration)

1. Click the button above (or in HACS: **⋮ → Custom repositories**, add
   `https://github.com/fion-private/ha-stundenplan` as category
   **Integration**).
2. Find **Stundenplan** in HACS and click **Download**.
3. Restart Home Assistant.
4. Continue with [Configuration](#configuration) below.

### Option B: Manual installation

1. Download the latest release (or clone this repository).
2. Copy the `custom_components/stundenplan` folder into your Home Assistant
   configuration directory, so you end up with
   `<config>/custom_components/stundenplan/…`.
3. Restart Home Assistant.
4. Continue with [Configuration](#configuration) below.

## Configuration

Go to **Settings → Devices & Services → Add Integration** and search for
**Stundenplan**. The setup wizard walks you through:

1. **Credentials**: school number, username, password. Home Assistant
   verifies the credentials immediately by searching the next few days for
   a published plan.
2. **Class**: chosen from the classes found in the plan (e.g. "8a").
3. **Ignore subjects & courses**: pick subjects to ignore from the class's
   real subject catalog. If the class has split course groups (e.g. two
   parallel courses within the same subject, such as "TC1"/"TC2"), also pick
   the group(s) that don't apply to you. Both are excluded from the
   first/last-lesson sensors **and** from the stored day plans — including
   when a lesson is fully cancelled (see [Limitations](#known-limitations)).
4. **Holiday calendar (optional)**: a `calendar.*` entity containing school
   holidays. On days with an event in that calendar, no fetch is performed
   for that day.

If no plan can be found during initial setup (e.g. during summer holidays),
you can enter the class name manually as text; the subject/course filters
can then be configured later via **Configure**, once plans are published
again.

All settings can be changed at any time via **Configure** on the
integration.

## When does it fetch?

- The integration polls **every hour** (no configurable time - see
  `const.UPDATE_INTERVAL`) and, on every poll, retrieves **both today's and
  tomorrow's** plan (two separate requests), so both days' entities pick up
  a substitution soon after it's published, even mid-day.
- Before fetching either day, Home Assistant checks whether there's school
  on that specific day at all:
  - **Weekend** (Sat/Sun) → no fetch for that day.
  - **Holidays** contained in the most recently fetched plan
    (`<FreieTage>`) → no fetch for that day.
  - If configured: an event in the **holiday calendar** on that day → no
    fetch for that day.
- A `404` response (no plan published for a given date) is treated as a
  normal state for that day, not an error.
- If fetching either day hits a real connection error, the whole update is
  retried at the next hourly poll and the previous data is kept meanwhile
  (standard Home Assistant coordinator behavior) — a failure on one day
  never mixes stale and fresh data.
- On genuine authentication failures (401/403), Home Assistant automatically
  starts a "Reauthenticate" flow.
- Use the `stundenplan.refresh` [service](#service) if you want to fetch
  immediately instead of waiting for the next hourly poll.

## Entities

Every entity exists twice: once for **today** and once for **tomorrow**.

| Entity | Description |
|---|---|
| `sensor.<class>_lesson_start_today` / `_tomorrow` | Start time of the first lesson of that day (cancellations and ignored subjects/courses excluded). Attributes: `period`, `end`, `subjects` (list, for parallel groups). |
| `sensor.<class>_lesson_end_today` / `_tomorrow` | End time of the last lesson of that day (same exclusions as above). Attributes: `period`, `start`, `subjects`. |
| `sensor.<class>_day_plan_today` / `_tomorrow` | The day's target date as its state. The `lessons` attribute holds the complete, filtered list of all lessons (subject, course group, teacher, room, note, status `regular`/`changed`/`cancelled`) — the basis for a future dashboard card. |

All six sensors also expose `target_date`, `plan_not_found` and
`skipped_reason` (e.g. `weekend`, `holiday`, `holiday_calendar`) so you can
react to them in automations/templates.

## Service

`stundenplan.refresh` — fetches today's and tomorrow's plan immediately
instead of waiting for the next hourly poll (e.g. for testing). The
weekend/holiday checks described above still apply. Optional field
`entry_id` to refresh only a specific configured entry; if omitted, all
configured entries are refreshed.

## How split course groups are filtered

Some subjects are split within a class (e.g. two parallel courses in the
same subject, or religion/ethics). The source XML provides a course catalog
per class (`<Kurse>`) plus, where applicable, a `<Ku2>` code per plan entry
(e.g. "TC1", "DeRS", "Inf2"). Use the **course group** selection in the
config dialog to hide the group that doesn't apply to your child.

If such a course lesson is fully cancelled, the `<Ku2>` code is preserved in
the source XML even though the subject itself shows as `---` — so cancelled
course lessons are filtered correctly too, on both the first- and
last-lesson sensors.

For subjects **without** split course groups that are fully cancelled, the
XML contains neither a subject code nor a course code, only a free-text note
(e.g. "MA Frau Matthes fällt aus"). In that case, the integration extracts
the likely subject code from the note text (first word, optionally after
"für " or after a semicolon) and matches it against your ignored subjects
too. This is a heuristic based on the typical phrasing used by Indiware
substitution plans and may occasionally be wrong for unusual phrasing.

## Known limitations

- The note-text heuristic described above is not 100% guaranteed to be
  correct, since it relies on typical substitution-text phrasing rather than
  structured data.
- **Holiday calendar**: currently checks whether *any* event exists on a
  given day in the configured calendar. Finer control (e.g. matching only
  specific event titles) could be added in a future version.

## Dashboard card

The complete day plan data is already available, structured, in the
`lessons` attribute of the day-plan sensors. A dedicated Lovelace card for
it (`ha-stundenplan-ui`) is being developed as a companion project.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, running the linter
(`ruff`), type checker (`mypy`) and the unit test suite (`pytest`) — the
same checks enforced by the [CI pipeline](.github/workflows/ci.yml) on every
push and pull request.

## License

[MIT](LICENSE)
