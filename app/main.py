# =============================================================================
# 이 파일의 역할 (main.py)
# -----------------------------------------------------------------------------
# 이 프로젝트의 "진입점(entry point)"입니다. uvicorn 같은 ASGI 서버가 실행할 때
# 최종적으로 가리키는 FastAPI 애플리케이션 객체(app)가 이 파일에서 만들어집니다.
#   실행 명령 예: uvicorn app.main:app --reload
#
# 하는 일은 크게 5가지입니다.
#   1) 로깅 포맷/레벨을 설정한다 (다른 무엇보다도 가장 먼저 실행되어야 함)
#   2) 서버가 켜질 때 DB 테이블을 자동으로 만든다 (없으면 생성, 있으면 그대로 둠)
#   3) 프론트엔드(다른 도메인/포트)에서의 API 호출을 허용하도록 CORS 설정을 한다
#   4) 전역 예외 처리와 요청 로깅 미들웨어를 등록한다
#   5) 각 기능별로 나뉘어 있는 라우터들(auth, dashboard, documents, chat 등)을
#      하나의 앱으로 조립해서 등록한다
# =============================================================================

from contextlib import asynccontextmanager

# FastAPI 라이브러리에서 가져옴 — FastAPI: 웹 애플리케이션 객체를 만드는 핵심 클래스
from fastapi import FastAPI
# 시작 시 컬럼 보강용 raw SQL 실행에 사용
from sqlalchemy import text
# CORS(Cross-Origin Resource Sharing) 관련 미들웨어.
# 브라우저는 기본적으로 "다른 출처(도메인/포트)"로의 API 요청을 보안상 막는데,
# 프론트엔드(예: localhost:3000)와 백엔드(예: localhost:8000)가 다른 포트에서 돌 때
# 이 미들웨어가 있어야 프론트엔드에서 정상적으로 API를 호출할 수 있다.
from fastapi.middleware.cors import CORSMiddleware

# app/config.py에서 settings를 가져온다 — CORS 허용 도메인 목록(allowed_origins_list)을 쓰기 위함.
from app.config import settings
# app/error_handlers.py: Claude API 실패, DB 에러, 그 외 예상 못한 에러까지 전부 일관된
# {"detail": ..., "error_code": ...} 형태의 JSON으로 응답하게 해주는 전역 예외 핸들러 등록 함수.
from app.error_handlers import register_exception_handlers
# app/logging_config.py: logging 모듈의 포맷/레벨을 앱 전체 기준으로 한 번 설정하는 함수.
# 다른 어떤 모듈이 logger를 쓰기 전에(=가장 먼저) 실행되어야 하므로 이 파일 맨 위에서 바로 호출한다.
from app.logging_config import configure_logging
# app/middleware.py: 모든 요청의 메서드/경로/상태코드/처리시간을 한 줄 로그로 남기는
# 미들웨어를 등록하는 함수.
from app.middleware import register_request_logging
# app/database.py에서 가져옴
# - Base: 모든 ORM 모델(User, Document 등)이 상속받는 부모 클래스. Base.metadata 안에는
#   지금까지 정의된 모든 테이블의 설계도가 들어있다.
# - engine: PostgreSQL과 실제로 연결된 엔진 객체.
from app.database import Base, engine
# app/routers 폴더 안의 라우터 모듈들을 가져온다. 각 모듈 안에는 APIRouter로 만든
# router 객체가 하나씩 들어있다 (예: auth.router, chat.router 등).
from app.services.deadline_scheduler import DeadlineScheduler
from app.routers import auth, chat, dashboard, documents, quiz, schedule, shop, state, subjects

# configure_logging(): 이 파일(main.py)이 임포트되는 시점에 가장 먼저 실행되어야 한다.
# 이보다 늦게 부르면, 그 사이에 다른 모듈에서 이미 만들어진 로거가 아직 설정 안 된
# 기본 포맷으로 로그를 남겨버릴 수 있기 때문이다.
configure_logging()

# Base.metadata.create_all(bind=engine):
#   지금까지 app/models.py에서 정의된 모든 테이블(users, documents, document_chunks,
#   chat_conversations, chat_messages)을 확인해서, PostgreSQL에 아직 없는 테이블만 새로 만든다.
#   이미 존재하는 테이블은 건드리지 않는다 (컬럼 변경 같은 "마이그레이션"은 처리하지 않음 —
#   나중에 테이블 구조를 바꾸게 되면 Alembic 같은 별도 마이그레이션 도구가 필요하다).
#   이 코드는 파일이 import되는 시점(=서버가 켜지는 시점)에 딱 한 번 실행된다.
Base.metadata.create_all(bind=engine)

# create_all은 이미 있는 테이블에 새 컬럼을 추가하지 못한다. Alembic을 쓰지 않는 이 프로젝트에서는
# notifications.email_sent처럼 나중에 추가된 컬럼을 이렇게 직접 보강한다 (IF NOT EXISTS라 반복 실행해도 안전).
with engine.begin() as _conn:
    _conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_sent BOOLEAN NOT NULL DEFAULT false"))
    _conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS subject_ref VARCHAR(64)"))
    _conn.execute(text("ALTER TABLE email_verifications ADD COLUMN IF NOT EXISTS verified BOOLEAN NOT NULL DEFAULT false"))
    _conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deadline_email_enabled BOOLEAN NOT NULL DEFAULT true"))
    _conn.execute(text("ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS subject_ref VARCHAR(64)"))
    _conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_conversations_subject_ref ON chat_conversations (subject_ref)"))
    _conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_conversations_user_subject ON chat_conversations (user_id, subject_ref)"))
    _conn.execute(text("ALTER TABLE character_states ADD COLUMN IF NOT EXISTS signup_bonus_granted BOOLEAN NOT NULL DEFAULT false"))

# FastAPI 애플리케이션 객체 생성. title="Siso API"는 자동 생성되는 API 문서(/docs)의
# 제목으로 표시된다.
# 서버가 켜질 때 과제 마감 알림 스케줄러를 띄우고, 꺼질 때 멈춘다. (SCHEDULER_ENABLED=false면 아무것도 안 함)
# 서버가 여러 대여도 중복 발송은 DB의 email_notification_logs 유니크 제약이 막는다.
@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler = DeadlineScheduler()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Siso API", lifespan=lifespan)

# CORS 미들웨어 등록 — 모든 요청/응답에 공통으로 적용되는 처리 계층을 추가하는 것.
# allow_origins는 더 이상 "*"(전체 허용)를 쓰지 않고, settings.allowed_origins_list
# (.env의 ALLOWED_ORIGINS)에 명시된 프론트엔드 도메인만 허용한다.
# 로그인 토큰(Authorization 헤더)이 오가는 API라 전체 허용은 위험하다 — 아무 사이트에서나
# 이 API로 로그인된 유저 대신 요청을 보낼 수 있게 되기 때문이다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_methods=["*"],   # GET, POST, PUT, DELETE 등 모든 HTTP 메서드를 허용
    allow_headers=["*"],   # Authorization, Content-Type 등 모든 요청 헤더를 허용
)

# 전역 예외 핸들러 등록 — 이 아래로 정의된 라우터들에서 발생하는 모든 예외
# (HTTPException, 요청 검증 실패, Claude API 오류, DB 오류, 그 외 예상 못한 에러)가
# 전부 app/error_handlers.py에서 정의한 일관된 JSON 포맷으로 응답된다.
register_exception_handlers(app)

# 요청 로깅 미들웨어 등록 — 이 아래로 등록되는 모든 라우터에 들어오는 요청이
# "메서드 경로 상태코드 처리시간" 한 줄로 서버 로그에 남는다.
register_request_logging(app)

# 각 라우터 모듈의 router 객체를 app에 등록한다.
# include_router로 등록하면, 그 라우터 파일 안에서 @router.get/@router.post로 정의한
# 모든 엔드포인트가 이 app에 실제로 연결되어 요청을 받을 수 있게 된다.
app.include_router(auth.router)         # /api/auth/...
app.include_router(dashboard.router)    # /api/dashboard
app.include_router(documents.router)    # /api/documents/...
app.include_router(chat.router)         # /api/chat/...
app.include_router(subjects.router)     # /api/subjects/...
app.include_router(quiz.router)         # /api/quiz/..., /api/wrong-notes
app.include_router(state.router)        # /api/state/...
app.include_router(shop.router)         # /api/shop/...
app.include_router(schedule.router)     # /api/events/..., /api/dashboard/..., /api/notifications/..., /api/character


# 헬스체크(health check)용 엔드포인트.
# 언제 쓰이나: 배포 환경(Render/Railway 등)이나 모니터링 도구가 "서버가 살아있는지"를
# 확인할 때 GET /health로 요청을 보내고, 정상이면 이 함수가 200 응답을 준다.
# 별도의 라우터 파일 없이 main.py에 직접 정의한 이유는, 인증이 필요 없는 아주 단순한
# 상태 확인용 엔드포인트라 굳이 라우터를 따로 만들 필요가 없기 때문이다.
@app.get("/health")
def health():
    return {"status": "ok"}
