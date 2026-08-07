# =============================================================================
# 이 파일의 역할 (routers/chat.py)
# -----------------------------------------------------------------------------
# AI와 대화하는 "챗봇" 기능을 담당하는 API 라우터입니다. RAG(검색 증강 생성) 흐름의
# 마지막 단계로, 문서 업로드 때 만들어둔 ChromaDB 벡터를 실제로 "검색"해서 Claude에게
# 참고자료로 넘겨주는 역할을 합니다.
#
#   - POST /api/chat/conversations                        : 새 대화방 생성
#   - GET  /api/chat/conversations                          : 내 대화방 목록 조회
#   - GET  /api/chat/conversations/{id}/messages             : 특정 대화방의 메시지 기록 조회
#   - POST /api/chat/conversations/{id}/messages             : 새 질문 보내고 AI 답변 받기
#
# 마지막 엔드포인트가 이 파일의 핵심입니다. 문서 기반 대화방이면
#   질문 임베딩 → ChromaDB에서 유사 청크 검색 → Claude 호출 → 답변 저장
# 순서로 동작합니다.
# =============================================================================

# FastAPI에서 가져옴 — 라우터 등록, 의존성 주입, 에러 응답
from fastapi import APIRouter, Depends, HTTPException, status
# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/deps.py: 로그인 유저 조회, DB 세션 생성
from app.deps import get_current_user, get_db
# app/models.py: 대화방/메시지/문서/유저 ORM 모델
from app.models import ChatConversation, ChatMessage, Document, User
# app/schemas.py: 요청/응답 형태 정의
from app.schemas import ConversationCreate, ConversationOut, MessageCreate, MessageOut
# services/claude_service.py: 실제 Claude API 호출 함수
from app.services.claude_service import ask
# services/embedding_service.py: 텍스트를 벡터로 변환하는 함수 (질문을 검색용 벡터로 바꿀 때 사용)
from app.services.embedding_service import embed_text
# services/pdf_service.py: ChromaDB 컬렉션을 가져오는 함수 (업로드 때 저장한 그 컬렉션과 동일)
from app.services.pdf_service import get_chunk_collection

# 이 라우터의 모든 엔드포인트는 "/api/chat"으로 시작한다.
router = APIRouter(prefix="/api/chat", tags=["chat"])

# 질문 하나당 ChromaDB에서 몇 개의 관련 청크를 가져올지 정하는 상수.
# 너무 적으면 답변에 필요한 정보가 빠질 수 있고, 너무 많으면 관련 없는 내용까지
# 프롬프트에 섞여 들어가 오히려 답변 품질이 떨어질 수 있어 5개로 절충했다.
TOP_K_CHUNKS = 5


# create_conversation: 새 대화방을 만드는 함수.
# 어디서 온 기능인가: payload: ConversationCreate → 요청 body를 app/schemas.py 스펙대로 검증해서 받음.
# 무슨 기능을 하나: document_id가 왔다면 그 문서가 실제로 존재하고 내 것이 맞는지 확인한 뒤,
#   문서 기준 대화방 또는 일반 대화방을 하나 만든다.
# 언제 쓰이나: 프론트엔드에서 "새 대화 시작" 버튼을 누르거나, 특정 문서를 열어 "이 문서로 질문하기"를
#   선택했을 때 호출된다.
@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = None
    # payload.document_id가 None이 아니면(=문서를 지정한 경우), 그 문서가 실제로 있고
    # 요청한 유저의 소유가 맞는지 확인한다.
    if payload.document_id is not None:
        document = db.get(Document, payload.document_id)
        if document is None or document.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    conversation = ChatConversation(
        user_id=current_user.id,
        document_id=payload.document_id,
        # payload.title이 있으면 그걸 쓰고, 없으면 document가 있는 경우 파일명을,
        # document도 없으면 "새 대화"를 기본 제목으로 사용한다.
        title=payload.title or (document.filename if document else "새 대화"),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


# list_conversations: 현재 유저의 대화방 목록을 최신순으로 조회하는 함수.
# 언제 쓰이나: 프론트엔드의 "대화 목록" 사이드바를 그릴 때 호출된다.
@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(ChatConversation)
        .filter(ChatConversation.user_id == current_user.id)
        .order_by(ChatConversation.created_at.desc())
        .all()
    )


# list_messages: 특정 대화방의 전체 메시지 기록을 조회하는 함수.
# 언제 쓰이나: 유저가 대화 목록에서 대화방 하나를 클릭해 들어갔을 때, 이전 대화 내용을
# 화면에 그리기 위해 호출된다.
@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # _get_owned_conversation: 이 대화방이 존재하고 내 것이 맞는지 확인하는 헬퍼 함수 (아래 정의)
    conversation = _get_owned_conversation(db, conversation_id, current_user.id)
    # conversation.messages: app/models.py의 relationship 덕분에 시간순으로 정렬된
    # ChatMessage 목록을 바로 꺼내 쓸 수 있다.
    return conversation.messages


# send_message: 새 질문을 보내고 AI 답변을 받아오는 이 파일의 핵심 함수.
# 어디서 온 기능인가: payload: MessageCreate로 유저가 보낸 질문 텍스트를 받는다.
# 무슨 기능을 하나 (순서대로):
#   1) 이 대화방의 지금까지 메시지 기록을 Claude에 넘길 형태(role/content)로 변환
#   2) 이 대화방이 특정 문서를 기준으로 한다면, 질문과 관련된 청크를 ChromaDB에서 검색해 컨텍스트로 준비
#   3) services/claude_service.py의 ask()를 호출해 실제 AI 답변을 받음
#   4) 유저 질문 + AI 답변을 각각 ChatMessage로 DB에 저장
# 언제 쓰이나: 프론트엔드의 채팅창에서 유저가 메시지를 입력하고 전송했을 때 호출된다.
@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    conversation_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _get_owned_conversation(db, conversation_id, current_user.id)

    # 이 대화방의 기존 메시지들을 Claude API가 이해하는 형태
    # ({"role": "user"/"assistant", "content": "..."})의 리스트로 변환한다.
    # 이렇게 대화 기록을 함께 보내야 Claude가 "이전에 무슨 얘기를 했는지" 기억하고 답할 수 있다.
    history = [{"role": m.role, "content": m.content} for m in conversation.messages]

    context_text = None
    # 이 대화방이 특정 문서(document_id)를 기준으로 한다면, 그 문서 안에서 질문과 가장
    # 관련 있는 내용을 찾아 context_text에 담는다. 문서 없는 일반 대화방이면 그냥 None으로 둔다.
    if conversation.document_id is not None:
        context_text = _build_context(payload.content, conversation.document_id)

    # ask(): services/claude_service.py 함수. 질문 + 대화 기록 + (있다면) 문서 컨텍스트를
    # Claude API로 보내고, 텍스트 답변을 받아온다.
    answer = ask(payload.content, history, context_text)

    # 유저가 보낸 질문과 AI의 답변을 각각 별도의 ChatMessage 행으로 만든다.
    user_message = ChatMessage(conversation_id=conversation.id, role="user", content=payload.content)
    assistant_message = ChatMessage(conversation_id=conversation.id, role="assistant", content=answer)
    # db.add_all([...]): 여러 객체를 한 번에 저장 대기 목록에 추가 (db.add()를 두 번 부르는 것과 같은 효과)
    db.add_all([user_message, assistant_message])
    db.commit()
    db.refresh(assistant_message)  # assistant_message에 DB가 채운 id, created_at 등을 다시 읽어옴
    # 프론트엔드는 이 응답(방금 만들어진 AI 답변 메시지)을 받아서 화면에 바로 표시하면 된다.
    return assistant_message


# _get_owned_conversation: "이 conversation_id가 실제로 존재하고, 요청한 유저의 것이 맞는지"
# 확인하는 내부 헬퍼 함수. 여러 엔드포인트에서 반복되는 검증 로직을 한 곳에 모았다.
def _get_owned_conversation(db: Session, conversation_id: int, user_id: int) -> ChatConversation:
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


# _build_context: 질문과 의미상 가장 관련 있는 문서 청크들을 ChromaDB에서 찾아
# 하나의 문자열로 합쳐주는 내부 함수. 이 프로젝트의 "RAG(검색 증강 생성)" 핵심 로직이다.
# 어디서 온 기능인가:
#   embed_text(services/embedding_service.py) → 질문 문장을 검색용 벡터로 변환
#   collection.query(...)(chromadb 라이브러리) → 저장된 벡터들 중 가장 가까운 것들을 검색
# 무슨 기능을 하나: 질문을 임베딩해서 ChromaDB에서 해당 문서 안의 가장 관련 있는 청크
#   TOP_K_CHUNKS개만 가져온다. 문서 전체를 순서대로 넣던 이전 방식과 달리,
#   문서가 길어도 질문과 무관한 청크가 컨텍스트를 차지하지 않는다.
# 언제 쓰이나: send_message 안에서, 대화방이 특정 문서를 기준으로 할 때만 호출된다.
def _build_context(question: str, document_id: int) -> str:
    """질문을 임베딩해서 ChromaDB에서 해당 문서 안의 가장 관련 있는 청크
    TOP_K_CHUNKS개만 가져온다. 문서 전체를 순서대로 넣던 이전 방식과 달리,
    문서가 길어도 질문과 무관한 청크가 컨텍스트를 차지하지 않는다."""
    # 문서 업로드 때 저장했던 것과 동일한 ChromaDB 컬렉션 객체를 가져온다.
    collection = get_chunk_collection()
    # 질문 문장을 벡터(숫자 배열)로 변환한다. 이 벡터와 가까운 청크 벡터를 찾는 것이 검색의 핵심이다.
    query_embedding = embed_text(question)

    # collection.query(...): ChromaDB에 "이 벡터와 가장 비슷한 것 상위 N개를 찾아달라"고 요청한다.
    #   query_embeddings=[query_embedding]: 검색 기준이 되는 질문 벡터 (여러 개를 한 번에 검색할 수도
    #     있는 구조라 리스트로 감싸지만, 여기서는 질문 하나이므로 원소 1개짜리 리스트를 넘긴다)
    #   n_results=TOP_K_CHUNKS: 상위 몇 개까지 가져올지 (5개)
    #   where={"document_id": document_id}: 반드시 이 문서에 속한 청크들 중에서만 검색하도록 하는
    #     필터. 이 필터가 없으면 다른 문서/다른 유저의 청크까지 검색 대상에 섞여버린다.
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=TOP_K_CHUNKS,
        where={"document_id": document_id},
    )

    # results는 {"documents": [[...]], "distances": [[...]], ...} 같은 형태로,
    # 검색 기준(질문) 하나당 결과 리스트 하나씩 바깥 리스트에 담겨서 온다.
    # 질문을 하나만 보냈으므로 바깥 리스트의 첫 번째 원소([0])가 우리가 원하는 결과다.
    # (results.get("documents") or [[]])는 혹시 "documents" 키 자체가 없는 경우를 대비한 안전장치.
    matched_chunks = (results.get("documents") or [[]])[0]
    # 찾은 청크들을 빈 줄로 이어붙여 하나의 문자열로 만들고, 양 끝 공백을 정리해서 반환한다.
    # 이 문자열이 services/claude_service.py의 ask()에서 <context> 태그로 감싸져 Claude에게 전달된다.
    return "\n\n".join(matched_chunks).strip()
