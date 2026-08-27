# =============================================================================
# 이 파일의 역할 (routers/dashboard.py)
# -----------------------------------------------------------------------------
# 로그인 후 첫 화면(대시보드)에 필요한 정보를 한 번에 모아서 내려주는 API 라우터입니다.
# 엔드포인트가 하나뿐입니다.
#
#   - GET /api/dashboard : 현재 로그인한 유저의 정보 + 문서/대화 개수 + 최근 목록들
#
# 여러 테이블(User, Document, ChatConversation)에 흩어진 정보를 조합해서
# app/schemas.py의 DashboardOut 형태 하나로 합쳐 응답하는 것이 이 파일의 역할입니다.
# =============================================================================

# FastAPI에서 가져옴 — APIRouter(엔드포인트 묶음), Depends(의존성 주입)
from fastapi import APIRouter, Depends
# SQLAlchemy의 func — SQL의 집계 함수(COUNT 등)를 파이썬 코드에서 쓸 수 있게 해줌
from sqlalchemy import func
# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/deps.py: 로그인 유저 조회(get_current_user), DB 세션 생성(get_db)
from app.deps import get_current_user, get_db
# app/models.py: 통계를 낼 대상 테이블들의 ORM 모델
from app.models import ChatConversation, Document, User
# app/schemas.py: 응답 형태를 정의하는 Pydantic 모델들
from app.schemas import ConversationOut, DashboardOut, DocumentOut, UserOut
# services/coin_service.py: 마감 지난 미완료 항목이 있으면 캐릭터 기분을 "sad"로 갱신
from app.services.coin_service import update_mood_on_incomplete

# 이 라우터의 모든 엔드포인트는 "/api/dashboard"로 시작한다.
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# get_dashboard: 대시보드 화면에 필요한 정보를 한 번에 모아 응답하는 함수.
# 어디서 온 기능인가:
#   current_user: User = Depends(get_current_user) → 로그인된 유저를 자동으로 가져옴 (없으면 401 에러)
#   db: Session = Depends(get_db) → 이번 요청 전용 DB 세션
# 무슨 기능을 하나: 이 유저가 올린 문서 개수, 만든 대화방 개수, 그리고 각각 최근 5개씩을
#   조회해서 하나의 DashboardOut으로 합쳐 반환한다. 그 전에 update_mood_on_incomplete로
#   마감 지난 과제나 미완료 알림이 있는지 확인해서, 있으면 캐릭터 기분을 "sad"로 갱신해둔다
#   (대시보드를 열 때마다 캐릭터 상태가 최신으로 맞춰지도록 하는 부수 효과).
# 언제 쓰이나: 프론트엔드 앱을 켜서 로그인 후 대시보드 화면으로 이동했을 때 호출된다.
@router.get("", response_model=DashboardOut)
def get_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 응답 자체에는 반영되지 않는 부수 효과(side effect)다 — DashboardOut에 캐릭터 정보를
    # 담지는 않지만, 이후 GET /api/character를 호출했을 때 최신 기분이 보이도록 미리 갱신해둔다.
    update_mood_on_incomplete(current_user.id, db)

    # db.query(func.count(Document.id)).filter(...).scalar():
    #   "SELECT COUNT(id) FROM documents WHERE user_id = 현재유저id"와 같은 효과.
    #   .scalar()는 결과가 표 형태(row)가 아니라 숫자 하나만 필요할 때 값 하나만 뽑아준다.
    #   결과가 None일 가능성(이론상 없지만 방어적으로)을 대비해 "or 0"으로 기본값을 준다.
    document_count = (
        db.query(func.count(Document.id)).filter(Document.user_id == current_user.id).scalar() or 0
    )
    # 위와 같은 방식으로 이 유저의 대화방 개수를 센다.
    conversation_count = (
        db.query(func.count(ChatConversation.id))
        .filter(ChatConversation.user_id == current_user.id)
        .scalar()
        or 0
    )
    # 최근 업로드한 문서 5개를 최신순(created_at 내림차순)으로 조회.
    # order_by(...desc()) → 최신 것이 먼저 오도록 정렬, limit(5) → 5개까지만 가져옴.
    recent_documents = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .limit(5)
        .all()
    )
    # 최근 만든 대화방 5개를 최신순으로 조회.
    recent_conversations = (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == current_user.id)
        .order_by(ChatConversation.created_at.desc())
        .limit(5)
        .all()
    )

    # 위에서 모은 정보들을 DashboardOut(app/schemas.py) 형태에 맞춰 조립해서 반환한다.
    # ...Out.model_validate(...): SQLAlchemy ORM 객체를 응답용 Pydantic 스키마로 변환.
    # 리스트에 대해서는 [DocumentOut.model_validate(d) for d in recent_documents]처럼
    # 각 항목을 하나씩 변환해서 리스트로 다시 묶는다.
    return DashboardOut(
        user=UserOut.model_validate(current_user),
        document_count=document_count,
        conversation_count=conversation_count,
        recent_documents=[DocumentOut.model_validate(d) for d in recent_documents],
        recent_conversations=[ConversationOut.model_validate(c) for c in recent_conversations],
    )
