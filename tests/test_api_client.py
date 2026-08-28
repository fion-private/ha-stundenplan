"""Tests für custom_components.stundenplan.api.Stundenplan24Client.

HTTP-Aufrufe werden über `aioresponses` gemockt - es findet kein echter
Netzwerkzugriff statt.
"""
from __future__ import annotations

from datetime import date

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.stundenplan.api import (
    Stundenplan24AuthError,
    Stundenplan24Client,
    Stundenplan24ConnectionError,
    Stundenplan24NotFoundError,
)
from custom_components.stundenplan.const import BASE_URL

SCHULNUMMER = "12345678"


def _url_for(ziel_datum: date) -> str:
    return f"{BASE_URL}/{SCHULNUMMER}/mobil/mobdaten/PlanKl{ziel_datum:%Y%m%d}.xml"


@pytest.fixture
async def client():
    async with aiohttp.ClientSession() as session:
        yield Stundenplan24Client(session, SCHULNUMMER, "user", "pass")


async def test_fetch_raw_erfolgreich(client, plan_sample_bytes, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=200, body=plan_sample_bytes)
        raw = await client.async_fetch_raw(plan_sample_date)
    assert raw == plan_sample_bytes


async def test_fetch_plan_parst_ergebnis(client, plan_sample_bytes, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=200, body=plan_sample_bytes)
        plan = await client.async_fetch_plan(plan_sample_date)
    assert "5a" in plan.klassen


@pytest.mark.parametrize("status", [401, 403])
async def test_fetch_raw_auth_fehler(client, plan_sample_date, status):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=status)
        with pytest.raises(Stundenplan24AuthError):
            await client.async_fetch_raw(plan_sample_date)


async def test_fetch_raw_404_wird_zu_not_found(client, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=404)
        with pytest.raises(Stundenplan24NotFoundError):
            await client.async_fetch_raw(plan_sample_date)


async def test_fetch_raw_serverfehler_wird_zu_connection_error(client, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=500)
        with pytest.raises(Stundenplan24ConnectionError):
            await client.async_fetch_raw(plan_sample_date)


async def test_verify_credentials_akzeptiert_404_als_gueltig(client):
    with aioresponses() as mocked:
        mocked.get(_url_for(date.today()), status=404)
        # Darf keine Exception werfen - 404 heißt nur "kein Plan heute",
        # nicht "falsche Zugangsdaten".
        await client.async_verify_credentials()


async def test_verify_credentials_wirft_bei_auth_fehler(client):
    with aioresponses() as mocked:
        mocked.get(_url_for(date.today()), status=401)
        with pytest.raises(Stundenplan24AuthError):
            await client.async_verify_credentials()


async def test_probe_ueberspringt_404_und_findet_naechsten_plan(
    client, plan_sample_bytes
):
    start = date(2026, 8, 26)
    with aioresponses() as mocked:
        mocked.get(_url_for(start), status=404)
        mocked.get(_url_for(date(2026, 8, 27)), status=404)
        mocked.get(_url_for(date(2026, 8, 28)), status=200, body=plan_sample_bytes)

        plan = await client.async_probe(start, max_days=5)

    assert plan is not None
    assert plan.ziel_datum == date(2026, 8, 28)


async def test_probe_gibt_none_zurueck_wenn_nichts_gefunden(client):
    start = date(2026, 8, 26)
    with aioresponses() as mocked:
        for offset in range(3):
            mocked.get(_url_for(date(2026, 8, 26 + offset)), status=404)
        plan = await client.async_probe(start, max_days=3)
    assert plan is None


async def test_probe_bricht_bei_auth_fehler_sofort_ab(client):
    start = date(2026, 8, 26)
    with aioresponses() as mocked:
        mocked.get(_url_for(start), status=401)
        with pytest.raises(Stundenplan24AuthError):
            await client.async_probe(start, max_days=5)
