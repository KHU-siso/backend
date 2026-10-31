# =============================================================================
# 빈 시간 학습 알림
# -----------------------------------------------------------------------------
# 마이페이지에서 "빈 시간 학습 알림"을 켠 사용자에게, 오늘/내일 시간표(수업 + 일정 + 시험)의 빈 시간이
# 시작되기 10분 전에 "공부할 시간이에요" 메일을 보낸다. 그 과목에 올린 PDF가 있으면 기존 퀴즈 생성 로직
# (quiz_service.generate_quiz_questions)으로 만든 짧은 퀴즈 1~3개를 함께 넣고, 자료가 없으면 알림만 보낸다.
#
# 데이터 위치(전부 기존 저장소 재사용 — DB 스키마 변경 없음)
#   - 시간표: user_states('subjects') JSON 의 calendarEvents / exams / cancellations / subjects
#   - 켜기/끄기: user_states('profile') JSON 의 notifications.freeTime (기본 꺼짐)
#   - 중복 방지·횟수 제한: email_notification_logs (kind="free_time_study", assignment_id="YYYY-MM-DDTHH:MM")
#
# 중복 발송 방지(서버 2대 이상): deadline_scheduler 와 같은 방식. 발송 전에 (user, 슬롯, kind) 행을 먼저 INSERT
# (ON CONFLICT DO NOTHING)해서 성공한 쪽만 보낸다. 실패하면 행을 지워 다음 주기에 다시 시도한다.
# 하루 최대 횟수는 오늘(서울) 이 kind 의 로그 행 수로 센다. 동시에 두 서버가 마지막 한 자리를 노려도
# INSERT 뒤에 다시 세어 초과분은 되돌리므로 한도를 넘지 않는다.
# =============================================================================
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.database import SessionLocal
from app.models import Document, EmailNotificationLog, User, UserState
from app.services.email_service import email_configured, send_study_reminder_email

logger = logging.getLogger("app.free_time")

KIND = "free_time_study"
SEOUL = ZoneInfo("Asia/Seoul")
DAY_START = 8 * 60  # 08:00
DAY_END = 22 * 60  # 22:00
MIN_SLOT_MINUTES = 30  # 이보다 짧은 빈 시간은 알리지 않는다
EXAM_MINUTES = 60  # 프론트 시간표가 시험을 1시간 블록으로 그리는 것과 같다
MAX_QUIZ = 3


# ---------- 빈 시간 계산 (순수 함수) ----------

def _normalized(value) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).strip()).lower()


def _event_subject_id(event: dict, subjects: list[dict]) -> str | None:
    """프론트 eventSubject()와 같은 규칙: subjectId가 있으면 그것, 없으면 이름으로 찾는다. 개인 일정(personal)은 과목이 아니다."""
    if event.get("kind") == "personal":
        return None
    ids = {s.get("id") for s in subjects if isinstance(s, dict)}
    if event.get("subjectId"):
        return event["subjectId"] if event["subjectId"] in ids else None
    for s in subjects:
        if isinstance(s, dict) and _normalized(s.get("name")) == _normalized(event.get("name")):
            return s.get("id")
    return None


def _hour_to_min(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value * 60))


def busy_intervals(data: dict, day: date) -> list[tuple[int, int]]:
    """그날 시간표가 차 있는 구간(분 단위, 0~1440). 휴강된 수업은 제외한다."""
    subjects = data.get("subjects") if isinstance(data.get("subjects"), list) else []
    cancelled = {
        (c.get("subjectId"), c.get("date"))
        for c in (data.get("cancellations") or [])
        if isinstance(c, dict)
    }
    iso = day.isoformat()
    weekday = (day.weekday() + 1) % 7  # 프론트는 일요일=0
    out: list[tuple[int, int]] = []
    for event in data.get("calendarEvents") or []:
        if not isinstance(event, dict):
            continue
        if event.get("date"):
            if event["date"] != iso:
                continue
        elif event.get("day") != weekday:
            continue
        subject_id = _event_subject_id(event, subjects)
        if subject_id and (subject_id, iso) in cancelled:
            continue
        start, end = _hour_to_min(event.get("start")), _hour_to_min(event.get("end"))
        if start is not None and end is not None and end > start:
            out.append((max(0, start), min(1440, end)))
    for exam in data.get("exams") or []:
        if not isinstance(exam, dict) or exam.get("date") != iso or not exam.get("time"):
            continue
        try:
            hour, minute = (int(part) for part in str(exam["time"]).split(":"))
        except ValueError:
            continue
        start = hour * 60 + minute
        out.append((start, min(1440, start + EXAM_MINUTES)))
    return out


def free_slots(data: dict, day: date) -> list[tuple[int, int]]:
    """08:00~22:00 안에서 비어 있는 구간 중 30분 이상인 것 (분 단위 (시작, 끝) 목록)."""
    clipped = sorted(
        (max(DAY_START, s), min(DAY_END, e)) for s, e in busy_intervals(data, day) if e > DAY_START and s < DAY_END
    )
    slots: list[tuple[int, int]] = []
    cursor = DAY_START
    for start, end in clipped:
        if start > cursor:
            slots.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < DAY_END:
        slots.append((cursor, DAY_END))
    return [(s, e) for s, e in slots if e - s >= MIN_SLOT_MINUTES]


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ---------- 중복 방지 / 횟수 제한 ----------

class _LimitReached(Exception):
    """오늘 이 사용자의 발송 한도에 도달했다."""



def _today_count(db, user_id: int, now_seoul: datetime) -> int:
    midnight = now_seoul.replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(func.count()).select_from(EmailNotificationLog).where(
            EmailNotificationLog.user_id == user_id,
            EmailNotificationLog.kind == KIND,
            EmailNotificationLog.created_at >= midnight,
        )
    ).scalar_one()


def _claim(db, user_id: int, slot_key: str) -> bool:
    result = db.execute(
        pg_insert(EmailNotificationLog)
        .values(user_id=user_id, assignment_id=slot_key, kind=KIND)
        .on_conflict_do_nothing(constraint="uq_email_notification_logs_user_assignment_kind")
    )
    db.commit()
    return result.rowcount == 1


def _release(db, user_id: int, slot_key: str) -> None:
    db.execute(
        delete(EmailNotificationLog).where(
            EmailNotificationLog.user_id == user_id,
            EmailNotificationLog.assignment_id == slot_key,
            EmailNotificationLog.kind == KIND,
        )
    )
    db.commit()


# ---------- 퀴즈 (기존 퀴즈 생성 로직 재사용) ----------

def _pick_document(db, user_id: int, data: dict, today: date) -> tuple[Document, str] | None:
    """퀴즈를 만들 자료 하나: 가장 가까운 시험이 있는 과목의 최신 PDF, 없으면 가장 최근에 올린 PDF."""
    docs = db.query(Document).filter(Document.user_id == user_id, Document.subject_ref.isnot(None)).order_by(Document.created_at.desc()).all()
    if not docs:
        return None
    names = {s.get("id"): s.get("name", "") for s in data.get("subjects", []) if isinstance(s, dict)}
    upcoming = sorted(
        (e for e in data.get("exams", []) if isinstance(e, dict) and str(e.get("date", "")) >= today.isoformat() and e.get("subjectId") in names),
        key=lambda e: (e.get("date", ""), e.get("time") or ""),
    )
    for exam in upcoming:
        for doc in docs:
            if doc.subject_ref == exam["subjectId"]:
                return doc, names[doc.subject_ref]
    doc = next((d for d in docs if d.subject_ref in names), None)
    return (doc, names[doc.subject_ref]) if doc else None


def _make_quiz(doc: Document) -> list[dict]:
    """실패하거나 자료에서 문제를 못 만들면 빈 목록 (그러면 알림만 보낸다)."""
    try:
        from app.services.quiz_service import generate_quiz_questions

        raw = generate_quiz_questions(doc.id, "객관식", num_questions=MAX_QUIZ)
    except Exception:
        logger.exception("빈 시간 알림 퀴즈 생성 실패: document_id=%s", doc.id)
        return []
    quiz = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("question") or not item.get("correct_answer"):
            continue
        options = [str(o) for o in item["options"]] if isinstance(item.get("options"), list) else []
        quiz.append({"question": str(item["question"]), "options": options, "answer": str(item["correct_answer"]), "explanation": str(item.get("explanation") or "")})
    return quiz[:MAX_QUIZ]


# ---------- 실행 ----------

def _enabled_targets(db) -> list[tuple[int, str, str, dict]]:
    rows = (
        db.query(User, UserState)
        .join(UserState, (UserState.user_id == User.id) & (UserState.key == "subjects"))
        .all()
    )
    profiles = {
        state.user_id: state.data
        for state in db.query(UserState).filter(UserState.key == "profile").all()
        if isinstance(state.data, dict)
    }
    targets = []
    for user, state in rows:
        notifications = (profiles.get(user.id) or {}).get("notifications")
        if isinstance(notifications, dict) and notifications.get("freeTime") is True:  # 기본 꺼짐
            targets.append((user.id, user.email, user.nickname, state.data if isinstance(state.data, dict) else {}))
    return targets


def run_once(now: datetime | None = None) -> int:
    """한 번 훑어서 보낼 메일을 보낸다. 실제 발송 수를 돌려준다."""
    if not email_configured():
        logger.info("빈 시간 알림 건너뜀: EMAIL_ENABLED/SMTP_USER/SMTP_PASSWORD가 설정되지 않음")
        return 0
    now = now or datetime.now(timezone.utc)
    now_seoul = now.astimezone(SEOUL)
    today = now_seoul.date()
    lead = timedelta(minutes=settings.study_reminder_lead_minutes)
    limit = settings.study_reminder_max_per_day
    sent = 0
    with SessionLocal() as db:
        for user_id, email, nickname, data in _enabled_targets(db):
            try:
                for day in (today, today + timedelta(days=1)):
                    for start, end in free_slots(data, day):
                        slot_start = datetime(day.year, day.month, day.day, start // 60, start % 60, tzinfo=SEOUL)
                        if not (slot_start - lead <= now_seoul < slot_start):  # 시작 10분 전부터 시작 직전까지만
                            continue
                        if _today_count(db, user_id, now_seoul) >= limit:
                            raise _LimitReached
                        slot_key = f"{day.isoformat()}T{_hhmm(start)}"
                        if not _claim(db, user_id, slot_key):
                            continue  # 이미 보냈거나 다른 서버가 먼저 가져갔다
                        try:
                            if _today_count(db, user_id, now_seoul) > limit:  # 동시에 마지막 자리를 잡은 경우
                                _release(db, user_id, slot_key)
                                raise _LimitReached
                            picked = _pick_document(db, user_id, data, today)
                            quiz = _make_quiz(picked[0]) if picked else []
                            ok = send_study_reminder_email(
                                to_email=email,
                                user_name=nickname,
                                slot_text=f"{_hhmm(start)} ~ {_hhmm(end)}",
                                subject_name=picked[1] if picked and quiz else "",
                                quiz=quiz,
                            )
                        except _LimitReached:
                            raise
                        except Exception:
                            logger.exception("빈 시간 알림 처리 중 오류: user_id=%s, slot=%s", user_id, slot_key)
                            db.rollback()
                            _release(db, user_id, slot_key)
                            continue
                        if ok:
                            sent += 1
                        else:
                            _release(db, user_id, slot_key)
            except _LimitReached:
                continue  # 이 사용자는 오늘 한도 도달
            except Exception:
                logger.exception("빈 시간 알림 사용자 처리 오류: user_id=%s", user_id)
                db.rollback()
    if sent:
        logger.info("빈 시간 학습 알림 %d건 발송", sent)
    return sent
