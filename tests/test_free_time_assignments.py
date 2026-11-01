# 빈 시간 학습 알림 + 과제 배정 테스트 (DB·SMTP 없이 mock). 실행: python -m unittest tests.test_free_time_assignments
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

from app.services import free_time_scheduler as fts
from app.services.deadline_scheduler import _deadline_at
from app.services.email_templates import study_reminder_email_html

SEOUL = fts.SEOUL
NOW1 = datetime(2026, 11, 2, 13, 55, tzinfo=SEOUL)  # 14:00 슬롯 10분 전 창 안
NOW2 = datetime(2026, 11, 2, 15, 55, tzinfo=SEOUL)  # 16:00 슬롯 10분 전 창 안
SLOTS = [(14 * 60, 15 * 60 + 30), (16 * 60, 17 * 60)]


def task(id, title, date, time="", completed=False):
    return {"id": id, "subjectId": "s1", "title": title, "date": date, "time": time, "completed": completed}


def data_with(*tasks):
    return {"subjects": [{"id": "s1", "name": "인지심리학"}], "assignments": list(tasks), "calendarEvents": [], "exams": []}


class RunOnceHarness:
    """run_once()를 DB 없이 두 번(두 슬롯) 돌려 메일 인자를 모은다."""

    def __init__(self, data):
        self.data = data
        self.used: set[str] = set()
        self.sent: list[dict] = []

    def _claim(self, db, user_id, key, kind=fts.KIND):
        if kind == fts.KIND_TASK:
            self.used.add(key)
        return True

    def run(self, now):
        @contextmanager
        def fake_session():
            yield object()

        def fake_send(**kwargs):
            self.sent.append(kwargs)
            return True

        with patch.object(fts, "email_configured", return_value=True), \
             patch.object(fts, "SessionLocal", fake_session), \
             patch.object(fts, "_enabled_targets", return_value=[(1, "a@b.c", "민지", self.data)]), \
             patch.object(fts, "free_slots", return_value=SLOTS), \
             patch.object(fts, "_today_count", return_value=0), \
             patch.object(fts, "_claim", self._claim), \
             patch.object(fts, "_release"), \
             patch.object(fts, "_used_task_ids", lambda db, uid, day: set(self.used)), \
             patch.object(fts, "_pick_document", return_value=None), \
             patch.object(fts, "send_study_reminder_email", fake_send):
            return fts.run_once(now)


class FreeTimeAssignmentTest(unittest.TestCase):
    def test_closer_deadline_assigned_first(self):
        far, near = task("far", "먼 과제", "2026-11-09"), task("near", "가까운 과제", "2026-11-04")
        h = RunOnceHarness(data_with(far, near))  # 입력 순서와 상관없이 마감순
        h.run(NOW1)
        h.run(NOW2)
        self.assertEqual([m["assignment"]["title"] for m in h.sent], ["가까운 과제", "먼 과제"])
        self.assertEqual(h.sent[0]["assignment"]["remaining_text"], "2일 남음")

    def test_fewer_tasks_than_slots_reuses_closest(self):
        h = RunOnceHarness(data_with(task("only", "하나뿐", "2026-11-05")))
        h.run(NOW1)
        h.run(NOW2)
        self.assertEqual([m["assignment"]["title"] for m in h.sent], ["하나뿐", "하나뿐"])

    def test_done_and_overdue_tasks_excluded(self):
        h = RunOnceHarness(data_with(task("d", "끝남", "2026-11-05", completed=True), task("o", "지남", "2026-11-01")))
        h.run(NOW1)
        self.assertIsNone(h.sent[0]["assignment"])

    def test_no_assignments_sends_existing_mail(self):
        h = RunOnceHarness(data_with())
        self.assertEqual(h.run(NOW1), 1)
        self.assertIsNone(h.sent[0]["assignment"])
        self.assertEqual(h.sent[0]["quiz"], [])
        html = study_reminder_email_html("민지", "14:00 ~ 15:30", "", [], None)
        self.assertIn("공부할 시간이에요", html)
        self.assertIn("빈 시간이 곧 시작돼요", html)

    def test_urgent_flag_and_remaining_text(self):
        info = lambda t: fts.assignment_info(t, _deadline_at(t), {"s1": "인지심리학"}, NOW1)
        today = info(task("t", "오늘", "2026-11-02", "23:00"))
        tomorrow_morning = info(task("m", "내일 아침", "2026-11-03", "09:00"))  # 19시간 뒤 → 급함
        later = info(task("l", "나중", "2026-11-05", "12:00"))
        self.assertTrue(today["urgent"])
        self.assertEqual(today["remaining_text"], "오늘 마감")
        self.assertTrue(tomorrow_morning["urgent"])
        self.assertFalse(later["urgent"])
        self.assertEqual(later["remaining_text"], "3일 남음")

    def test_email_html_shows_task_then_quiz(self):
        quiz = [{"question": "Q?", "options": ["a", "b"], "answer": "a", "explanation": ""}]
        info = {"title": "보고서", "subject_name": "인지심리학", "deadline_text": "2026-11-05 12:00", "remaining_text": "3일 남음", "urgent": False}
        html = study_reminder_email_html("민지", "14:00 ~ 15:30", "인지심리학", quiz, info)
        self.assertIn("지금 비는 시간(14:00 ~ 15:30)에 이 과제를 해보세요", html)
        self.assertLess(html.index("보고서"), html.index("Q1."))
        self.assertIn("3일 남음", html)


if __name__ == "__main__":
    unittest.main()
