# =============================================================================
# 이 파일의 역할 (config.py)
# -----------------------------------------------------------------------------
# 프로젝트 전체에서 쓰는 "환경 설정값"을 한 곳에 모아두는 파일입니다.
# DB 주소, JWT 비밀키, Claude API 키처럼 서버마다(내 컴퓨터/배포 서버) 값이 달라져야 하는
# 정보를 코드에 직접 적지 않고, 프로젝트 루트의 .env 파일에서 읽어와 settings 객체로 만듭니다.
#
# 다른 파일들(database.py, security.py, services/*.py 등)은 이 파일의 settings를
# import해서 "settings.database_url"처럼 사용합니다. 즉 이 파일은 프로젝트의
# "환경설정 창구" 역할을 합니다.
# =============================================================================

# pydantic-settings 라이브러리에서 가져옴
# - BaseSettings: 이 클래스를 상속하면, 클래스에 적어둔 필드 이름과 같은 이름의
#   환경변수(또는 .env 파일의 값)를 자동으로 읽어와 채워주는 "설정 전용" 모델이 됨
# - SettingsConfigDict: BaseSettings의 동작 방식(어떤 .env 파일을 읽을지 등)을 설정하는 도구
from pydantic_settings import BaseSettings, SettingsConfigDict


# Settings 클래스: 이 프로젝트에서 필요한 모든 환경설정값의 "명세서" 역할을 한다.
# 아래 필드 하나하나가 .env 파일의 같은 이름(대문자)의 줄과 자동으로 매칭된다.
# 예: database_url 필드는 .env 파일의 "DATABASE_URL=..." 줄 값을 읽어온다.
class Settings(BaseSettings):
    # PostgreSQL 접속 주소. 타입에 기본값이 없으므로(= str만 있고 "= ..."가 없음)
    # .env에 반드시 값이 있어야 하며, 없으면 서버 실행 시 바로 에러가 난다.
    database_url: str
    # JWT 토큰을 서명/검증할 때 쓰는 비밀 문자열. 이 값을 아는 사람만 유효한 토큰을 만들 수 있으므로
    # 절대 외부에 노출되면 안 된다 (그래서 .gitignore에 .env가 들어가 있다).
    jwt_secret_key: str
    # JWT 서명에 쓰는 알고리즘. 기본값 "HS256"을 그대로 쓰면 되고, 보통 바꿀 일이 없다.
    jwt_algorithm: str = "HS256"
    # 로그인 토큰의 유효기간(분 단위). 60 * 24 * 7 = 10080분 = 7일. 이 시간이 지나면
    # 토큰이 만료되어 재로그인이 필요하다.
    access_token_expire_minutes: int = 60 * 24 * 7

    # Claude(Anthropic) API 키. "str | None = None"은 "값이 없어도 괜찮다(None 허용)"는 뜻으로,
    # .env에 안 적어두면 None이 되고, 이 경우 services/claude_service.py에서 다른 방식(환경변수 등)으로
    # 인증을 시도한다.
    anthropic_api_key: str | None = None
    # 챗봇 답변 생성에 사용할 Claude 모델 이름. 기본값으로 claude-opus-5를 사용한다.
    claude_model: str = "claude-opus-5"

    # 업로드된 PDF 원본 파일을 저장할 로컬 폴더 경로.
    upload_dir: str = "uploads"
    # ChromaDB(벡터 검색 DB)가 데이터를 저장할 로컬 폴더 경로.
    chroma_dir: str = "chroma_db"

    # model_config: BaseSettings의 동작을 세부 설정하는 부분.
    # - env_file=".env": 프로젝트 루트의 .env 파일을 읽어서 위 필드들을 채우라는 뜻.
    # - extra="ignore": .env 파일에 위 필드에 없는 값이 더 있어도 에러 내지 말고 무시하라는 뜻.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 이 파일이 처음 import될 때 딱 한 번 Settings()를 실행해서 .env 값을 읽어 들인다.
# 이후 다른 파일에서는 "from app.config import settings"로 이 객체를 그대로 재사용한다
# (매번 새로 만들지 않고 하나의 settings 인스턴스를 공유).
settings = Settings()
