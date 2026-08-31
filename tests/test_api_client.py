"""Tests for custom_components.stundenplan.api.Stundenplan24Client.

HTTP calls are mocked via `aioresponses` - no real network access happens.
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

SCHOOL_NUMBER = "12345678"


def _url_for(target_date: date) -> str:
    return f"{BASE_URL}/{SCHOOL_NUMBER}/mobil/mobdaten/PlanKl{target_date:%Y%m%d}.xml"


@pytest.fixture
async def client():
    async with aiohttp.ClientSession() as session:
        yield Stundenplan24Client(session, SCHOOL_NUMBER, "user", "pass")


async def test_fetch_raw_succeeds(client, plan_sample_bytes, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=200, body=plan_sample_bytes)
        raw = await client.async_fetch_raw(plan_sample_date)
    assert raw == plan_sample_bytes


async def test_fetch_plan_parses_result(client, plan_sample_bytes, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=200, body=plan_sample_bytes)
        plan = await client.async_fetch_plan(plan_sample_date)
    assert "5a" in plan.classes


@pytest.mark.parametrize("status", [401, 403])
async def test_fetch_raw_auth_error(client, plan_sample_date, status):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=status)
        with pytest.raises(Stundenplan24AuthError):
            await client.async_fetch_raw(plan_sample_date)


async def test_fetch_raw_404_becomes_not_found(client, plan_sample_date):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=404)
        with pytest.raises(Stundenplan24NotFoundError):
            await client.async_fetch_raw(plan_sample_date)


async def test_fetch_raw_server_error_becomes_connection_error(
    client, plan_sample_date
):
    with aioresponses() as mocked:
        mocked.get(_url_for(plan_sample_date), status=500)
        with pytest.raises(Stundenplan24ConnectionError):
            await client.async_fetch_raw(plan_sample_date)


async def test_verify_credentials_accepts_404_as_valid(client):
    with aioresponses() as mocked:
        mocked.get(_url_for(date.today()), status=404)
        # Must not raise - 404 only means "no plan today", not "wrong credentials".
        await client.async_verify_credentials()


async def test_verify_credentials_raises_on_auth_error(client):
    with aioresponses() as mocked:
        mocked.get(_url_for(date.today()), status=401)
        with pytest.raises(Stundenplan24AuthError):
            await client.async_verify_credentials()


async def test_probe_skips_404_and_finds_next_plan(client, plan_sample_bytes):
    start = date(2026, 8, 26)
    with aioresponses() as mocked:
        mocked.get(_url_for(start), status=404)
        mocked.get(_url_for(date(2026, 8, 27)), status=404)
        mocked.get(_url_for(date(2026, 8, 28)), status=200, body=plan_sample_bytes)

        plan = await client.async_probe(start, max_days=5)

    assert plan is not None
    assert plan.target_date == date(2026, 8, 28)


async def test_probe_returns_none_when_nothing_found(client):
    start = date(2026, 8, 26)
    with aioresponses() as mocked:
        for offset in range(3):
            mocked.get(_url_for(date(2026, 8, 26 + offset)), status=404)
        plan = await client.async_probe(start, max_days=3)
    assert plan is None


async def test_probe_aborts_immediately_on_auth_error(client):
    start = date(2026, 8, 26)
    with aioresponses() as mocked:
        mocked.get(_url_for(start), status=401)
        with pytest.raises(Stundenplan24AuthError):
            await client.async_probe(start, max_days=5)
