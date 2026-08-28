# Stundenplan

*Home Assistant Integration for Indiware Stundenplan*

[![CI](https://github.com/fion-private/ha-stundenplan/actions/workflows/ci.yml/badge.svg)](https://github.com/fion-private/ha-stundenplan/actions/workflows/ci.yml)
[![HACS Custom Repository](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/github/license/fion-private/ha-stundenplan)](LICENSE)

A Home Assistant custom integration that fetches a class's timetable and
daily substitution plan from [Stundenplan24.de](https://www.stundenplan24.de)
(Indiware) and exposes the first lesson of the day plus the full, filtered
day plan as sensors — ready to be used in automations and, eventually, a
dashboard card.

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

1. **Credentials**: school number, username, password, and the daily fetch
   time (e.g. 18:30). Home Assistant verifies the credentials immediately by
   searching the next few days for a published plan.
2. **Class**: chosen from the classes found in the plan (e.g. "8a").
3. **Ignore subjects & courses**: pick subjects to ignore from the class's
   real subject catalog. If the class has split course groups (e.g. two
   parallel courses within the same subject, such as "TC1"/"TC2"), also pick
   the group(s) that don't apply to you. Both are excluded from the "first
   lesson" sensor **and** from the stored day plan — including when a
   lesson is fully cancelled (see [Limitations](#known-limitations)).
4. **Holiday calendar (optional)**: a `calendar.*` entity containing school
   holidays. On days with an event in that calendar, no fetch is performed.

If no plan can be found during initial setup (e.g. during summer holidays),
you can enter the class name manually as text; the subject/course filters
can then be configured later via **Configure**, once plans are published
again.

All settings can be changed at any time via **Configure** on the
integration.

## When does it fetch?

- The fetch is **time-triggered**, exactly at the configured time — there is
  no polling interval.
- It always fetches the plan for the **next calendar day**.
- Before every fetch, Home Assistant checks whether there's school at all:
  - **Weekend** (Sat/Sun) → no fetch.
  - **Holidays** contained in the most recently fetched plan
    (`<FreieTage>`) → no fetch.
  - If configured: an event in the **holiday calendar** for the target date
    → no fetch.
- A `404` response (no plan published for the target date) is treated as a
  normal state, not an error.
- On genuine authentication failures (401/403), Home Assistant automatically
  starts a "Reauthenticate" flow.

## Entities

| Entity | Description |
|---|---|
| `sensor.<class>_erste_stunde` | Start time of the first lesson (cancellations and ignored subjects/courses excluded). Attributes: `stunde` (period number), `ende`, `faecher` (list, for parallel groups). |
| `sensor.<class>_tagesplan` | Target date as its state. The `stunden` attribute holds the complete, filtered list of all lessons (subject, course group, teacher, room, hint text, status `regulaer`/`geaendert`/`entfaellt`) — the basis for a future dashboard card. |

Both sensors also expose `ziel_datum`, `kein_plan_gefunden` and
`uebersprungen_grund` (e.g. `wochenende`, `ferien`, `ferien_kalender`) so you
can react to them in automations/templates.

## Service

`stundenplan.refresh` — fetches the plan immediately (e.g. for testing). The
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
course lessons are filtered correctly too.

For subjects **without** split course groups that are fully cancelled, the
XML contains neither a subject code nor a course code, only a free-text hint
(e.g. "MA Frau Matthes fällt aus"). In that case, the integration extracts
the likely subject code from the hint text (first word, optionally after
"für " or after a semicolon) and matches it against your ignored subjects
too. This is a heuristic based on the typical phrasing used by Indiware
substitution plans and may occasionally be wrong for unusual phrasing.

## Known limitations

- The hint-text heuristic described above is not 100% guaranteed to be
  correct, since it relies on typical substitution-text phrasing rather than
  structured data.
- **Holiday calendar**: currently checks whether *any* event exists on the
  target date in the configured calendar. Finer control (e.g. matching only
  specific event titles) could be added in a future version.

## Dashboard card

The complete day plan data is already available, structured, in the
`stunden` attribute of the day-plan sensor. A dedicated Lovelace card for it
is a natural next step.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, running the linter
(`ruff`), type checker (`mypy`) and the unit test suite (`pytest`) — the
same checks enforced by the [CI pipeline](.github/workflows/ci.yml) on every
push and pull request.

## License

[MIT](LICENSE)
