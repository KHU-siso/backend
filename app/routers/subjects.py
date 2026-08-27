# =============================================================================
# 이 파일의 역할 (routers/subjects.py)
# -----------------------------------------------------------------------------
# 과목(시간표) 등록/조회, 과제 등록, 이번 주 휴강 토글을 담당하는 API 라우터입니다.
#
#   - POST  /api/subjects                              : 과목 등록 (시간표 + 성적 반영비율)
#   - GET   /api/subjects                                : 내 과목 목록 조회
#   - POST  /api/subjects/{subject_id}/assignments        : 특정 과목에 과제 등록
#   - PATCH /api/subjects/{subject_id}/cancel-week        : 이번 주 휴강 여부 토글
#
# 과제 우선순위 조회는 더 이상 이 파일에 있지 않다 — 예전에는 유저의 learning_style
# ("복습형"/"벼락치기형")에 따라 마감 기준과 복습 추천 로직이 갈렸지만, User에서
# learning_style이 제거되면서 그 분기 자체가 의미를 잃었다. 학습 스타일 구분 없이 모든 유저에게
# 동일하게 적용되는 새 우선순위 로직은 services/priority_service.py로 옮겨졌고,
# GET /api/dashboard/priority(routers/schedule.py)로 조회한다.
# =============================================================================

# FastAPI에서 가져옴 — 라우터 등록, 의존성 주입, 에러 응답
from fastapi import APIRouter, Depends, HTTPException, status
# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/deps.py: 로그인 유저 조회, DB 세션 생성 (documents.py, chat.py와 동일한 패턴)
from app.deps import get_current_user, get_db
# app/models.py: 과목/과제/유저 ORM 모델
from app.models import Assignment, Subject, User
# app/schemas.py: 요청/응답 형태 정의
from app.schemas import AssignmentCreate, AssignmentOut, SubjectCreate, SubjectOut
# services/notification_service.py: 과목을 등록하는 시점에 "복습할 시간이에요" 알림을
# 미리 하나 만들어두기 위해 사용한다.
from app.services.notification_service import create_review_notification

# 이 라우터의 모든 엔드포인트는 "/api/subjects"로 시작한다.
router = APIRouter(prefix="/api/subjects", tags=["subjects"])


# create_subject: 과목 하나를 등록하는 함수. 시간표(요일/시작-종료 시각)와 성적 반영비율을
# 한 번에 받아 저장한다. 등록 직후 create_review_notification으로 그 과목에 대한 첫 "복습할
# 시간이에요" 알림도 함께 만들어둔다 — 시간표를 등록해두고 정작 복습 리마인더가 하나도 없는
# 상태를 방지하기 위한 트리거다.
# 언제 쓰이나: 프론트엔드의 "과목 등록" 화면에서 시간표를 입력하고 저장 버튼을 눌렀을 때 호출된다.
@router.post("", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(
    payload: SubjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subject = Subject(
        user_id=current_user.id,
        name=payload.name,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        midterm_ratio=payload.midterm_ratio,
        final_ratio=payload.final_ratio,
        assignment_ratio=payload.assignment_ratio,
        attendance_ratio=payload.attendance_ratio,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)

    # 오늘/내일 빈 시간이 전혀 없으면 create_review_notification이 None을 반환할 수 있다
    # (services/notification_service.py 참고) — 그 경우에도 과목 등록 자체는 실패로 보지 않는다.
    create_review_notification(current_user.id, subject.id, db)

    return subject


# list_subjects: 현재 로그인한 유저가 등록한 과목 목록을 조회하는 함수.
# 언제 쓰이나: 프론트엔드의 "내 시간표" 화면을 그릴 때 호출된다. is_canceled_this_week가 True인
# 과목은 SubjectOut.cancellation_notice에 "이번주는 휴강했어요" 문구가 자동으로 채워져 내려간다.
@router.get("", response_model=list[SubjectOut])
def list_subjects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Subject)
        .filter(Subject.user_id == current_user.id)
        .order_by(Subject.start_time)
        .all()
    )


# create_assignment: 특정 과목에 과제를 등록하는 함수.
# 어디서 온 기능인가: subject_id: int → URL 경로의 "{subject_id}" 부분이 자동으로 정수로 파싱되어 들어옴.
# 무슨 기능을 하나: 이 과목이 실제로 존재하고 내 것이 맞는지 확인한 뒤 과제를 저장한다.
# 언제 쓰이나: 프론트엔드에서 특정 과목 화면에 들어가 "과제 추가" 버튼을 눌렀을 때 호출된다.
@router.post(
    "/{subject_id}/assignments",
    response_model=AssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_assignment(
    subject_id: int,
    payload: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subject = _get_owned_subject(db, subject_id, current_user.id)
    assignment = Assignment(subject_id=subject.id, title=payload.title, due_date=payload.due_date)
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


# toggle_cancel_week: 과목 하나의 "이번 주 휴강" 여부를 뒤집는(토글) 함수.
# 무슨 기능을 하나: 별도의 요청 body 없이, 호출할 때마다 현재 값의 반대로 뒤집는다
#   (휴강 아님 → 휴강, 휴강 → 휴강 아님). "취소"도 같은 엔드포인트를 한 번 더 눌러서 처리한다.
# 언제 쓰이나: 교수님이 이번 주 휴강을 공지했을 때 유저가 그 과목 화면에서 "휴강" 버튼을 누르면 호출된다.
#   is_canceled_this_week가 True인 동안은 services/priority_service.py의 find_free_time_slots가
#   그 시간대를 "수업 중"이 아니라 "빈 시간"으로 계산한다.
@router.patch("/{subject_id}/cancel-week", response_model=SubjectOut)
def toggle_cancel_week(
    subject_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subject = _get_owned_subject(db, subject_id, current_user.id)
    subject.is_canceled_this_week = not subject.is_canceled_this_week
    db.commit()
    db.refresh(subject)
    return subject


# _get_owned_subject: "이 subject_id가 실제로 존재하고, 요청한 유저의 것이 맞는지" 확인하는
# 내부 헬퍼 함수. documents.py의 _get_owned_document와 동일한 패턴이다.
def _get_owned_subject(db: Session, subject_id: int, user_id: int) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None or subject.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    return subject
