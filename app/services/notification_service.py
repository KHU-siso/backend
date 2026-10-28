# =============================================================================
# 이 파일의 역할 (services/notification_service.py)
# -----------------------------------------------------------------------------
# "복습할 시간이에요" 알림을 실제로 만드는 로직을 담당하는 파일입니다.
# services/priority_service.py의 find_free_time_slots로 빈 시간을 찾고, 그 시간을
# notify_at으로 삼아 Notification 행을 하나 저장합니다.
# =============================================================================

# 파이썬 표준 라이브러리 — 날짜/시간 계산, 로깅, 백그라운드 스레드에 사용
import logging
import threading
from datetime import date, datetime, timedelta

# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/models.py: 알림/과목 ORM 모델
from app.database import SessionLocal
from app.models import Notification, Subject, User
# services/email_service.py: 복습 알림 메일 발송
from app.services.email_service import send_review_email
# services/priority_service.py: 빈 시간 계산 함수 재사용
from app.services.priority_service import find_free_time_slots

logger = logging.getLogger("app.notifications")


# _send_review_email_for: 알림 한 건에 대한 복습 메일을 (백그라운드 스레드에서) 보내는 함수.
# 요청의 DB 세션은 요청이 끝나면 닫히므로 여기서는 새 세션을 열어 쓴다.
# 중복 방지: email_sent=False인 행만 "UPDATE ... SET email_sent=True"로 선점(rowcount==1)한 쪽만
# 발송한다. 발송이 실패하면 선점을 되돌려 나중에 다시 시도할 수 있게 한다.
# 어떤 예외도 밖으로 내보내지 않는다 — 메일 문제가 알림 저장/API 응답에 영향을 주면 안 된다.
def _send_review_email_for(notification_id: int) -> None:
    try:
        with SessionLocal() as db:
            claimed = (
                db.query(Notification)
                .filter(Notification.id == notification_id, Notification.email_sent.is_(False))
                .update({Notification.email_sent: True}, synchronize_session=False)
            )
            db.commit()
            if claimed != 1:
                return

            notification = db.get(Notification, notification_id)
            user = db.get(User, notification.user_id) if notification else None
            subject = db.get(Subject, notification.related_id) if notification and notification.related_id else None
            if notification is None or user is None:
                return

            sent = send_review_email(
                to_email=user.email,
                user_name=user.nickname,
                subject_name=subject.name if subject else "",
                message=notification.message,
            )
            if not sent:
                notification.email_sent = False
                db.commit()
    except Exception:
        logger.exception("복습 알림 메일 처리 중 오류: notification_id=%s", notification_id)


# create_review_notification: 특정 과목에 대한 "복습 알림"을 만드는 함수.
# 무슨 기능을 하나:
#   1) 이 유저가 그 과목에 대해 아직 체크(is_completed=True)하지 않은 복습 알림을 이미 갖고
#      있다면, 새로 만들지 않고 그 기존 알림을 그대로 반환한다 — "체크할 때까지 유지된다"는
#      요구사항을, 매번 새로 만들지 않는 방식으로 구현했다.
#   2) find_free_time_slots로 오늘의 빈 시간을 찾고, 없으면 내일의 빈 시간을 찾는다
#      (오늘 저녁이든 내일 오전/오후든, 먼저 찾아지는 빈 시간의 시작 시각을 그대로 쓴다).
#   3) 오늘도 내일도 빈 시간이 없으면 알림을 만들지 않고 None을 반환한다.
# 언제 쓰이나: 앞으로 "이 과목 복습이 필요하다"고 판단되는 시점(예: 퀴즈 오답노트가 쌓였을 때,
#   또는 예정된 배치 작업)에서 호출하도록 만들어진 함수다. 이번 작업 범위에는 이 함수를 직접
#   호출하는 HTTP 엔드포인트가 포함되어 있지 않다 — routers/schedule.py는 이미 만들어진
#   알림을 "조회"하고 "완료 체크"하는 엔드포인트만 제공한다.
def create_review_notification(user_id: int, subject_id: int, db: Session) -> Notification | None:
    subject = db.get(Subject, subject_id)
    if subject is None or subject.user_id != user_id:
        raise ValueError("Subject not found")

    existing = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.related_type == "review_quiz",
            Notification.related_id == subject_id,
            Notification.is_completed.is_(False),
        )
        .first()
    )
    if existing is not None:
        return existing

    today = date.today()
    notify_date = today
    slots = find_free_time_slots(user_id, notify_date, db)
    if not slots:
        notify_date = today + timedelta(days=1)
        slots = find_free_time_slots(user_id, notify_date, db)
    if not slots:
        # 오늘도 내일도 1시간 이상 비는 시간이 없으면, 억지로 알림을 만들지 않는다.
        return None

    slot_start, _ = slots[0]
    notification = Notification(
        user_id=user_id,
        message=f"{subject.name} 복습할 시간이에요",
        related_type="review_quiz",
        related_id=subject.id,
        is_completed=False,
        notify_at=datetime.combine(notify_date, slot_start),
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)

    # 저장(commit)이 끝난 뒤에만 메일을 보낸다. 별도 데몬 스레드라서 메일 발송이 느리거나 실패해도
    # 알림 저장과 API 응답에는 영향이 없다. 이미 있던 알림을 그대로 돌려주는 위 경로에서는 보내지 않는다.
    threading.Thread(target=_send_review_email_for, args=(notification.id,), daemon=True).start()
    return notification
