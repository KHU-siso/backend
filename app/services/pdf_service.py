# =============================================================================
# 이 파일의 역할 (services/pdf_service.py)
# -----------------------------------------------------------------------------
# PDF 파일을 다루는 데 필요한 모든 작업을 모아둔 파일입니다. 크게 3단계로 나뉩니다.
#
#   1) PDF → 텍스트 추출          (extract_text)
#   2) 긴 텍스트 → 작은 조각(청크)들로 분할 (split_into_chunks)
#   3) 청크들을 임베딩해서 ChromaDB(벡터 검색 DB)에 저장/삭제 (store_chunk_embeddings, delete_document_embeddings)
#
# routers/documents.py(PDF 업로드 API)가 이 파일의 함수들을 순서대로 호출해서
# "업로드된 PDF → 검색 가능한 상태"로 만드는 전체 파이프라인을 완성합니다.
# 실제 벡터 변환(숫자로 바꾸는 부분)은 services/embedding_service.py에 위임하고,
# 이 파일은 "PDF 처리 + ChromaDB 저장소 관리"에 집중합니다.
# =============================================================================

# 파이썬 표준 라이브러리 — 파일 경로를 다루는 타입 (문자열보다 안전하게 경로를 다룰 수 있게 해줌)
from pathlib import Path

# chromadb: 벡터(임베딩)를 저장하고, "이 벡터와 가장 비슷한 벡터들"을 빠르게 검색할 수 있게 해주는
# 오픈소스 벡터 데이터베이스 라이브러리. RAG(검색 증강 생성)의 핵심 저장소 역할을 한다.
import chromadb
# langchain_text_splitters 라이브러리에서 가져옴
# - RecursiveCharacterTextSplitter: 긴 텍스트를 정해진 글자 수 단위로 잘라주는 도구.
#   문단/문장 경계를 최대한 존중하면서 자르려고 시도하기 때문에 단순히 N글자마다 뚝뚝
#   자르는 것보다 의미가 덜 끊긴다.
from langchain_text_splitters import RecursiveCharacterTextSplitter
# pypdf 라이브러리 — PDF 파일 형식을 읽고 다루는 도구
# - PdfReader: PDF 파일을 열어서 페이지별 텍스트 등을 읽어올 수 있게 해주는 클래스
from pypdf import PdfReader

# app/config.py의 settings에서 ChromaDB 저장 경로(chroma_dir)를 가져온다.
from app.config import settings
# 방금 만든 embedding_service.py의 embed_texts 함수 — 텍스트 리스트를 벡터 리스트로 변환
from app.services.embedding_service import embed_texts

# 프로세스당 하나의 영구(persistent) 클라이언트/컬렉션만 열어 재사용한다.
# chromadb.PersistentClient(path=...):
#   settings.chroma_dir 경로(기본값 "chroma_db" 폴더)에 데이터를 실제 디스크 파일로 저장하는
#   ChromaDB 클라이언트를 만든다. "Persistent"(영구적)라는 이름처럼, 서버를 껐다 켜도
#   저장해둔 벡터 데이터가 사라지지 않는다.
# 이 두 줄은 파일이 처음 import될 때 딱 한 번만 실행되어, 이후 모든 함수가 같은 클라이언트를 재사용한다.
_chroma_client = chromadb.PersistentClient(path=settings.chroma_dir)
# get_or_create_collection: "document_chunks"라는 이름의 컬렉션(=SQL의 테이블과 비슷한 개념)이
# 이미 있으면 그걸 가져오고, 없으면 새로 만든다.
# metadata={"hnsw:space": "cosine"}: 벡터끼리의 "거리"를 계산하는 방식을 코사인 유사도로 지정.
# embedding_service.py에서 normalize_embeddings=True로 정규화한 벡터를 쓰는 것과 짝을 이루는 설정이다.
_chunk_collection = _chroma_client.get_or_create_collection(
    name="document_chunks",
    metadata={"hnsw:space": "cosine"},
)


# get_chunk_collection: 위에서 만든 컬렉션 객체를 다른 파일에서도 쓸 수 있게 내보내는 함수.
# 어디서 온 기능인가: 별도 라이브러리 기능은 없고, 모듈 최상단의 _chunk_collection 변수를 그대로 반환한다.
# 무슨 기능을 하나: 컬렉션을 새로 만들지 않고, 이미 만들어진 하나의 컬렉션 인스턴스를 공유하게 해준다.
# 언제 쓰이나: routers/chat.py에서 유저 질문과 유사한 청크를 검색(query)할 때 이 함수로
# 컬렉션을 가져와서 사용한다.
def get_chunk_collection():
    """chat.py 등 다른 모듈에서 같은 컬렉션에 대해 검색(query)할 때 사용."""
    return _chunk_collection


# extract_text: PDF 파일에서 전체 텍스트와 페이지 수를 뽑아내는 함수.
# 어디서 온 기능인가: pypdf 라이브러리의 PdfReader와 page.extract_text()를 사용한다.
# 무슨 기능을 하나: PDF의 모든 페이지를 순서대로 돌면서 각 페이지의 텍스트를 추출하고,
#   페이지 사이를 빈 줄 두 개("\n\n")로 이어 붙여 하나의 긴 문자열로 합친다.
# 언제 쓰이나: routers/documents.py의 업로드 API에서, PDF 파일을 디스크에 저장한 직후
#   그 파일 경로를 넘겨받아 호출된다.
def extract_text(pdf_path: Path) -> tuple[str, int]:
    # PdfReader(str(pdf_path)): pdf_path(Path 객체)를 문자열로 바꿔 PDF 파일을 연다.
    reader = PdfReader(str(pdf_path))
    # 각 페이지(page)마다 extract_text()로 텍스트를 뽑는다.
    # "or \"\"" 부분: 이미지로만 이루어진 페이지 등 텍스트 추출이 안 되는 경우 None이 반환될 수 있는데,
    # 그럴 때 빈 문자열로 대체해서 이후 join 과정에서 에러가 나지 않게 한다.
    pages = [page.extract_text() or "" for page in reader.pages]
    # 모든 페이지 텍스트를 빈 줄로 구분해서 하나로 합친 문자열과, 총 페이지 수를 함께 반환한다.
    return "\n\n".join(pages), len(reader.pages)


# split_into_chunks: 긴 텍스트 하나를 여러 개의 작은 텍스트 조각(청크)으로 나누는 함수.
# 어디서 온 기능인가: langchain_text_splitters의 RecursiveCharacterTextSplitter를 사용한다.
# 무슨 기능을 하나: chunk_size(기본 1000자)를 기준으로 텍스트를 자르되, chunk_overlap(기본 150자)만큼
#   앞뒤 청크가 겹치게 잘라서, 문장이 청크 경계에서 뚝 끊겨 문맥을 잃어버리는 걸 줄여준다.
# 언제 쓰이나: extract_text로 뽑아낸 전체 텍스트를, ChromaDB에 저장하고 나중에 부분 검색하기
#   좋은 단위로 쪼갤 때 routers/documents.py에서 호출된다.
def split_into_chunks(text: str, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[str]:
    # RecursiveCharacterTextSplitter(...): 이 크기/겹침 설정으로 분할기 객체를 만든다.
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    # split_text(text): 실제로 텍스트를 나눠서 문자열 리스트로 반환한다.
    return splitter.split_text(text)


# store_chunk_embeddings: 청크 텍스트들을 벡터로 바꿔서 ChromaDB에 저장(upsert)하는 함수.
# 어디서 온 기능인가: embed_texts(embedding_service.py)로 벡터를 만들고,
#   _chunk_collection.upsert(...)(chromadb 라이브러리 메서드)로 실제 저장을 수행한다.
# 무슨 기능을 하나: 청크 텍스트를 임베딩해서 ChromaDB에 upsert. PostgreSQL의 DocumentChunk 행과
#   1:1로 대응하도록 id를 "{document_id}_{chunk_index}"로 맞춘다.
#   "upsert"는 "update or insert"의 줄임말로, 같은 id가 이미 있으면 덮어쓰고 없으면 새로 추가한다.
# 언제 쓰이나: routers/documents.py의 업로드 API에서, PostgreSQL에 청크 저장을 마친 뒤 호출된다.
def store_chunk_embeddings(document_id: int, chunks: list[str]) -> None:
    """청크 텍스트를 임베딩해서 ChromaDB에 upsert. PostgreSQL의 DocumentChunk 행과
    1:1로 대응하도록 id를 "{document_id}_{chunk_index}"로 맞춘다."""
    # 청크가 하나도 없으면(예: 빈 PDF) 임베딩 계산도, 저장도 할 필요가 없으므로 바로 종료한다.
    if not chunks:
        return

    # 모든 청크를 한 번에 벡터로 변환 (문장 하나씩 여러 번 호출하는 것보다 훨씬 빠름)
    embeddings = embed_texts(chunks)
    # ChromaDB에 저장할 각 청크의 고유 id를 만든다. 같은 문서의 청크들은
    # "1_0", "1_1", "1_2"처럼 document_id와 순서(chunk_index)의 조합으로 구분된다.
    ids = [f"{document_id}_{i}" for i in range(len(chunks))]
    # 각 청크에 붙는 부가정보(metadata). document_id를 넣어두는 이유는, 나중에 검색할 때
    # "이 문서 안에서만" 찾도록 필터링(where={"document_id": ...})하기 위함이다.
    metadatas = [{"document_id": document_id, "chunk_index": i} for i in range(len(chunks))]

    # _chunk_collection.upsert(...): 위에서 만든 id/벡터/원문/메타데이터를 ChromaDB에 실제로 저장한다.
    #   ids: 각 항목의 고유 식별자
    #   embeddings: 각 청크의 벡터값 (검색 시 이 값끼리 거리를 비교함)
    #   documents: 벡터의 원본이 된 실제 텍스트 (검색 결과로 그대로 돌려받을 수 있음)
    #   metadatas: 필터링에 쓸 부가정보
    _chunk_collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )


# delete_document_embeddings: 특정 문서에 속한 벡터들을 ChromaDB에서 모두 지우는 함수.
# 어디서 온 기능인가: _chunk_collection.delete(where=...)는 chromadb 라이브러리가 제공하는
#   "조건에 맞는 항목을 지우는" 메서드.
# 무슨 기능을 하나: 문서를 삭제할 때 ChromaDB에 남는 벡터도 같이 정리한다.
#   where={"document_id": document_id} 조건으로, 이 문서에 속한 청크들만 정확히 골라 지운다.
# 언제 쓰이나: routers/documents.py의 문서 삭제 API에서, PostgreSQL의 Document/DocumentChunk
#   행을 지우기 직전에 함께 호출되어 ChromaDB에 고아 데이터가 남지 않게 한다.
def delete_document_embeddings(document_id: int) -> None:
    """문서를 삭제할 때 ChromaDB에 남는 벡터도 같이 정리한다."""
    _chunk_collection.delete(where={"document_id": document_id})
