# =============================================================================
# 이 파일의 역할 (models.py)
# -----------------------------------------------------------------------------
# PostgreSQL에 실제로 만들어질 "테이블 구조"를 파이썬 클래스로 정의하는 파일입니다.
# SQLAlchemy ORM(Object-Relational Mapping)을 사용하면, 여기 정의한 클래스 하나가
# DB의 테이블 하나에 대응되고, 클래스의 인스턴스(객체) 하나가 그 테이블의 행(row) 하나에
# 대응됩니다. 즉 SQL문을 직접 안 써도 파이썬 객체를 다루듯 DB를 조작할 수 있게 해줍니다.
#
# 이 파일에는 5개의 테이블이 정의되어 있고, 서로 다음과 같이 연결되어 있습니다.
#
#   User(유저) 1 ─── N Document(업로드한 PDF 문서)
#   User(유저) 1 ─── N ChatConversation(대화방)
#   Document(문서) 1 ─── N DocumentChunk(문서를 잘게 나눈 조각들)
#   ChatConversation(대화방) 1 ─── N ChatMessage(대화방 안의 메시지들)
#   ChatConversation(대화방) N ─── 1 Document(대화방이 참조하는 문서, 없을 수도 있음)
#
# 실제 테이블 생성은 app/main.py의 Base.metadata.create_all(...)에서 이 파일의
# 클래스 정의를 읽어 자동으로 처리합니다.
# =============================================================================

# SQLAlchemy 라이브러리에서 가져옴 — 테이블의 "컬럼(열)"을 정의할 때 쓰는 도구들
# - Column: 하나의 컬럼(열)을 정의하는 클래스
# - DateTime: 날짜+시간을 저장하는 컬럼 타입
# - ForeignKey: 다른 테이블의 id를 참조하는 "외래키" 컬럼을 만들 때 사용
# - Integer: 정수를 저장하는 컬럼 타입
# - String: 길이 제한이 있는 문자열을 저장하는 컬럼 타입 (예: String(255))
# - Text: 길이 제한이 없는 긴 문자열을 저장하는 컬럼 타입 (PDF 청크 내용처럼 긴 글에 사용)
# - func: SQL 함수(예: func.now() = 현재 시각)를 파이썬에서 쓸 수 있게 해주는 도구
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
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
    # name: 화면에 표시할 사용자 이름
    name = Column(String(100), nullable=False)
    # created_at: 가입 시각. server_default=func.now() → 행이 INSERT될 때 DB가 자동으로
    # 현재 시각을 채워준다 (파이썬 코드에서 따로 값을 넣지 않아도 됨).
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # documents: 이 유저가 올린 Document들과의 관계. back_populates="owner"는
    # Document 쪽의 owner 필드와 서로 짝을 이루도록 연결해준다는 뜻.
    # cascade="all, delete-orphan": 이 유저가 삭제되면, 이 유저 소유의 Document들도 함께 삭제된다.
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    # conversations: 이 유저의 대화방들과의 관계. 유저가 삭제되면 대화방들도 함께 삭제된다.
    conversations = relationship("ChatConversation", back_populates="owner", cascade="all, delete-orphan")


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
