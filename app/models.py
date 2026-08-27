# =============================================================================
# 이 파일의 역할 (models.py)
# -----------------------------------------------------------------------------
# PostgreSQL에 실제로 만들어질 "테이블 구조"를 파이썬 클래스로 정의하는 파일입니다.
# SQLAlchemy ORM(Object-Relational Mapping)을 사용하면, 여기 정의한 클래스 하나가
# DB의 테이블 하나에 대응되고, 클래스의 인스턴스(객체) 하나가 그 테이블의 행(row) 하나에
# 대응됩니다. 즉 SQL문을 직접 안 써도 파이썬 객체를 다루듯 DB를 조작할 수 있게 해줍니다.
#
# 이 파일에는 14개의 테이블이 정의되어 있고, 서로 다음과 같이 연결되어 있습니다.
#
#   User(유저) 1 ─── N Document(업로드한 PDF 문서)
#   User(유저) 1 ─── N ChatConversation(대화방)
#   User(유저) 1 ─── N Subject(수강 과목/시간표)
#   User(유저) 1 ─── N QuizSet(퀴즈 세트)
#   User(유저) 1 ─── N QuizAttempt(퀴즈 풀이 기록)
#   User(유저) 1 ─── N Event(개인 일정)
#   User(유저) 1 ─── 1 CharacterState(옹이 캐릭터 상태)
#   User(유저) 1 ─── N Notification(알림)
#   Document(문서) 1 ─── N DocumentChunk(문서를 잘게 나눈 조각들)
#   Document(문서) 1 ─── N QuizSet(그 문서로 만든 퀴즈 세트들)
#   ChatConversation(대화방) 1 ─── N ChatMessage(대화방 안의 메시지들)
#   ChatConversation(대화방) N ─── 1 Document(대화방이 참조하는 문서, 없을 수도 있음)
#   Subject(과목) 1 ─── N Assignment(그 과목의 과제들)
#   QuizSet(퀴즈 세트) 1 ─── N QuizQuestion(세트 안의 문제들)
#   QuizQuestion(문제) 1 ─── N QuizAttempt(그 문제를 푼 기록들, 재도전 포함)
#
# 실제 테이블 생성은 app/main.py의 Base.metadata.create_all(...)에서 이 파일의
# 클래스 정의를 읽어 자동으로 처리합니다.
# =============================================================================

# SQLAlchemy 라이브러리에서 가져옴 — 테이블의 "컬럼(열)"을 정의할 때 쓰는 도구들
# - Boolean: 참/거짓만 저장하는 컬럼 타입 (퀴즈 정답 여부에 사용)
# - Column: 하나의 컬럼(열)을 정의하는 클래스
# - Date: 날짜만 저장하는 컬럼 타입 (시간 정보 없음, 과제 마감일에 사용)
# - DateTime: 날짜+시간을 저장하는 컬럼 타입
# - ForeignKey: 다른 테이블의 id를 참조하는 "외래키" 컬럼을 만들 때 사용
# - Integer: 정수를 저장하는 컬럼 타입
# - JSON: 리스트/딕셔너리 같은 구조를 그대로 저장하는 컬럼 타입 (객관식 보기 목록에 사용)
# - String: 길이 제한이 있는 문자열을 저장하는 컬럼 타입 (예: String(255))
# - Text: 길이 제한이 없는 긴 문자열을 저장하는 컬럼 타입 (PDF 청크 내용처럼 긴 글에 사용)
# - Time: 시:분:초만 저장하는 컬럼 타입 (수업 시작/종료 시각에 사용)
# - func: SQL 함수(예: func.now() = 현재 시각)를 파이썬에서 쓸 수 있게 해주는 도구
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text, Time, func
# relationship: 두 테이블(모델) 사이의 "관계"를 파이썬 객체 레벨에서 편하게 다루게 해주는 함수.
# 예를 들어 user.documents라고 쓰면 SQL JOIN을 직접 안 짜도 그 유저가 올린 문서 목록을 가져올 수 있다.
from sqlalchemy.orm import relationship

# app/database.py에서 만든 Base(모든 모델의 공통 부모 클래스)를 가져온다.
from app.database import Base


# User: 회원(사용자) 정보를 저장하는 테이블. routers/auth.py의 회원가입/로그인에서 사용된다.
class User(Base):
    # __tablename__: 실제 PostgreSQL에 생성될 테이블 이름
    __tablename__ = "users"

    # id: 기본키(primary_key=True). 값을 따로 안 넣어도 DB가 1, 2, 3...으로 자동 채번한다.
    id = Column(Integer, primary_key=True)
    # email: 로그인 아이디로 쓰이는 이메일. unique=True → 같은 이메일 중복 가입 방지(DB 레벨에서도 막아줌).
    # index=True → 이메일로 조회(로그인 시 WHERE email = ...)가 빨라지도록 색인을 만들어둠.
    email = Column(String(255), unique=True, nullable=False, index=True)
    # hashed_password: security.py의 hash_password()로 만든 해시값만 저장 (평문 비밀번호는 저장 안 함)
    hashed_password = Column(String(255), nullable=False)
    # nickname: 화면에 표시할 별명. 실명 대신 닉네임만 받도록 정책이 바뀌어 name을 대체한다.
    nickname = Column(String(50), nullable=False)
    # created_at: 가입 시각. server_default=func.now() → 행이 INSERT될 때 DB가 자동으로
    # 현재 시각을 채워준다 (파이썬 코드에서 따로 값을 넣지 않아도 됨).
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # documents: 이 유저가 올린 Document들과의 관계. back_populates="owner"는
    # Document 쪽의 owner 필드와 서로 짝을 이루도록 연결해준다는 뜻.
    # cascade="all, delete-orphan": 이 유저가 삭제되면, 이 유저 소유의 Document들도 함께 삭제된다.
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    # conversations: 이 유저의 대화방들과의 관계. 유저가 삭제되면 대화방들도 함께 삭제된다.
    conversations = relationship("ChatConversation", back_populates="owner", cascade="all, delete-orphan")
    # subjects: 이 유저가 등록한 과목(시간표)들과의 관계. 유저가 삭제되면 과목도 함께 삭제된다.
    subjects = relationship("Subject", back_populates="owner", cascade="all, delete-orphan")
    # quiz_sets: 이 유저가 생성한 퀴즈 세트들과의 관계. 유저가 삭제되면 퀴즈 세트도 함께 삭제된다.
    quiz_sets = relationship("QuizSet", back_populates="owner", cascade="all, delete-orphan")
    # quiz_attempts: 이 유저의 모든 퀴즈 풀이 기록(오답노트의 원본 데이터). 유저가 삭제되면 함께 삭제된다.
    quiz_attempts = relationship("QuizAttempt", back_populates="user", cascade="all, delete-orphan")
    # events: 이 유저가 등록한 개인 일정들. Subject의 수업 시간표와는 별개의 자유 일정이다.
    events = relationship("Event", back_populates="owner", cascade="all, delete-orphan")
    # character_state: 이 유저의 캐릭터 상태(코인/기분) 1건. uselist=False로 리스트가 아니라
    # 단일 객체(1:1)로 다룬다. 유저가 삭제되면 캐릭터 상태도 함께 삭제된다.
    character_state = relationship(
        "CharacterState", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    # notifications: 이 유저에게 온 알림들. 유저가 삭제되면 함께 삭제된다.
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


# Document: 사용자가 업로드한 PDF 한 건에 대한 메타정보를 저장하는 테이블.
# 실제 PDF 파일 자체는 서버 디스크(uploads 폴더)에 저장되고, 이 테이블은 그 파일의 "정보"만 담는다.
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    # user_id: 이 문서를 올린 유저의 id. ForeignKey("users.id")로 users 테이블의 id를 참조한다.
    # ondelete="CASCADE": DB 레벨에서, 참조하는 User 행이 삭제되면 이 Document 행도 자동 삭제되게 설정.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # filename: 사용자가 업로드한 원본 파일 이름 (화면에 보여줄 이름)
    filename = Column(String(255), nullable=False)
    # storage_path: 서버 디스크에 실제로 저장된 파일의 경로 (원본 filename과는 다를 수 있음,
    # routers/documents.py에서 uuid로 새 이름을 만들어 저장하기 때문)
    storage_path = Column(String(500), nullable=False)
    # num_pages: PDF의 총 페이지 수 (pdf_service.extract_text에서 계산)
    num_pages = Column(Integer, default=0)
    # num_chars: 추출된 전체 텍스트 글자 수 (통계/표시용)
    num_chars = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # owner: 이 문서를 올린 User 쪽으로의 역방향 관계 (User.documents와 짝을 이룸)
    owner = relationship("User", back_populates="documents")
    # chunks: 이 문서를 잘게 나눈 DocumentChunk들과의 관계.
    # order_by="DocumentChunk.chunk_index" → document.chunks로 가져올 때 항상 순서대로 정렬되게 함.
    # 문서가 삭제되면 딸린 청크들도 함께 삭제된다(cascade).
    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )


# DocumentChunk: 하나의 PDF 문서 텍스트를 여러 조각(청크)으로 잘라 저장하는 테이블.
# services/pdf_service.py의 split_into_chunks()로 나눈 결과가 여기에 한 줄씩 저장된다.
# 같은 내용이 ChromaDB에도 임베딩(벡터)과 함께 저장되는데, 이 테이블은 "원본 텍스트"의
# 정본(source of truth) 역할을 한다.
class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True)
    # document_id: 이 청크가 어느 문서에 속하는지. 문서가 삭제되면 청크도 함께 삭제된다(CASCADE).
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    # chunk_index: 문서 안에서 이 청크가 몇 번째 조각인지 (0부터 시작). ChromaDB에 저장할 때도
    # 이 값을 이용해 "{document_id}_{chunk_index}" 형태의 id를 만들어 1:1로 대응시킨다.
    chunk_index = Column(Integer, nullable=False)
    # content: 이 청크의 실제 텍스트 내용. 길이 제한이 없는 Text 타입 사용.
    content = Column(Text, nullable=False)

    document = relationship("Document", back_populates="chunks")


# ChatConversation: 하나의 "대화방"을 나타내는 테이블. 유저가 AI와 나누는 대화 세션 단위이며,
# 특정 문서를 기준으로 질문하는 대화방일 수도 있고(document_id 있음), 문서 없이 일반 대화를
# 나누는 대화방일 수도 있다(document_id가 NULL).
class ChatConversation(Base):
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True)
    # user_id: 이 대화방의 주인 유저. 유저가 삭제되면 대화방도 함께 삭제된다.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # document_id: 이 대화방이 특정 문서를 기준으로 한 것이라면 그 문서의 id, 아니면 NULL.
    # ondelete="SET NULL": 참조하던 문서가 삭제되면, 대화방 자체는 지우지 않고 이 값만 NULL로 바꿔서
    # (대화 기록은 남기되) 더 이상 존재하지 않는 문서를 참조하지 않게 만든다.
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    # title: 대화방 제목. 기본값은 "새 대화" (routers/chat.py에서 문서 이름 등으로 덮어쓸 수 있음)
    title = Column(String(255), default="새 대화")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="conversations")
    # document: 이 대화방이 참조하는 Document (없을 수도 있으므로 nullable). 별도 back_populates가
    # 없는 이유는 Document 쪽에서 "나를 참조하는 대화방 목록"을 따로 관리하지 않기 때문.
    document = relationship("Document")
    # messages: 이 대화방 안의 메시지들. created_at 순서대로 정렬되며, 대화방이 삭제되면
    # 메시지들도 함께 삭제된다.
    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


# ChatMessage: 대화방 안의 메시지 한 건(유저가 보낸 질문 하나, 또는 AI가 보낸 답변 하나)을 저장하는 테이블.
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    # conversation_id: 이 메시지가 속한 대화방. 대화방이 삭제되면 메시지도 함께 삭제된다.
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    # role: 이 메시지를 누가 보냈는지. "user"(유저가 보낸 질문) 또는 "assistant"(Claude가 보낸 답변).
    # Claude API에 대화 기록을 넘길 때도(services/claude_service.py) 이 role 값을 그대로 사용한다.
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("ChatConversation", back_populates="messages")


# Subject: 유저가 등록한 수강 과목 한 건. 시간표(요일/시작-종료 시각)와 성적 반영비율을 함께 담는다.
# routers/subjects.py의 과목 등록 API에서 사용되고, 과제 우선순위 로직(복습형 유저의 "복습 추천
# 시간" 계산)에서 오늘 요일에 해당하는 이 유저의 수업들을 조회하는 데도 사용된다.
class Subject(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    # user_id: 이 과목을 등록한 유저. 유저가 삭제되면 과목도 함께 삭제된다(CASCADE).
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # name: 과목명 (예: "자료구조")
    name = Column(String(100), nullable=False)
    # day_of_week: 이 수업이 열리는 요일. "월요일"~"일요일" 중 하나만 저장된다
    # (검증은 app/schemas.py의 SubjectCreate에서 Literal 타입으로 처리).
    day_of_week = Column(String(10), nullable=False)
    # start_time / end_time: 수업 시작/종료 시각 (시:분만 사용, 날짜 정보 없음)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    # midterm_ratio/final_ratio/assignment_ratio/attendance_ratio: 중간고사/기말고사/과제/출석이
    # 최종 성적에 반영되는 비율(%). 네 값의 합이 100이 되도록 프론트에서 안내하지만, DB 레벨에서
    # 강제하지는 않는다.
    midterm_ratio = Column(Integer, default=0, nullable=False)
    final_ratio = Column(Integer, default=0, nullable=False)
    assignment_ratio = Column(Integer, default=0, nullable=False)
    attendance_ratio = Column(Integer, default=0, nullable=False)
    # is_canceled_this_week: 이번 주에 한해 휴강인지 여부. routers/subjects.py의
    # PATCH /api/subjects/{id}/cancel-week로 토글된다. "이번 주"만 다루는 단순한 불리언이라,
    # 주가 바뀌면 다시 False로 되돌리는 처리는 이 프로젝트 범위 밖(스케줄러 등 별도 배치가 필요)이다.
    is_canceled_this_week = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="subjects")
    # assignments: 이 과목에 딸린 과제들. 과목이 삭제되면 과제도 함께 삭제된다.
    assignments = relationship(
        "Assignment",
        back_populates="subject",
        cascade="all, delete-orphan",
        order_by="Assignment.due_date",
    )


# Assignment: 특정 과목에 속한 과제 한 건. 과제 우선순위 조회(GET /api/assignments/priority)의
# 대상이 되는 핵심 테이블이다.
class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True)
    # subject_id: 이 과제가 속한 과목. 과목이 삭제되면 과제도 함께 삭제된다(CASCADE).
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    # due_date: 마감일. 시각 없이 날짜만 다루므로 DateTime이 아닌 Date 타입을 사용한다.
    due_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subject = relationship("Subject", back_populates="assignments")


# QuizSet: "퀴즈 생성" 버튼 한 번에 만들어지는 퀴즈 묶음 하나. 어떤 문서를 기반으로,
# 어떤 유형(객관식/주관식)의 문제 몇 개를 만들었는지, 그리고 다 풀었을 때의 점수를 담는다.
class QuizSet(Base):
    __tablename__ = "quiz_sets"

    id = Column(Integer, primary_key=True)
    # user_id: 이 퀴즈를 생성한 유저. 유저가 삭제되면 퀴즈 세트도 함께 삭제된다(CASCADE).
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # document_id: 어느 PDF를 기반으로 만든 퀴즈인지. chat_conversations.document_id와 같은 이유로
    # ondelete="SET NULL"을 쓴다 — 원본 문서가 삭제되더라도 퀴즈 기록(과 오답노트)은 그대로 남기고,
    # 더 이상 존재하지 않는 문서에 대한 참조만 끊는다.
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    # quiz_type: "객관식" 또는 "주관식" 둘 중 하나만 저장된다 (검증은 schemas.py의 Literal에서).
    quiz_type = Column(String(20), nullable=False)
    # total_questions: 이 세트에 몇 문제가 들어있는지. 기본값 10.
    total_questions = Column(Integer, default=10, nullable=False)
    # score: 채점 결과(정답률 %). 아직 결과 조회를 안 했으면 NULL(=None)이다.
    score = Column(Integer, nullable=True)
    # coins_awarded: 이 세트의 결과 조회 때 실제로 지급된 코인 수. reward_claimed와 짝을 이뤄서,
    # "이미 코인을 지급했는지"를 기억하는 용도다 — 이 값이 없으면 결과를 다시 조회할 때마다
    # (재도전으로 점수가 바뀌지 않아도) 코인이 매번 또 지급되는 버그가 생긴다.
    coins_awarded = Column(Integer, default=0, nullable=False)
    # reward_claimed: 이 세트에 대해 coin_service.calculate_quiz_reward를 이미 한 번
    # 실행했는지(코인 지급을 이미 처리했는지) 여부. True가 된 뒤에는 결과를 몇 번을 다시 조회해도
    # CharacterState.coin_balance를 더 이상 건드리지 않는다.
    reward_claimed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="quiz_sets")
    # document: 이 퀴즈가 참조하는 Document. chat_conversations.document와 마찬가지로 Document 쪽에
    # 역방향 관계를 두지 않는다 (Document가 "나를 참조하는 퀴즈 목록"을 관리할 필요가 없기 때문).
    document = relationship("Document")
    # questions: 이 세트에 속한 문제들. question_index 순서로 정렬되며, 세트가 삭제되면 함께 삭제된다.
    questions = relationship(
        "QuizQuestion",
        back_populates="quiz_set",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.question_index",
    )


# QuizQuestion: 퀴즈 세트 안의 문제 한 건. Claude가 생성한 문제/보기/정답/해설을 그대로 저장해두고,
# 이후 채점·오답노트 조회 때 매번 Claude를 다시 부르지 않고 이 저장된 정답과 비교한다.
class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(Integer, primary_key=True)
    # quiz_set_id: 이 문제가 속한 세트. 세트가 삭제되면 문제도 함께 삭제된다(CASCADE).
    quiz_set_id = Column(Integer, ForeignKey("quiz_sets.id", ondelete="CASCADE"), nullable=False)
    # question_index: 세트 안에서 몇 번째 문제인지 (1~total_questions).
    question_index = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    # options: 객관식일 때만 4지선다 보기 목록(예: ["2006","2007","2005","1592"])을 JSON으로 저장.
    # 주관식 문제는 보기가 없으므로 NULL이다.
    options = Column(JSON, nullable=True)
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)

    quiz_set = relationship("QuizSet", back_populates="questions")
    # attempts: 이 문제를 푼 기록들(최초 풀이 + 재도전 전부). 문제가 삭제되면 함께 삭제된다.
    attempts = relationship(
        "QuizAttempt",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuizAttempt.answered_at",
    )


# QuizAttempt: 유저가 문제 하나를 실제로 푼 기록 한 건. 제출(submit)이든 재도전(retry)이든
# 매번 새 행으로 쌓이기 때문에, 같은 문제를 여러 번 풀면 여러 행이 남는다 — "가장 최근 기록"을
# 가려내는 로직(결과 채점, 오답노트 조회)은 routers/quiz.py에서 처리한다.
class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True)
    # quiz_question_id: 어떤 문제를 풀었는지. 문제가 삭제되면 풀이 기록도 함께 삭제된다.
    quiz_question_id = Column(Integer, ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False)
    # user_id: 누가 풀었는지. quiz_question → quiz_set → user_id로도 알 수 있지만, 오답노트 조회에서
    # "이 유저의 모든 오답"을 바로 필터링할 수 있도록 여기에도 중복해서 저장해둔다.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_answer = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    answered_at = Column(DateTime(timezone=True), server_default=func.now())

    question = relationship("QuizQuestion", back_populates="attempts")
    user = relationship("User", back_populates="quiz_attempts")


# Event: 유저가 직접 등록하는 개인 일정 한 건. Subject(수강 과목의 고정 수업 시간표)와는
# 별개의 테이블이다 — 약속, 알바, 동아리 모임처럼 학기 내내 반복되지 않는 일정을 담는다.
# services/priority_service.py의 find_free_time_slots가 Subject와 Event를 함께 조회해서
# "이 날 실제로 비어있는 시간"을 계산할 때 사용한다.
class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    # user_id: 이 일정의 주인. 유저가 삭제되면 일정도 함께 삭제된다(CASCADE).
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    # date: 이 일정이 있는 날짜. Subject는 "매주 반복되는 요일"을 쓰지만, 개인 일정은
    # 특정 하루에만 있으므로 요일이 아닌 날짜(Date)를 그대로 저장한다.
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    # memo: 일정에 대한 추가 메모. 없어도 되므로 nullable.
    memo = Column(Text, nullable=True)

    owner = relationship("User", back_populates="events")


# CharacterState: 유저 한 명당 정확히 1건 존재하는 "옹이" 캐릭터의 상태.
# 퀴즈를 잘 풀면 코인이 쌓이고 기분이 좋아지고(happy), 할 일을 미루면 기분이 나빠진다(sad).
# services/coin_service.py가 이 테이블을 갱신하는 유일한 곳이다.
class CharacterState(Base):
    __tablename__ = "character_states"

    id = Column(Integer, primary_key=True)
    # user_id: unique=True로 걸어서 유저 한 명당 이 테이블에 딱 한 행만 존재하도록 DB 레벨에서 강제한다
    # (User.character_state 쪽에서 uselist=False로 다루는 것과 짝을 이루는 1:1 관계).
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    coin_balance = Column(Integer, default=0, nullable=False)
    # mood: "happy"/"sad"/"neutral" 중 하나만 저장된다 (검증은 schemas.py의 Literal에서).
    mood = Column(String(20), default="neutral", nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="character_state")


# Notification: 유저에게 보낼(또는 보낸) 알림 한 건. "복습할 시간이에요" 같은 리마인더나,
# 과제 마감 임박 알림처럼 특정 Assignment/QuizSet과 연결된 알림을 담는다.
class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    message = Column(Text, nullable=False)
    # related_type: "assignment", "review_quiz" 등 이 알림이 무엇에 대한 것인지 나타내는 표시.
    # day_of_week/learning_style과 달리 앞으로 새 알림 유형이 계속 추가될 수 있는 개방형 값이라,
    # schemas.py에서도 Literal로 제한하지 않고 일반 문자열로 둔다.
    related_type = Column(String(30), nullable=False)
    # related_id: 관련된 Assignment나 QuizSet 등의 id. 어떤 테이블을 참조하는지는 related_type으로
    # 구분해야 해서 외래키(ForeignKey)로 걸지 않고 일반 정수로 둔다.
    related_id = Column(Integer, nullable=True)
    # is_completed: 유저가 "확인/완료" 체크를 했는지. 체크 전까지는 계속 미완료 알림 목록에 남는다.
    is_completed = Column(Boolean, default=False, nullable=False)
    notify_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")
