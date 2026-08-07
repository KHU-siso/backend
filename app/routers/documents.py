# =============================================================================
# 이 파일의 역할 (routers/documents.py)
# -----------------------------------------------------------------------------
# PDF 문서 업로드/조회/삭제를 담당하는 API 라우터입니다.
#
#   - POST   /api/documents/upload            : PDF 업로드 (저장 → 텍스트 추출 → 청크 분할 →
#                                                 PostgreSQL 저장 → ChromaDB 임베딩 저장까지 한 번에 처리)
#   - GET    /api/documents                    : 내가 업로드한 문서 목록 조회
#   - GET    /api/documents/{document_id}/chunks : 특정 문서의 청크(조각) 목록 조회
#   - DELETE /api/documents/{document_id}      : 문서 삭제 (원본 파일 + DB 행 + ChromaDB 벡터까지 정리)
#
# 실제 PDF 처리 로직(텍스트 추출, 분할, 임베딩 저장)은 services/pdf_service.py에 있고,
# 이 파일은 "요청을 받아 그 함수들을 순서대로 호출하고, 결과를 DB에 반영"하는 역할을 합니다.
# =============================================================================

# 파이썬 표준 라이브러리
import shutil  # 업로드된 파일 스트림을 디스크 파일로 복사할 때 사용
import uuid    # 저장할 파일의 이름이 겹치지 않도록 무작위 고유 문자열을 만들 때 사용
from pathlib import Path  # 파일 경로를 다루는 타입

# FastAPI에서 가져옴
# - APIRouter, Depends: 라우터 등록과 의존성 주입
# - HTTPException, status: 에러 응답
# - UploadFile: 업로드된 파일(멀티파트 폼 데이터)을 나타내는 FastAPI 전용 타입.
#   file.filename(원본 파일명), file.content_type(MIME 타입), file.file(실제 파일 스트림) 등을 제공한다.
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/config.py: 업로드 파일을 저장할 폴더 경로(upload_dir) 등 환경설정
from app.config import settings
# app/deps.py: 로그인 유저 조회, DB 세션 생성
from app.deps import get_current_user, get_db
# app/models.py: Document(문서 메타정보), DocumentChunk(문서 조각), User ORM 모델
from app.models import Document, DocumentChunk, User
# app/schemas.py: 응답 형태 정의
from app.schemas import DocumentChunkOut, DocumentOut
# services/pdf_service.py: PDF 텍스트 추출, 청크 분할, ChromaDB 임베딩 저장/삭제 함수들
from app.services.pdf_service import (
    delete_document_embeddings,
    extract_text,
    split_into_chunks,
    store_chunk_embeddings,
)

# 이 라우터의 모든 엔드포인트는 "/api/documents"로 시작한다.
router = APIRouter(prefix="/api/documents", tags=["documents"])


# upload_document: PDF 파일 하나를 업로드받아 "검색 가능한 상태"까지 만드는 함수.
# 어디서 온 기능인가:
#   file: UploadFile → FastAPI가 요청의 멀티파트 폼 데이터에서 업로드된 파일을 자동으로 파싱해 넣어줌
#   current_user, db → app/deps.py의 의존성 주입
# 무슨 기능을 하나 (파이프라인 5단계):
#   1) 파일 형식이 PDF인지 확인
#   2) 서버 디스크의 유저별 폴더에 원본 파일 저장
#   3) pypdf로 텍스트 추출 + 텍스트를 여러 청크로 분할
#   4) PostgreSQL에 Document(메타정보)와 DocumentChunk(조각들) 행 저장
#   5) 그 청크들을 임베딩해서 ChromaDB에도 저장 (나중에 chat.py에서 의미 검색에 사용)
# 언제 쓰이나: 프론트엔드의 "PDF 업로드" 화면에서 파일을 선택하고 업로드 버튼을 눌렀을 때 호출된다.
@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # file.content_type: 브라우저/클라이언트가 보내준 파일의 MIME 타입.
    # PDF가 아니면 처리할 이유가 없으므로 400 Bad Request로 즉시 거절한다.
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    # Path(settings.upload_dir) / str(current_user.id):
    #   예) uploads/3  → 유저별로 폴더를 나눠서 저장한다 (다른 유저 파일과 섞이지 않도록).
    user_dir = Path(settings.upload_dir) / str(current_user.id)
    # mkdir(parents=True, exist_ok=True): 폴더가 없으면 상위 폴더까지 포함해서 만들고,
    # 이미 있으면 에러 없이 그냥 넘어간다.
    user_dir.mkdir(parents=True, exist_ok=True)
    # uuid.uuid4().hex: 무작위 고유 문자열을 만들어 파일명으로 사용한다.
    # 원본 파일명을 그대로 쓰지 않는 이유는, 같은 이름의 파일을 여러 번 올려도 서로 덮어쓰지 않게 하기 위함.
    stored_path = user_dir / f"{uuid.uuid4().hex}.pdf"

    # 업로드된 파일 스트림(file.file)을 서버 디스크의 stored_path 경로에 실제로 저장한다.
    # "wb" = write binary(바이너리 쓰기 모드). shutil.copyfileobj로 스트림을 그대로 복사한다.
    with stored_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    # services/pdf_service.py의 함수 호출
    # extract_text: 방금 저장한 PDF 파일에서 전체 텍스트와 페이지 수를 뽑아낸다.
    text, num_pages = extract_text(stored_path)
    # split_into_chunks: 뽑아낸 텍스트를 1000자 단위(150자 겹침)의 작은 조각들로 나눈다.
    chunks = split_into_chunks(text)

    # Document ORM 객체를 만든다 (아직 DB에 저장 전, 메모리 상태).
    document = Document(
        user_id=current_user.id,
        # file.filename or stored_path.name: 원본 파일명이 있으면 그걸, 없으면(드묾) 저장된
        # 파일명을 대신 사용한다.
        filename=file.filename or stored_path.name,
        storage_path=str(stored_path),
        num_pages=num_pages,
        num_chars=len(text),
    )
    db.add(document)  # 저장 대기 목록에 추가
    # db.flush(): commit 전이지만, DB에 SQL을 미리 실행시켜서 document.id 같은
    # DB가 자동으로 채워주는 값을 지금 시점에 미리 받아온다. 아래에서 document.id가
    # DocumentChunk를 만들 때 바로 필요하기 때문에 flush로 먼저 확정시킨다.
    db.flush()

    # 나눠진 청크들을 하나씩 DocumentChunk 행으로 만들어 저장 대기 목록에 추가한다.
    # enumerate(chunks): (0, 첫번째청크), (1, 두번째청크)... 형태로 인덱스와 값을 함께 돌려준다.
    for index, chunk in enumerate(chunks):
        db.add(DocumentChunk(document_id=document.id, chunk_index=index, content=chunk))

    db.commit()        # Document + 모든 DocumentChunk를 한 번에 실제로 PostgreSQL에 반영
    db.refresh(document)  # document 객체에 DB가 채운 최신 값(created_at 등)을 다시 읽어옴

    # PostgreSQL 커밋이 끝난 뒤 임베딩을 계산해 ChromaDB에 저장한다. document.id가
    # 확정된 다음이어야 컬렉션의 id/metadata가 PostgreSQL 쪽 청크와 정확히 대응된다.
    store_chunk_embeddings(document.id, chunks)

    # response_model=DocumentOut 설정 덕분에, 이 document 객체는 자동으로 DocumentOut
    # 형태(필요한 필드만)로 변환되어 응답된다.
    return document


# list_documents: 현재 로그인한 유저가 업로드한 문서 목록을 조회하는 함수.
# 언제 쓰이나: 프론트엔드의 "내 문서 목록" 화면, 또는 대화방을 만들 때 "어떤 문서로 대화할지"
# 선택하는 드롭다운 등에서 호출된다.
@router.get("", response_model=list[DocumentOut])
def list_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 이 유저 소유의 문서만 최신순으로 전부 조회해서 리스트로 반환한다.
    return (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.created_at.desc())
        .all()
    )


# list_chunks: 특정 문서의 청크(조각) 목록을 조회하는 함수. 주로 디버깅/확인용 API.
# 어디서 온 기능인가: document_id: int → URL 경로의 "{document_id}" 부분이 자동으로 정수로 파싱되어 들어옴.
# 언제 쓰이나: "이 PDF가 실제로 어떻게 나뉘어 저장됐는지" 확인하고 싶을 때 호출된다.
@router.get("/{document_id}/chunks", response_model=list[DocumentChunkOut])
def list_chunks(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # _get_owned_document: 아래에 정의된 헬퍼 함수. 이 문서가 실제로 존재하고,
    # 요청한 유저의 소유가 맞는지 확인한다 (다른 사람 문서를 볼 수 없도록).
    document = _get_owned_document(db, document_id, current_user.id)
    # document.chunks: app/models.py에서 정의한 relationship 덕분에, SQL을 직접 안 짜도
    # 이 문서에 딸린 DocumentChunk 목록을 chunk_index 순서대로 바로 꺼내 쓸 수 있다.
    return document.chunks


# delete_document: 문서 하나를 완전히 삭제하는 함수.
# 무슨 기능을 하나: 삭제는 세 군데에서 동시에 일어나야 데이터가 일관된다.
#   1) 서버 디스크의 실제 PDF 파일 삭제
#   2) ChromaDB에 저장된 이 문서의 벡터들 삭제
#   3) PostgreSQL의 Document 행 삭제 (cascade 설정 덕분에 딸린 DocumentChunk도 자동 삭제됨)
# 언제 쓰이나: 프론트엔드에서 문서 목록의 "삭제" 버튼을 눌렀을 때 호출된다.
@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = _get_owned_document(db, document_id, current_user.id)
    # Path(document.storage_path).unlink(missing_ok=True):
    #   저장된 실제 PDF 파일을 디스크에서 지운다. missing_ok=True → 파일이 이미 없어도
    #   에러 없이 넘어간다 (예: 수동으로 이미 지워진 경우 대비).
    Path(document.storage_path).unlink(missing_ok=True)
    # ChromaDB에 남아있는 이 문서의 벡터들을 먼저 정리한다.
    delete_document_embeddings(document.id)
    db.delete(document)  # PostgreSQL에서 이 Document 행을 삭제 대기 상태로 표시
    db.commit()            # 실제로 DELETE 쿼리를 실행해서 확정 (딸린 청크들도 cascade로 함께 삭제됨)


# _get_owned_document: "이 document_id가 실제로 존재하고, 요청한 유저의 것이 맞는지" 확인하는
# 내부 헬퍼(도우미) 함수. 여러 엔드포인트(chunks 조회, 삭제)에서 중복되는 검증 로직을 한 곳에 모았다.
# 함수 이름 앞의 밑줄(_)은 "이 파일 안에서만 쓰는 내부용 함수"라는 파이썬 관례적 표시다.
def _get_owned_document(db: Session, document_id: int, user_id: int) -> Document:
    # db.get(Document, document_id): 기본키로 한 건 조회 (없으면 None)
    document = db.get(Document, document_id)
    # 문서가 아예 없거나, 있어도 소유자가 다르면 "찾을 수 없음"으로 통일해서 응답한다.
    # (소유자가 다른 경우에도 403 대신 404를 쓰는 이유는, 다른 사람의 문서 id가 "존재는 하지만
    #  내 것이 아니라 접근 불가"라는 정보조차 노출하지 않기 위함이다.)
    if document is None or document.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document
