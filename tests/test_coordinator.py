"""Tests für die Filter- und Auswertungslogik in custom_components.stundenplan.coordinator.

Es wird bewusst kein vollständiger, laufender Home-Assistant-Kern
instanziiert: Die hier getesteten Methoden sind reine Business-Logik
(Filterung, Ermittlung der ersten Stunde, Serialisierung) und werden direkt
bzw. über ein minimal konstruiertes Coordinator-Objekt aufgerufen. Tests, die
eine echte laufende Home-Assistant-Instanz benötigen (z.B. der komplette
Refresh-Zyklus inkl. Kalenderabfrage), sind bewusst nicht Teil dieser
leichtgewichtigen Suite - siehe CONTRIBUTING.md.
"""
from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from custom_components.stundenplan.api import Lesson
from custom_components.stundenplan.coordinator import Stundenplan24Coordinator


def _lesson(
    stunde: int,
    fach: str,
    *,
    kurs: str | None = None,
    hinweis: str = "",
    entfaellt: bool = False,
) -> Lesson:
    fach_wert = "---" if entfaellt else fach
    return Lesson(
        stunde=stunde,
        beginn=f"{7 + stunde:02d}:00",
        ende=f"{7 + stunde:02d}:45",
        fach=fach_wert,
        lehrer="Le",
        raum="1.01",
        hinweis=hinweis,
        fach_geaendert=entfaellt,
        lehrer_geaendert=entfaellt,
        raum_geaendert=entfaellt,
        kurs=kurs,
    )


def _coordinator_stub(
    ignorierte_faecher: set[str] | None = None,
    ignorierte_kurse: set[str] | None = None,
) -> Stundenplan24Coordinator:
    """Erzeugt ein Coordinator-Objekt ohne __init__ (kein hass/entry nötig).

    Nur für Tests der reinen Filterlogik gedacht - alle anderen Attribute
    bleiben bewusst ungesetzt.
    """
    coordinator = object.__new__(Stundenplan24Coordinator)
    coordinator._ignorierte_faecher = ignorierte_faecher or set()
    coordinator._ignorierte_kurse = ignorierte_kurse or set()
    return coordinator


class TestWirdIgnoriert:
    def test_reguläre_stunde_ohne_filter_wird_nicht_ignoriert(self):
        coordinator = _coordinator_stub()
        assert coordinator._wird_ignoriert(_lesson(1, "MA")) is False

    def test_ignoriertes_fach_wird_gefiltert(self):
        coordinator = _coordinator_stub(ignorierte_faecher={"MA"})
        assert coordinator._wird_ignoriert(_lesson(1, "MA")) is True

    def test_nicht_ignoriertes_fach_bleibt(self):
        coordinator = _coordinator_stub(ignorierte_faecher={"MA"})
        assert coordinator._wird_ignoriert(_lesson(1, "DE")) is False

    def test_ignorierte_kursgruppe_wird_ueber_ku2_gefiltert(self):
        coordinator = _coordinator_stub(ignorierte_kurse={"WPK2"})
        stunde_a = _lesson(3, "WPK1", kurs="WPK1")
        stunde_b = _lesson(3, "WPK2", kurs="WPK2")
        assert coordinator._wird_ignoriert(stunde_a) is False
        assert coordinator._wird_ignoriert(stunde_b) is True

    def test_ignoriertes_fach_wird_auch_bei_ausfall_ueber_hinweistext_erkannt(self):
        coordinator = _coordinator_stub(ignorierte_faecher={"MA"})
        ausfall = _lesson(1, "MA", entfaellt=True, hinweis="MA Herr Mueller fällt aus")
        assert coordinator._wird_ignoriert(ausfall) is True

    def test_ausfall_ohne_erkennbares_kuerzel_wird_nicht_faelschlich_gefiltert(self):
        coordinator = _coordinator_stub(ignorierte_faecher={"MA"})
        ausfall = _lesson(1, "DE", entfaellt=True, hinweis="")
        assert coordinator._wird_ignoriert(ausfall) is False

    def test_ausfall_mit_ku2_wird_ueber_kurs_ignoriert_liste_gefiltert(self):
        coordinator = _coordinator_stub(ignorierte_kurse={"WPK1"})
        ausfall = _lesson(
            3, "WPK1", kurs="WPK1", entfaellt=True, hinweis="verlegt; WPK1 fällt aus"
        )
        assert coordinator._wird_ignoriert(ausfall) is True


class TestErmittleErsteStunde:
    def test_erste_stunde_ohne_ausfaelle(self):
        stunden = [_lesson(2, "DE"), _lesson(1, "MA")]
        ergebnis = Stundenplan24Coordinator._ermittle_erste_stunde(stunden)
        assert ergebnis is not None
        assert ergebnis["stunde"] == 1
        assert ergebnis["faecher"][0]["fach"] == "MA"

    def test_ausgefallene_erste_stunde_wird_uebersprungen(self):
        stunden = [
            _lesson(1, "MA", entfaellt=True, hinweis="MA fällt aus"),
            _lesson(2, "DE"),
        ]
        ergebnis = Stundenplan24Coordinator._ermittle_erste_stunde(stunden)
        assert ergebnis is not None
        assert ergebnis["stunde"] == 2

    def test_parallele_gruppen_in_erster_stunde_werden_alle_gelistet(self):
        stunden = [
            _lesson(1, "WPK1", kurs="WPK1"),
            _lesson(1, "WPK2", kurs="WPK2"),
        ]
        ergebnis = Stundenplan24Coordinator._ermittle_erste_stunde(stunden)
        assert ergebnis is not None
        assert {f["fach"] for f in ergebnis["faecher"]} == {"WPK1", "WPK2"}

    def test_keine_stunden_ergibt_none(self):
        assert Stundenplan24Coordinator._ermittle_erste_stunde([]) is None

    def test_nur_ausfaelle_ergibt_none(self):
        stunden = [_lesson(1, "MA", entfaellt=True, hinweis="MA fällt aus")]
        assert Stundenplan24Coordinator._ermittle_erste_stunde(stunden) is None


class TestLessonZuDict:
    def test_enthaelt_alle_erwarteten_felder(self):
        lesson = _lesson(1, "MA", kurs="MA1", hinweis="Hinweis")
        ergebnis = Stundenplan24Coordinator._lesson_zu_dict(lesson)
        assert ergebnis == {
            "stunde": 1,
            "beginn": "08:00",
            "ende": "08:45",
            "fach": "MA",
            "kurs": "MA1",
            "lehrer": "Le",
            "raum": "1.01",
            "hinweis": "Hinweis",
            "status": "regulaer",
            "faellt_aus": False,
        }


class TestZielDatum:
    @freeze_time("2026-08-27 18:30:00")
    def test_ziel_datum_ist_immer_der_naechste_kalendertag(self):
        assert Stundenplan24Coordinator._ziel_datum() == date(2026, 8, 28)

    @freeze_time("2026-08-28 23:59:59")
    def test_ziel_datum_funktioniert_ueber_monatsgrenzen(self):
        assert Stundenplan24Coordinator._ziel_datum() == date(2026, 8, 29)
