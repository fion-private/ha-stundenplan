"""Tests für custom_components.stundenplan.api - reines XML-Parsing.

Diese Tests benötigen keine Home-Assistant-Laufzeitumgebung und keinen
Netzwerkzugriff; sie arbeiten ausschließlich auf der mitgelieferten
Beispieldatei tests/fixtures/plan_sample.xml.
"""
from __future__ import annotations

from datetime import date

import pytest

from custom_components.stundenplan.api import Lesson, parse_plan_xml


def test_parse_plan_xml_findet_alle_klassen(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)

    assert set(plan.klassen.keys()) == {"5a", "6b"}
    assert plan.ziel_datum == plan_sample_date


def test_parse_plan_xml_strippt_bom(plan_sample_bytes, plan_sample_date):
    # Die Fixture beginnt bewusst mit einem UTF-8-BOM, wie es reale
    # Stundenplan24-Exporte liefern. Das Parsen darf daran nicht scheitern.
    assert plan_sample_bytes.startswith(b"\xef\xbb\xbf")
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    assert plan.klassen  # kein Fehler, Klassen wurden trotz BOM gefunden


def test_parse_freie_tage(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)

    assert plan.freie_tage == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 10, 12),
    ]


def test_faecherkatalog_enthaelt_unterricht_und_tagesplan_faecher(
    plan_sample_bytes, plan_sample_date
):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    klasse = plan.klassen["5a"]

    # Aus <Unterricht>: MA, DE, WPK. Aus dem Tagesplan zusätzlich die
    # konkreten Gruppen-Kürzel WPK1/WPK2 (die im Katalog nicht als
    # eigenständiges Fach auftauchen, aber im Plan als <Fa> verwendet werden).
    assert {"MA", "DE", "WPK", "WPK1", "WPK2"} <= klasse.faecher
    # Der Ausfall-Marker "---" darf niemals als Fach gelten.
    assert "---" not in klasse.faecher


def test_kurskatalog_wird_geparst(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    klasse = plan.klassen["5a"]

    assert klasse.kurse == {"WPK1", "WPK2"}


def test_klasse_ohne_kurse_hat_leeren_kurskatalog(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    klasse = plan.klassen["6b"]

    assert klasse.kurse == set()
    assert klasse.faecher == {"EN"}


def test_anzahl_stunden_pro_klasse(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)

    assert len(plan.klassen["5a"].lessons) == 5  # inkl. der 2 parallelen WPK-Stunden
    assert len(plan.klassen["6b"].lessons) == 1


@pytest.mark.parametrize(
    ("stunde", "erwartetes_fach", "erwarteter_status"),
    [
        (1, "MA", "regulaer"),
        (2, "DE", "geaendert"),
        (4, "---", "entfaellt"),
    ],
)
def test_lesson_status(
    plan_sample_bytes, plan_sample_date, stunde, erwartetes_fach, erwarteter_status
):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    treffer = [
        lesson
        for lesson in plan.klassen["5a"].lessons
        if lesson.stunde == stunde and lesson.fach == erwartetes_fach
    ]
    assert len(treffer) == 1
    assert treffer[0].status == erwarteter_status


def test_parallele_kursgruppen_haben_unterschiedliches_ku2(
    plan_sample_bytes, plan_sample_date
):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    dritte_stunde = [l for l in plan.klassen["5a"].lessons if l.stunde == 3]

    assert len(dritte_stunde) == 2
    kurse = {l.kurs for l in dritte_stunde}
    assert kurse == {"WPK1", "WPK2"}


def test_hinweis_kandidat_bei_ku2_bevorzugt_ku2():
    lesson = Lesson(
        stunde=3,
        beginn="09:50",
        ende="10:35",
        fach="---",
        lehrer="",
        raum="",
        hinweis="WPK1 fällt aus",
        fach_geaendert=True,
        lehrer_geaendert=True,
        raum_geaendert=True,
        kurs="WPK1",
    )
    assert lesson.hinweis_kandidat == "WPK1"


@pytest.mark.parametrize(
    ("hinweis", "erwartet"),
    [
        ("MA Herr Mueller fällt aus", "MA"),
        ("für DE Herr Sonne", "DE"),
        ("verlegt von St.1; GE Frau Burger fällt aus", "GE"),
        ("KU Herr Mai fällt aus", "KU"),
        ("", None),
    ],
)
def test_hinweis_kandidat_heuristik_ohne_ku2(hinweis, erwartet):
    lesson = Lesson(
        stunde=1,
        beginn="08:00",
        ende="08:45",
        fach="---",
        lehrer="",
        raum="",
        hinweis=hinweis,
        fach_geaendert=True,
        lehrer_geaendert=True,
        raum_geaendert=True,
        kurs=None,
    )
    assert lesson.hinweis_kandidat == erwartet


def test_hinweis_kandidat_bei_regulaerer_stunde_ist_none():
    lesson = Lesson(
        stunde=1,
        beginn="08:00",
        ende="08:45",
        fach="MA",
        lehrer="Mu",
        raum="101",
        hinweis="",
        fach_geaendert=False,
        lehrer_geaendert=False,
        raum_geaendert=False,
        kurs=None,
    )
    assert lesson.hinweis_kandidat is None
