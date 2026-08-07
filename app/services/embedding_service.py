# =============================================================================
# 이 파일의 역할 (services/embedding_service.py)
# -----------------------------------------------------------------------------
# "텍스트를 숫자 벡터(임베딩)로 변환하는 일"만 전담하는 파일입니다.
# 여기서 말하는 "임베딩"이란, 문장의 의미를 담은 실수(float) 숫자 배열을 뜻합니다.
# 의미가 비슷한 문장끼리는 벡터도 서로 가깝게 만들어지기 때문에, 이 벡터들끼리
# 거리를 비교하면 "이 질문과 의미상 가장 비슷한 문장이 뭔지" 찾을 수 있습니다.
#
# 이 파일이 만든 벡터는 services/pdf_service.py(청크 저장 시)와
# routers/chat.py(질문 검색 시)에서 사용되며, 실제 벡터 저장/검색은 ChromaDB가
# 담당하고 이 파일은 "벡터로 변환하기"라는 한 가지 역할만 합니다.
# =============================================================================

# 파이썬 표준 라이브러리 functools에서 가져옴
# - lru_cache: 함수 실행 결과를 캐시(기억)해뒀다가, 같은 입력으로 다시 호출되면
#   재계산하지 않고 캐시된 값을 즉시 반환해주는 데코레이터.
from functools import lru_cache

# sentence-transformers 라이브러리에서 가져옴
# - SentenceTransformer: 문장(텍스트)을 입력하면 의미를 담은 숫자 벡터(임베딩)로
#   변환해주는 사전 학습된 AI 모델을 불러오고 실행하는 클래스.
from sentence_transformers import SentenceTransformer

# 사용할 임베딩 모델 이름. Hugging Face(모델 저장소)에 올라온 모델을 이름으로 지정하면
# 처음 실행 시 자동으로 다운로드된다.
# 다국어(한국어 포함) 문장 임베딩을 지원하는 경량 모델. 강의자료가 대부분 한국어라 영어 전용
# 모델(all-MiniLM-L6-v2) 대신 multilingual 모델을 기본값으로 둔다.
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


# _get_model: 실제 SentenceTransformer 모델 객체를 만들어서 반환하는 함수.
# 어디서 온 기능인가: SentenceTransformer(모델이름)을 호출하면 라이브러리가 모델 파일을
#   (필요하면 인터넷에서) 내려받아 메모리에 로드한다.
# 무슨 기능을 하나: 모델을 "준비"만 하는 함수. 실제 문장 변환은 아래 embed_texts에서 한다.
# 언제 쓰이나: embed_texts 함수 내부에서 모델이 필요할 때마다 호출되지만,
#   아래 @lru_cache 덕분에 실제로 무거운 로딩 작업은 프로세스 전체에서 딱 한 번만 일어난다.
@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    # 모델 로딩이 수백 ms~수 초 걸리므로 프로세스당 한 번만 로드해 재사용한다.
    # maxsize=1인 lru_cache가 붙어 있어서, 이 함수는 같은 인자(인자 없음)로 두 번째 호출될 때부터는
    # 새로 모델을 로드하지 않고 처음 만들어둔 모델 객체를 그대로 재사용한다.
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


# embed_texts: 문자열 여러 개를 한 번에 벡터 여러 개로 변환하는 함수.
# 어디서 온 기능인가: model.encode(...)는 SentenceTransformer 라이브러리가 제공하는 메서드로,
#   문장 리스트를 받아 각 문장에 대응하는 벡터(숫자 배열)들을 계산해준다.
# 무슨 기능을 하나: 텍스트 리스트 → 벡터 리스트로 변환. 한 번에 여러 문장을 넘기면
#   한 문장씩 처리하는 것보다 훨씬 빠르다(배치 처리).
# 언제 쓰이나: services/pdf_service.py의 store_chunk_embeddings에서, PDF를 여러 청크로
#   나눈 뒤 그 청크들을 한꺼번에 벡터로 바꿀 때 사용된다.
def embed_texts(texts: list[str]) -> list[list[float]]:
    # 빈 리스트가 들어오면 모델을 실행할 필요도 없이 바로 빈 리스트를 반환한다 (불필요한 연산 방지).
    if not texts:
        return []
    model = _get_model()  # 캐시된 모델 객체를 가져온다 (최초 1회만 실제 로딩 발생)
    # model.encode(texts, normalize_embeddings=True):
    #   texts 안의 문장 각각을 벡터로 변환한다. normalize_embeddings=True로 정규화해두면
    #   ChromaDB의 코사인 거리 계산과 값이 일치한다(벡터 길이를 1로 맞춰서 방향만으로 비교하게 됨).
    embeddings = model.encode(texts, normalize_embeddings=True)
    # model.encode()의 결과는 numpy 배열 형태인데, ChromaDB 등 다른 라이브러리에 넘기기 편하도록
    # 순수 파이썬 리스트(list[list[float]])로 변환해서 반환한다.
    return embeddings.tolist()


# embed_text: 문장 "하나"만 벡터로 변환하고 싶을 때 쓰는 편의 함수.
# 어디서 온 기능인가: 내부적으로 위의 embed_texts를 재사용한다 (직접 model.encode를 다시 부르지 않음).
# 무슨 기능을 하나: [문장]처럼 리스트에 한 개만 담아 embed_texts를 호출하고, 결과 리스트의
#   첫 번째(=유일한) 벡터만 꺼내서 반환한다.
# 언제 쓰이나: routers/chat.py에서 유저의 질문 한 문장을 벡터로 바꿔 ChromaDB에서
#   유사한 청크를 검색할 때 사용된다.
def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
