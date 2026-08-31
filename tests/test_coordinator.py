"""Tests for the filtering/evaluation logic in custom_components.stundenplan.coordinator.

No full, running Home Assistant core is instantiated on purpose: the
methods tested here are pure business logic (filtering, first/last lesson
determination, serialization) and are called directly, or via a minimally
constructed coordinator object. Tests that need a real running Home
Assistant instance (e.g. the full refresh cycle including the calendar
lookup) are intentionally not part of this lightweight suite - see
CONTRIBUTING.md.
"""

from __future__ import annotations

from custom_components.stundenplan.api import Lesson
from custom_components.stundenplan.coordinator import Stundenplan24Coordinator


def _lesson(
    period: int,
    subject: str,
    *,
    course: str | None = None,
    note: str = "",
    cancelled: bool = False,
) -> Lesson:
    subject_value = "---" if cancelled else subject
    return Lesson(
        period=period,
        start=f"{7 + period:02d}:00",
        end=f"{7 + period:02d}:45",
        subject=subject_value,
        teacher="Teacher",
        room="1.01",
        note=note,
        subject_changed=cancelled,
        teacher_changed=cancelled,
        room_changed=cancelled,
        course=course,
    )


def _coordinator_stub(
    ignored_subjects: set[str] | None = None,
    ignored_courses: set[str] | None = None,
) -> Stundenplan24Coordinator:
    """Creates a coordinator object without __init__ (no hass/entry needed).

    Only intended for testing the pure filtering logic - all other
    attributes are deliberately left unset.
    """
    coordinator = object.__new__(Stundenplan24Coordinator)
    coordinator._ignored_subjects = ignored_subjects or set()
    coordinator._ignored_courses = ignored_courses or set()
    return coordinator


class TestIsIgnored:
    def test_regular_lesson_without_filters_is_not_ignored(self):
        coordinator = _coordinator_stub()
        assert coordinator._is_ignored(_lesson(1, "MA")) is False

    def test_ignored_subject_is_filtered(self):
        coordinator = _coordinator_stub(ignored_subjects={"MA"})
        assert coordinator._is_ignored(_lesson(1, "MA")) is True

    def test_non_ignored_subject_stays(self):
        coordinator = _coordinator_stub(ignored_subjects={"MA"})
        assert coordinator._is_ignored(_lesson(1, "DE")) is False

    def test_ignored_course_group_is_filtered_via_course_code(self):
        coordinator = _coordinator_stub(ignored_courses={"WPK2"})
        lesson_a = _lesson(3, "WPK1", course="WPK1")
        lesson_b = _lesson(3, "WPK2", course="WPK2")
        assert coordinator._is_ignored(lesson_a) is False
        assert coordinator._is_ignored(lesson_b) is True

    def test_ignored_subject_is_recognized_via_note_even_when_cancelled(self):
        coordinator = _coordinator_stub(ignored_subjects={"MA"})
        cancelled = _lesson(1, "MA", cancelled=True, note="MA Mr Miller cancelled")
        assert coordinator._is_ignored(cancelled) is True

    def test_cancelled_lesson_without_recognizable_code_is_not_falsely_filtered(self):
        coordinator = _coordinator_stub(ignored_subjects={"MA"})
        cancelled = _lesson(1, "DE", cancelled=True, note="")
        assert coordinator._is_ignored(cancelled) is False

    def test_cancelled_lesson_with_course_code_is_filtered_via_ignored_courses(self):
        coordinator = _coordinator_stub(ignored_courses={"WPK1"})
        cancelled = _lesson(
            3, "WPK1", course="WPK1", cancelled=True, note="moved; WPK1 cancelled"
        )
        assert coordinator._is_ignored(cancelled) is True


class TestDetermineFirstLesson:
    def test_first_lesson_without_cancellations(self):
        lessons = [_lesson(2, "DE"), _lesson(1, "MA")]
        result = Stundenplan24Coordinator._determine_first_lesson(lessons)
        assert result is not None
        assert result["period"] == 1
        assert result["subjects"][0]["subject"] == "MA"

    def test_cancelled_first_lesson_is_skipped(self):
        lessons = [
            _lesson(1, "MA", cancelled=True, note="MA cancelled"),
            _lesson(2, "DE"),
        ]
        result = Stundenplan24Coordinator._determine_first_lesson(lessons)
        assert result is not None
        assert result["period"] == 2

    def test_parallel_groups_in_first_period_are_all_listed(self):
        lessons = [_lesson(1, "WPK1", course="WPK1"), _lesson(1, "WPK2", course="WPK2")]
        result = Stundenplan24Coordinator._determine_first_lesson(lessons)
        assert result is not None
        assert {s["subject"] for s in result["subjects"]} == {"WPK1", "WPK2"}

    def test_no_lessons_returns_none(self):
        assert Stundenplan24Coordinator._determine_first_lesson([]) is None

    def test_only_cancellations_returns_none(self):
        lessons = [_lesson(1, "MA", cancelled=True, note="MA cancelled")]
        assert Stundenplan24Coordinator._determine_first_lesson(lessons) is None


class TestDetermineLastLesson:
    def test_last_lesson_without_cancellations(self):
        lessons = [_lesson(1, "MA"), _lesson(3, "EN"), _lesson(2, "DE")]
        result = Stundenplan24Coordinator._determine_last_lesson(lessons)
        assert result is not None
        assert result["period"] == 3
        assert result["subjects"][0]["subject"] == "EN"

    def test_cancelled_last_lesson_falls_back_to_the_previous_period(self):
        lessons = [
            _lesson(1, "MA"),
            _lesson(2, "DE"),
            _lesson(3, "MA", cancelled=True, note="MA cancelled"),
        ]
        result = Stundenplan24Coordinator._determine_last_lesson(lessons)
        assert result is not None
        assert result["period"] == 2

    def test_parallel_groups_in_last_period_are_all_listed(self):
        lessons = [
            _lesson(1, "MA"),
            _lesson(3, "WPK1", course="WPK1"),
            _lesson(3, "WPK2", course="WPK2"),
        ]
        result = Stundenplan24Coordinator._determine_last_lesson(lessons)
        assert result is not None
        assert {s["subject"] for s in result["subjects"]} == {"WPK1", "WPK2"}

    def test_no_lessons_returns_none(self):
        assert Stundenplan24Coordinator._determine_last_lesson([]) is None

    def test_only_cancellations_returns_none(self):
        lessons = [_lesson(1, "MA", cancelled=True, note="MA cancelled")]
        assert Stundenplan24Coordinator._determine_last_lesson(lessons) is None


class TestLessonToDict:
    def test_contains_all_expected_fields(self):
        lesson = _lesson(1, "MA", course="MA1", note="Note")
        result = Stundenplan24Coordinator._lesson_to_dict(lesson)
        assert result == {
            "period": 1,
            "start": "08:00",
            "end": "08:45",
            "subject": "MA",
            "course": "MA1",
            "teacher": "Teacher",
            "room": "1.01",
            "note": "Note",
            "status": "regular",
            "cancelled": False,
        }
