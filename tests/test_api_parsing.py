"""Tests for custom_components.stundenplan.api - pure XML parsing.

These tests require no Home Assistant runtime and no network access; they
work exclusively against the bundled sample file
tests/fixtures/plan_sample.xml.
"""
from __future__ import annotations

from datetime import date

import pytest

from custom_components.stundenplan.api import Lesson, parse_plan_xml


def test_parse_plan_xml_finds_all_classes(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)

    assert set(plan.classes.keys()) == {"5a", "6b"}
    assert plan.target_date == plan_sample_date


def test_parse_plan_xml_strips_bom(plan_sample_bytes, plan_sample_date):
    # The fixture deliberately starts with a UTF-8 BOM, as real
    # Stundenplan24 exports do. Parsing must not fail because of it.
    assert plan_sample_bytes.startswith(b"\xef\xbb\xbf")
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    assert plan.classes  # no error, classes were found despite the BOM


def test_parse_free_days(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)

    assert plan.free_days == [
        date(2026, 6, 1),
        date(2026, 6, 2),
        date(2026, 10, 12),
    ]


def test_subject_catalog_includes_schedule_and_syllabus_subjects(
    plan_sample_bytes, plan_sample_date
):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    class_data = plan.classes["5a"]

    # From <Unterricht>: MA, DE, WPK. From the day plan itself, additionally
    # the concrete group codes WPK1/WPK2 (which don't appear as a standalone
    # subject in the catalog, but are used as <Fa> in the plan).
    assert {"MA", "DE", "WPK", "WPK1", "WPK2"} <= class_data.subjects
    # The cancellation marker "---" must never count as a subject.
    assert "---" not in class_data.subjects


def test_course_catalog_is_parsed(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    class_data = plan.classes["5a"]

    assert class_data.courses == {"WPK1", "WPK2"}


def test_class_without_courses_has_empty_course_catalog(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    class_data = plan.classes["6b"]

    assert class_data.courses == set()
    assert class_data.subjects == {"EN"}


def test_lesson_count_per_class(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)

    assert len(plan.classes["5a"].lessons) == 5  # including the 2 parallel WPK lessons
    assert len(plan.classes["6b"].lessons) == 1


@pytest.mark.parametrize(
    ("period", "expected_subject", "expected_status"),
    [
        (1, "MA", "regular"),
        (2, "DE", "changed"),
        (4, "---", "cancelled"),
    ],
)
def test_lesson_status(
    plan_sample_bytes, plan_sample_date, period, expected_subject, expected_status
):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    matches = [
        lesson
        for lesson in plan.classes["5a"].lessons
        if lesson.period == period and lesson.subject == expected_subject
    ]
    assert len(matches) == 1
    assert matches[0].status == expected_status


def test_parallel_course_groups_have_different_course_codes(plan_sample_bytes, plan_sample_date):
    plan = parse_plan_xml(plan_sample_bytes, plan_sample_date)
    third_period = [lesson for lesson in plan.classes["5a"].lessons if lesson.period == 3]

    assert len(third_period) == 2
    courses = {lesson.course for lesson in third_period}
    assert courses == {"WPK1", "WPK2"}


def test_note_candidate_prefers_course_code():
    lesson = Lesson(
        period=3,
        start="09:50",
        end="10:35",
        subject="---",
        teacher="",
        room="",
        note="WPK1 cancelled",
        subject_changed=True,
        teacher_changed=True,
        room_changed=True,
        course="WPK1",
    )
    assert lesson.note_candidate == "WPK1"


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("MA Mr Miller cancelled", "MA"),
        ("für DE Mr Sun", "DE"),
        ("moved from period 1; GE Ms Bird cancelled", "GE"),
        ("KU Mr May cancelled", "KU"),
        ("", None),
    ],
)
def test_note_candidate_heuristic_without_course_code(note, expected):
    lesson = Lesson(
        period=1,
        start="08:00",
        end="08:45",
        subject="---",
        teacher="",
        room="",
        note=note,
        subject_changed=True,
        teacher_changed=True,
        room_changed=True,
        course=None,
    )
    assert lesson.note_candidate == expected


def test_note_candidate_is_none_for_a_regular_lesson():
    lesson = Lesson(
        period=1,
        start="08:00",
        end="08:45",
        subject="MA",
        teacher="Miller",
        room="101",
        note="",
        subject_changed=False,
        teacher_changed=False,
        room_changed=False,
        course=None,
    )
    assert lesson.note_candidate is None
