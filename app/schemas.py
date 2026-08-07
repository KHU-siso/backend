# =============================================================================
# 이 파일의 역할 (schemas.py)
# -----------------------------------------------------------------------------
# API의 "요청(request) body"와 "응답(response) body" 형태를 정의하는 파일입니다.
# Pydantic 라이브러리의 BaseModel을 상속해서 만들며, FastAPI가 이 클래스들을 보고
#   1) 들어오는 JSON이 이 형태에 맞는지 자동으로 검증하고 (틀리면 자동으로 422 에러 응답)
#   2) 나가는 응답을 이 형태에 맞춰 자동으로 JSON으로 변환합니다.
#
# app/models.py(DB 테이블 구조, 내부용)와 이 파일(API 요청/응답 형태, 외부용)은
# 의도적으로 분리되어 있습니다. 예를 들어 User 모델에는 hashed_password가 있지만,
# UserOut에는 없기 때문에 API 응답에 비밀번호 해시가 절대 노출되지 않습니다.
#
# 이 파일은 사실상 "프론트엔드에게 주는 API 명세서"이기도 합니다 — 각 클래스의
# 필드 이름과 타입이 곧 실제 JSON 요청/응답의 스펙입니다.
# =============================================================================

# 파이썬 표준 라이브러리 — 날짜/시간 타입. created_at 같은 필드에 사용.
from datetime import datetime

# Pydantic 라이브러리에서 가져옴
# - BaseModel: 모든 스키마 클래스가 상속받는 기본 클래스. 필드를 선언하면 자동으로 타입 검증이 붙는다.
# - ConfigDict: BaseModel의 동작 방식을 세부 설정할 때 사용 (아래 from_attributes=True에 사용됨)
# - EmailStr: 그냥 문자열이 아니라 "이메일 형식이 맞는지"까지 자동으로 검사해주는 특수 문자열 타입
from pydantic import BaseModel, ConfigDict, EmailStr


# UserCreate: 회원가입 API(POST /api/auth/signup)의 요청 body 형태.
# 프론트엔드가 이 형태의 JSON({"email": "...", "password": "...", "name": "..."})을 보내야 한다.
class UserCreate(BaseModel):
    email: EmailStr  # 올바른 이메일 형식이 아니면 FastAPI가 자동으로 요청을 거부한다
    password: str
    name: str


# UserLogin: 로그인 API(POST /api/auth/login)의 요청 body 형태.
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# UserOut: 유저 정보를 클라이언트에게 보여줄 때 쓰는 "출력용" 형태.
# hashed_password 필드가 없으므로, User ORM 객체를 여기로 변환하는 순간 비밀번호 해시는 자동으로 빠진다.
class UserOut(BaseModel):
    # from_attributes=True: 원래 Pydantic은 dict만 잘 받아들이는데, 이 옵션을 켜면
    # SQLAlchemy User 객체처럼 "속성(user.id, user.email...)"으로 접근하는 객체도
    # UserOut.model_validate(user)로 그대로 변환할 수 있게 해준다.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    created_at: datetime


# TokenOut: 회원가입/로그인 성공 시 응답 형태. 로그인 토큰과 유저 정보를 함께 내려준다.
class TokenOut(BaseModel):
    access_token: str
    # token_type: 기본값 "bearer" — 프론트엔드가 이후 요청에서
    # "Authorization: {token_type} {access_token}" 형태로 헤더를 만들 때 참고하는 값.
    token_type: str = "bearer"
    user: UserOut  # 스키마 안에 다른 스키마(UserOut)를 그대로 중첩해서 쓸 수 있다


# DocumentOut: 업로드된 PDF 문서 정보를 응답할 때 쓰는 형태 (목록 조회, 업로드 결과 등에 사용)
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    num_pages: int
    num_chars: int
    created_at: datetime


# DocumentChunkOut: 문서를 나눈 청크 하나를 응답할 때 쓰는 형태 (청크 목록 조회 API에서 사용)
class DocumentChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    content: str


# ConversationCreate: 새 대화방을 만들 때(POST /api/chat/conversations) 보내는 요청 body 형태.
class ConversationCreate(BaseModel):
    # document_id: "int | None = None" → 값을 아예 안 보내거나 null을 보내도 되고(문서 없는 일반 대화),
    # 특정 문서의 id를 보내면 그 문서 기준 대화방이 된다.
    document_id: int | None = None
    # title: 안 보내면 서버가 자동으로 제목을 정한다(routers/chat.py 참고)
    title: str | None = None


# ConversationOut: 대화방 정보를 응답할 때 쓰는 형태 (대화방 생성/목록 조회 결과)
class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int | None
    title: str
    created_at: datetime


# MessageCreate: 대화방에 새 메시지를 보낼 때(POST /api/chat/conversations/{id}/messages)
# 사용하는 요청 body 형태. 유저가 입력한 질문 텍스트 하나만 담는다.
class MessageCreate(BaseModel):
    content: str


# MessageOut: 메시지 하나를 응답할 때 쓰는 형태 (메시지 목록 조회, 새 답변 응답 등에 사용)
class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str  # "user" 또는 "assistant"
    content: str
    created_at: datetime


# DashboardOut: 대시보드 화면 하나를 그리는 데 필요한 정보를 한 번에 묶어서 내려주는 형태.
# 여러 정보(유저 정보 + 통계 + 최근 목록들)를 하나의 응답으로 합쳐서, 프론트엔드가
# 대시보드를 그릴 때 API를 여러 번 호출하지 않아도 되게 해준다.
class DashboardOut(BaseModel):
    user: UserOut
    document_count: int
    conversation_count: int
    recent_documents: list[DocumentOut]  # 최근 업로드한 문서 목록 (리스트 형태로 여러 개)
    recent_conversations: list[ConversationOut]  # 최근 대화방 목록
