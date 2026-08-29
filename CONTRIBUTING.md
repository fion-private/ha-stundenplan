# Contributing

Thanks for considering a contribution to this integration!

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-test.txt
```

## Running the checks locally

These are the same checks the CI pipeline (`.github/workflows/ci.yml`) runs
on every push and pull request:

```bash
# Linting (pyflakes, pycodestyle, isort, bugbear, ...)
ruff check .

# Formatting (Black-compatible)
ruff format --check .
# ... or to auto-fix formatting:
ruff format .

# Static type checking
mypy custom_components

# Unit tests with coverage
pytest --cov=custom_components/stundenplan --cov-report=term-missing
```

## Test suite structure

- `tests/test_api_parsing.py` – pure XML parsing logic (`api.parse_plan_xml`,
  `Lesson`). No network, no Home Assistant runtime required.
- `tests/test_api_client.py` – HTTP behavior of `Stundenplan24Client`
  (auth errors, 404 handling, probing), mocked via `aioresponses`. No real
  network access.
- `tests/test_coordinator.py` – the coordinator's filtering and evaluation
  logic (`_is_ignored`, `_determine_first_lesson`, `_determine_last_lesson`,
  `_lesson_to_dict`), exercised directly/via a minimally constructed
  coordinator instance (`object.__new__`), without spinning up a full Home
  Assistant core.
- `tests/fixtures/plan_sample.xml` – a small, synthetic (**not real school
  data**) XML file mirroring the structure of a real Stundenplan24/Indiware
  `PlanKl*.xml` export, including a regular lesson, a changed lesson, a
  fully cancelled lesson (only recoverable via the free-text hint) and a
  split course group (`<Ku2>`).

**Out of scope for now:** end-to-end tests that exercise the full config
flow or a complete coordinator refresh cycle (including the `hass.services`
calendar lookup) against a real, running Home Assistant core via
`pytest-homeassistant-custom-component`. Contributions adding these are
very welcome.

## Code style

- Python 3.13, formatted and linted with [ruff](https://docs.astral.sh/ruff/)
  (configuration in `pyproject.toml`), which enforces PEP 8 plus import
  sorting, pyupgrade and a few common bug-pattern checks - the same tooling
  Home Assistant core itself uses.
- Type hints are checked with `mypy`.
- All source code (identifiers, comments, docstrings) is in English. Only
  the user-facing strings in `strings.json`/`translations/*.json` are
  localized (English source/fallback, German translation) - please add new
  strings to **both** language files in the same PR.

## Submitting changes

1. Fork the repository and create a branch from `main`.
2. Make your change, including tests.
3. Make sure all checks above pass locally.
4. Open a pull request describing the change.
