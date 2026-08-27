# =============================================================================
# 이 파일의 역할 (routers/schedule.py)
# -----------------------------------------------------------------------------
# 개인 일정, 우선순위 체크리스트, 알림, 캐릭터 상태 조회를 담당하는 API 라우터입니다.
#
#   - POST /api/events                              : 개인 일정 등록
#   - GET  /api/events                                : 내 개인 일정 목록 조회
#   - GET  /api/dashboard/priority                    : 과제 우선순위 체크리스트 조회
#   - GET  /api/dashboard/notifications               : 완료 안 된 내 알림 목록 조회
#   - POST /api/notifications/{notification_id}/complete : 알림 완료 체크
#   - GET  /api/character                             : 내 캐릭터(코인/기분) 상태 조회
#
# 실제 계산 로직(우선순위, 캐릭터 상태 생성)은 services/priority_service.py,
# services/coin_service.py에 있고, 이 파일은 요청을 받아 소유권을 확인하고 그 결과를
# 그대로 돌려주는 역할만 한다.
# =============================================================================

# FastAPI에서 가져옴 — 라우터 등록, 의존성 주입, 에러 응답
from fastapi import APIRouter, Depends, HTTPException, status
# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/deps.py: 로그인 유저 조회, DB 세션 생성 (documents.py, chat.py, subjects.py와 동일한 패턴)
from app.deps import get_current_user, get_db
# app/models.py: 개인일정/알림/유저 ORM 모델
from app.models import Event, Notification, User
# app/schemas.py: 요청/응답 형태 정의
from app.schemas import CharacterStateOut, EventCreate, EventOut, NotificationOut, PriorityChecklistItem
# services/coin_service.py: 캐릭터 상태 조회(없으면 생성)
from app.services.coin_service import get_or_create_character_state
# services/priority_service.py: 학습 스타일 구분 없는 통합 우선순위 계산
from app.services.priority_service import get_priority_checklist

router = APIRouter(prefix="/api", tags=["schedule"])


# create_event: 개인 일정 하나를 등록하는 함수.
# 언제 쓰이나: 프론트엔드의 "일정 추가" 화면에서 제목/날짜/시간을 입력하고 저장했을 때 호출된다.
@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    payload: EventCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = Event(
        user_id=current_user.id,
        title=payload.title,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        memo=payload.memo,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# list_events: 현재 로그인한 유저의 개인 일정 목록을 날짜/시간순으로 조회하는 함수.
# 언제 쓰이나: 프론트엔드의 "내 일정" 화면을 그릴 때 호출된다.
@router.get("/events", response_model=list[EventOut])
def list_events(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Event)
        .filter(Event.user_id == current_user.id)
        .order_by(Event.date, Event.start_time)
        .all()
    )


# get_priority: 이 유저의 과제 우선순위 체크리스트를 조회하는 함수.
# 무슨 기능을 하나: services/priority_service.py의 get_priority_checklist를 그대로 호출한다
#   (학습 스타일 구분 없이 모든 유저에게 동일한 로직).
# 언제 쓰이나: 프론트엔드의 대시보드 화면에서 "오늘 할 일" 목록을 그릴 때 호출된다.
@router.get("/dashboard/priority", response_model=list[PriorityChecklistItem])
def get_priority(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_priority_checklist(current_user.id, db)


# list_notifications: 아직 체크하지 않은(is_completed=False) 내 알림 목록을 조회하는 함수.
# 언제 쓰이나: 프론트엔드의 대시보드 화면에서 알림/리마인더 영역을 그릴 때 호출된다.
@router.get("/dashboard/notifications", response_model=list[NotificationOut])
def list_notifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_completed.is_(False))
        .order_by(Notification.notify_at.asc())
        .all()
    )


# complete_notification: 알림 하나를 "완료"로 체크하는 함수.
# 언제 쓰이나: 유저가 알림 목록에서 체크박스를 눌렀을 때 호출된다. 이후 이 알림은
#   GET /api/dashboard/notifications 목록에 더 이상 나타나지 않는다.
@router.post("/notifications/{notification_id}/complete", response_model=NotificationOut)
def complete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notification.is_completed = True
    db.commit()
    db.refresh(notification)
    return notification


# get_character: 이 유저의 캐릭터 상태(코인 잔액, 기분)를 조회하는 함수.
# 무슨 기능을 하나: 아직 CharacterState가 없는 유저(예: 방금 가입해서 퀴즈를 한 번도 안 푼 경우)여도
#   get_or_create_character_state가 기본값으로 하나 만들어주므로 404 없이 항상 값을 돌려준다.
# 언제 쓰이나: 프론트엔드의 캐릭터(옹이) 화면이나 대시보드 상단에서 코인/기분을 보여줄 때 호출된다.
@router.get("/character", response_model=CharacterStateOut)
def get_character(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_or_create_character_state(db, current_user.id)
