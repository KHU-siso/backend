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

# 파이썬 표준 라이브러리
from datetime import date, datetime, time  # date/time: 마감일, 수업 시작/종료 시각에 사용

# Pydantic 라이브러리에서 가져옴
# - BaseModel: 모든 스키마 클래스가 상속받는 기본 클래스. 필드를 선언하면 자동으로 타입 검증이 붙는다.
# - computed_field: 저장된 필드가 아니라 다른 필드로부터 계산해서 응답에 포함시키는 필드를 정의할 때 사용
#   (예: is_canceled_this_week 값으로부터 만들어지는 안내 문구).
# - ConfigDict: BaseModel의 동작 방식을 세부 설정할 때 사용 (아래 from_attributes=True에 사용됨)
# - EmailStr: 그냥 문자열이 아니라 "이메일 형식이 맞는지"까지 자동으로 검사해주는 특수 문자열 타입
# - Field: 필드에 추가 제약(범위 등)을 걸 때 사용 (예: 반영비율은 0~100 사이여야 함)
from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field
# typing.Literal: "이 값들 중 하나만 허용" 이라는 제약을 타입으로 표현. 잘못된 값이 오면
# FastAPI가 자동으로 422 에러로 거절해준다 (day_of_week, quiz_type, mood에 사용).
from typing import Literal

# DayOfWeek: 요일은 이 7개 문자열 중 하나만 허용된다.
DayOfWeek = Literal["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
# QuizType: 퀴즈 유형은 "객관식" 또는 "주관식" 둘 중 하나만 허용된다.
QuizType = Literal["객관식", "주관식"]
# Mood: 캐릭터 기분은 이 3가지 값만 허용된다.
Mood = Literal["happy", "sad", "neutral"]


# UserCreate: 회원가입 API(POST /api/auth/signup)의 요청 body 형태.
# 프론트엔드가 이 형태의 JSON({"email": "...", "password": "...", "nickname": "..."})을 보내야 한다.
class UserCreate(BaseModel):
    email: EmailStr  # 올바른 이메일 형식이 아니면 FastAPI가 자동으로 요청을 거부한다
    password: str
    nickname: str


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
    nickname: str
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


# SubjectCreate: 과목 등록 API(POST /api/subjects)의 요청 body 형태.
# 시간표 정보(요일/시작-종료 시각)와 성적 반영비율을 한 번에 받는다.
class SubjectCreate(BaseModel):
    name: str
    day_of_week: DayOfWeek
    start_time: time
    end_time: time
    # Field(ge=0, le=100): 0~100 사이의 값만 허용 (퍼센트이므로)
    midterm_ratio: int = Field(ge=0, le=100, default=0)
    final_ratio: int = Field(ge=0, le=100, default=0)
    assignment_ratio: int = Field(ge=0, le=100, default=0)
    attendance_ratio: int = Field(ge=0, le=100, default=0)


# SubjectOut: 과목 정보를 응답할 때 쓰는 형태 (과목 등록 결과, 목록 조회에 사용)
class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    day_of_week: DayOfWeek
    start_time: time
    end_time: time
    midterm_ratio: int
    final_ratio: int
    assignment_ratio: int
    attendance_ratio: int
    is_canceled_this_week: bool
    created_at: datetime

    # cancellation_notice: DB에 저장된 값이 아니라 is_canceled_this_week로부터 매번 계산해서
    # 응답에 포함시키는 필드. 휴강이 아니면 None이라 프론트엔드는 이 값이 있을 때만 문구를 보여주면 된다.
    @computed_field
    @property
    def cancellation_notice(self) -> str | None:
        return "이번주는 휴강했어요" if self.is_canceled_this_week else None


# AssignmentCreate: 과제 등록 API(POST /api/subjects/{subject_id}/assignments)의 요청 body 형태.
class AssignmentCreate(BaseModel):
    title: str
    due_date: date


# AssignmentOut: 과제 하나를 응답할 때 쓰는 기본 형태 (과제 등록 결과에 사용)
class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    title: str
    due_date: date
    created_at: datetime


# PriorityChecklistItem: 우선순위 체크리스트(GET /api/dashboard/priority)의 항목 하나.
# 학습 스타일 구분 없이 모든 유저에게 동일한 로직(마감 임박순, 밀린 것 우선)으로 계산된다.
# is_overdue가 True면 이미 마감을 지난 항목이라는 뜻이고, 그 경우 days_remaining은 음수가 된다.
class PriorityChecklistItem(BaseModel):
    assignment_id: int
    subject_id: int
    subject_name: str
    title: str
    due_date: date
    is_overdue: bool
    days_remaining: int


# EventCreate: 개인 일정 등록 API(POST /api/events)의 요청 body 형태.
class EventCreate(BaseModel):
    title: str
    date: date
    start_time: time
    end_time: time
    memo: str | None = None


# EventOut: 개인 일정 정보를 응답할 때 쓰는 형태 (등록 결과, 목록 조회에 사용)
class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    date: date
    start_time: time
    end_time: time
    memo: str | None


# CharacterStateOut: 캐릭터 상태 조회(GET /api/character) 응답 형태.
class CharacterStateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    coin_balance: int
    mood: Mood
    updated_at: datetime


# NotificationOut: 알림 하나를 응답할 때 쓰는 형태 (알림 목록 조회, 완료 체크 결과에 사용).
# related_type은 day_of_week 등과 달리 앞으로 새 값이 추가될 수 있는 개방형 문자열이라
# Literal로 제한하지 않는다 (app/models.py의 Notification.related_type 주석 참고).
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message: str
    related_type: str
    related_id: int | None
    is_completed: bool
    notify_at: datetime
    created_at: datetime


# QuizGenerateRequest: 퀴즈 생성 API(POST /api/quiz/generate)의 요청 body 형태.
class QuizGenerateRequest(BaseModel):
    document_id: int
    quiz_type: QuizType


# QuizSetOut: 퀴즈 세트 정보를 응답할 때 쓰는 형태 (생성 결과에 사용).
# score는 아직 결과 조회 전이면 None이다.
class QuizSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int | None
    quiz_type: QuizType
    total_questions: int
    score: int | None
    created_at: datetime


# QuizQuestionOut: 문제 하나를 조회할 때 쓰는 형태.
# 의도적으로 correct_answer/explanation을 포함하지 않는다 — 풀기 전에 정답이 보이면
# 퀴즈로서 의미가 없기 때문에, 정답은 제출(submit) 이후 응답에서만 내려준다.
class QuizQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quiz_set_id: int
    question_index: int
    question_text: str
    options: list[str] | None


# QuizSubmitRequest: 답 제출/재도전 API 공통 요청 body 형태.
class QuizSubmitRequest(BaseModel):
    user_answer: str


# QuizSubmitResponse: 답 제출/재도전 API의 응답 형태. 채점 결과와 함께 정답·해설을 공개한다.
class QuizSubmitResponse(BaseModel):
    question_id: int
    user_answer: str
    is_correct: bool
    correct_answer: str
    explanation: str


# QuizResultOut: 퀴즈 세트 결과 조회(GET /api/quiz/{quiz_set_id}/result) 응답 형태.
# score는 정답률(%)이며, correct_count/total_questions로 "5/10"처럼 분수 형태도 조립할 수 있다.
# coins_awarded/choices는 services/coin_service.py의 calculate_quiz_reward 결과를 그대로 반영한다 —
# coins_awarded는 이미 지급된 코인 수(재조회 시에도 값은 유지되지만 중복 지급되지는 않는다),
# choices는 정답률이 50% 미만일 때만 채워지는 "다시 도전할지" 선택지 문구다.
class QuizResultOut(BaseModel):
    quiz_set_id: int
    total_questions: int
    correct_count: int
    score: int
    coins_awarded: int
    choices: list[str] | None


# WrongNoteOut: 오답노트(GET /api/wrong-notes) 목록의 항목 하나.
# 같은 문제를 여러 번 틀렸어도 가장 최근 오답 기록 하나만 나타낸다.
class WrongNoteOut(BaseModel):
    quiz_question_id: int
    quiz_set_id: int
    question_text: str
    options: list[str] | None
    user_answer: str
    correct_answer: str
    explanation: str
    answered_at: datetime
