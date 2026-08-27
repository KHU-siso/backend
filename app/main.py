# =============================================================================
# 이 파일의 역할 (main.py)
# -----------------------------------------------------------------------------
# 이 프로젝트의 "진입점(entry point)"입니다. uvicorn 같은 ASGI 서버가 실행할 때
# 최종적으로 가리키는 FastAPI 애플리케이션 객체(app)가 이 파일에서 만들어집니다.
#   실행 명령 예: uvicorn app.main:app --reload
#
# 하는 일은 크게 3가지입니다.
#   1) 서버가 켜질 때 DB 테이블을 자동으로 만든다 (없으면 생성, 있으면 그대로 둠)
#   2) 프론트엔드(다른 도메인/포트)에서의 API 호출을 허용하도록 CORS 설정을 한다
#   3) 각 기능별로 나뉘어 있는 라우터들(auth, dashboard, documents, chat)을
#      하나의 앱으로 조립해서 등록한다
# =============================================================================

# FastAPI 라이브러리에서 가져옴 — FastAPI: 웹 애플리케이션 객체를 만드는 핵심 클래스
from fastapi import FastAPI
# CORS(Cross-Origin Resource Sharing) 관련 미들웨어.
# 브라우저는 기본적으로 "다른 출처(도메인/포트)"로의 API 요청을 보안상 막는데,
# 프론트엔드(예: localhost:3000)와 백엔드(예: localhost:8000)가 다른 포트에서 돌 때
# 이 미들웨어가 있어야 프론트엔드에서 정상적으로 API를 호출할 수 있다.
from fastapi.middleware.cors import CORSMiddleware

# app/database.py에서 가져옴
# - Base: 모든 ORM 모델(User, Document 등)이 상속받는 부모 클래스. Base.metadata 안에는
#   지금까지 정의된 모든 테이블의 설계도가 들어있다.
# - engine: PostgreSQL과 실제로 연결된 엔진 객체.
from app.database import Base, engine
# app/routers 폴더 안의 라우터 모듈들을 가져온다. 각 모듈 안에는 APIRouter로 만든
# router 객체가 하나씩 들어있다 (예: auth.router, chat.router 등).
from app.routers import auth, chat, dashboard, documents, quiz, schedule, subjects

# Base.metadata.create_all(bind=engine):
#   지금까지 app/models.py에서 정의된 모든 테이블(users, documents, document_chunks,
#   chat_conversations, chat_messages)을 확인해서, PostgreSQL에 아직 없는 테이블만 새로 만든다.
#   이미 존재하는 테이블은 건드리지 않는다 (컬럼 변경 같은 "마이그레이션"은 처리하지 않음 —
#   나중에 테이블 구조를 바꾸게 되면 Alembic 같은 별도 마이그레이션 도구가 필요하다).
#   이 코드는 파일이 import되는 시점(=서버가 켜지는 시점)에 딱 한 번 실행된다.
Base.metadata.create_all(bind=engine)

# FastAPI 애플리케이션 객체 생성. title="Siso API"는 자동 생성되는 API 문서(/docs)의
# 제목으로 표시된다.
app = FastAPI(title="Siso API")

# CORS 미들웨어 등록 — 모든 요청/응답에 공통으로 적용되는 처리 계층을 추가하는 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # "*"는 모든 출처(도메인)에서의 요청을 허용한다는 뜻. 개발 단계라 전체 허용.
    allow_methods=["*"],   # GET, POST, PUT, DELETE 등 모든 HTTP 메서드를 허용
    allow_headers=["*"],   # Authorization, Content-Type 등 모든 요청 헤더를 허용
)

# 각 라우터 모듈의 router 객체를 app에 등록한다.
# include_router로 등록하면, 그 라우터 파일 안에서 @router.get/@router.post로 정의한
# 모든 엔드포인트가 이 app에 실제로 연결되어 요청을 받을 수 있게 된다.
app.include_router(auth.router)         # /api/auth/...
app.include_router(dashboard.router)    # /api/dashboard
app.include_router(documents.router)    # /api/documents/...
app.include_router(chat.router)         # /api/chat/...
app.include_router(subjects.router)     # /api/subjects/...
app.include_router(quiz.router)         # /api/quiz/..., /api/wrong-notes
app.include_router(schedule.router)     # /api/events/..., /api/dashboard/..., /api/notifications/..., /api/character


# 헬스체크(health check)용 엔드포인트.
# 언제 쓰이나: 배포 환경(Render/Railway 등)이나 모니터링 도구가 "서버가 살아있는지"를
# 확인할 때 GET /health로 요청을 보내고, 정상이면 이 함수가 200 응답을 준다.
# 별도의 라우터 파일 없이 main.py에 직접 정의한 이유는, 인증이 필요 없는 아주 단순한
# 상태 확인용 엔드포인트라 굳이 라우터를 따로 만들 필요가 없기 때문이다.
@app.get("/health")
def health():
    return {"status": "ok"}
