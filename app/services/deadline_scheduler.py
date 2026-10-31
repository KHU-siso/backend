# =============================================================================
# 과제 마감 이메일 알림 스케줄러
# -----------------------------------------------------------------------------
# 일정 간격(SCHEDULER_INTERVAL_SECONDS)마다 "과제 마감 알림"을 켠 사용자의 과제 중
# 마감까지 24시간 이내이고 아직 메일을 보내지 않은 것에 메일을 보낸다.
#
# 서버가 두 대 이상 떠서 이 코드가 동시에 돌 수 있으므로 중복 발송은 DB로 막는다.
#   1) email_notification_logs 에 (user_id, assignment_id, kind) 행을 먼저 INSERT 한다.
#      (유니크 제약 + ON CONFLICT DO NOTHING → 동시에 시도해도 정확히 한 쪽만 1행을 넣는다.)
#   2) INSERT 에 성공한(rowcount == 1) 쪽만 메일을 보낸다.
#   3) 메일 발송이 실패하면 그 행을 지워서 다음 주기에 다시 시도한다.
# 과제 데이터는 과목 테이블이 아니라 프론트가 저장하는 user_states('subjects') JSON 안에 있다.
# =============================================================================
import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.database import SessionLocal
from app.models import EmailNotificationLog, User, UserState
from app.services.email_service import email_configured, send_assignment_deadline_email

logger = logging.getLogger("app.scheduler")

KIND_DUE_24H = "assignment_due_24h"
WINDOW = timedelta(hours=24)
SEOUL = ZoneInfo("Asia/Seoul")


def _deadline_at(task: dict) -> datetime | None:
    """프론트의 deadlineAt()과 같은 규칙: 날짜 + (시간 없으면 23:59:59) 를 서울 시간으로 해석한다."""
    try:
        day = datetime.strptime(task["date"], "%Y-%m-%d")
        time = task.get("time")
        if time:
            hour, minute = (int(part) for part in time.split(":"))
            return day.replace(hour=hour, minute=minute, tzinfo=SEOUL)
        return day.replace(hour=23, minute=59, second=59, tzinfo=SEOUL)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _remaining_text(deadline: datetime, now: datetime) -> str:
    """메일에 쓰는 남은 시간 문구. 알림 조건이 24시간 이내라 시간 단위로만 표현한다."""
    minutes = int((deadline - now).total_seconds() // 60)
    if minutes < 60:
        return "마감까지 1시간도 남지 않았어요"
    return f"마감까지 {-(-minutes // 60)}시간 남았어요"


def _claim(db, user_id: int, assignment_id: str) -> bool:
    """발송 기록을 먼저 INSERT 한다. 내가 넣는 데 성공했을 때만 True (= 내가 보낼 차례)."""
    result = db.execute(
        pg_insert(EmailNotificationLog)
        .values(user_id=user_id, assignment_id=assignment_id, kind=KIND_DUE_24H)
        .on_conflict_do_nothing(constraint="uq_email_notification_logs_user_assignment_kind")
    )
    db.commit()
    return result.rowcount == 1


def _release(db, user_id: int, assignment_id: str) -> None:
    """발송에 실패했을 때 기록을 되돌려 다음 주기에 다시 시도되게 한다."""
    db.execute(
        delete(EmailNotificationLog).where(
            EmailNotificationLog.user_id == user_id,
            EmailNotificationLog.assignment_id == assignment_id,
            EmailNotificationLog.kind == KIND_DUE_24H,
        )
    )
    db.commit()


def run_once(now: datetime | None = None) -> int:
    """한 번 훑어서 보낼 메일을 보낸다. 실제로 발송한 메일 수를 돌려준다."""
    if not email_configured():
        logger.info("과제 마감 알림 건너뜀: EMAIL_ENABLED/SMTP_USER/SMTP_PASSWORD가 설정되지 않음")
        return 0
    now = now or datetime.now(timezone.utc)
    sent = 0
    with SessionLocal() as db:
        rows = (
            db.query(User, UserState)
            .join(UserState, (UserState.user_id == User.id) & (UserState.key == "subjects"))
            .filter(User.deadline_email_enabled.is_(True))
            .all()
        )
        # 커밋하면 ORM 객체가 만료되므로 필요한 값은 미리 꺼내 둔다.
        targets = [(user.id, user.email, user.nickname, state.data if isinstance(state.data, dict) else {}) for user, state in rows]
        for user_id, email, nickname, data in targets:
            names = {s.get("id"): s.get("name", "") for s in data.get("subjects", []) if isinstance(s, dict)}
            for task in data.get("assignments", []):
                if not isinstance(task, dict) or task.get("completed") or not task.get("id"):
                    continue
                deadline = _deadline_at(task)
                if deadline is None or not (now < deadline <= now + WINDOW):
                    continue
                assignment_id = str(task["id"])[:64]
                try:
                    if not _claim(db, user_id, assignment_id):
                        continue  # 이미 보냈거나, 다른 서버가 먼저 가져갔다
                    ok = send_assignment_deadline_email(
                        to_email=email,
                        user_name=nickname,
                        subject_name=names.get(task.get("subjectId"), "과목"),
                        assignment_title=str(task.get("title", "과제")),
                        deadline_text=deadline.astimezone(SEOUL).strftime("%Y-%m-%d %H:%M") if task.get("time") else deadline.astimezone(SEOUL).strftime("%Y-%m-%d") + " 하루 종일",
                        remaining_text=_remaining_text(deadline, now),
                    )
                    if ok:
                        sent += 1
                    else:
                        _release(db, user_id, assignment_id)
                except Exception:
                    logger.exception("과제 마감 알림 처리 중 오류: user_id=%s, assignment_id=%s", user_id, assignment_id)
                    db.rollback()
                    try:
                        _release(db, user_id, assignment_id)
                    except Exception:
                        logger.exception("발송 기록 되돌리기 실패: user_id=%s, assignment_id=%s", user_id, assignment_id)
                        db.rollback()
    if sent:
        logger.info("과제 마감 알림 %d건 발송", sent)
    return sent


class DeadlineScheduler:
    """백그라운드 스레드로 run_once()를 주기적으로 실행한다. 시작하자마자 한 번 실행하고 이후 간격마다 반복."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.scheduler_enabled:
            logger.info("스케줄러 꺼짐: SCHEDULER_ENABLED=false")
            return
        interval = max(5, settings.scheduler_interval_seconds)
        self._thread = threading.Thread(target=self._loop, args=(interval,), name="deadline-scheduler", daemon=True)
        self._thread.start()
        logger.info("과제 마감 알림 스케줄러 시작: %d초 간격", interval)

    def _loop(self, interval: int) -> None:
        while True:
            try:
                run_once()
            except Exception:
                logger.exception("과제 마감 알림 스케줄러 오류")
            if self._stop.wait(interval):
                return

    def stop(self) -> None:
        self._stop.set()
