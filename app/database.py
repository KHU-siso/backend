# =============================================================================
# 이 파일의 역할 (database.py)
# -----------------------------------------------------------------------------
# SQLAlchemy(ORM 라이브러리)를 이용해 PostgreSQL과 "연결"하는 부분을 준비하는 파일입니다.
# 이 파일 자체는 테이블이나 API 로직을 담고 있지 않고, 다른 파일들이 DB에 접근할 때
# 공통으로 사용할 3가지 "부품"만 만들어서 내보냅니다.
#
#   - engine        : DB에 실제로 연결하는 통로 (커넥션 풀 포함)
#   - SessionLocal   : engine을 이용해 "대화 세션"을 하나씩 만들어주는 공장(팩토리)
#   - Base           : 모든 ORM 모델(app/models.py의 User, Document 등)이 상속받는 부모 클래스
#
# app/models.py는 Base를 상속해서 테이블 구조를 정의하고,
# app/deps.py는 SessionLocal을 이용해 요청마다 새 DB 세션을 만들어줍니다.
# =============================================================================

# SQLAlchemy 라이브러리에서 가져옴
# - create_engine: DB 접속 주소를 받아서 실제 DB와 통신할 수 있는 "엔진" 객체를 만드는 함수
from sqlalchemy import create_engine
# - declarative_base: ORM 모델 클래스들이 공통으로 상속받을 기본 클래스를 만들어주는 함수
# - sessionmaker: engine에 연결된 새 Session 객체를 계속 찍어낼 수 있는 "세션 팩토리"를 만드는 함수
from sqlalchemy.orm import declarative_base, sessionmaker

# app/config.py에서 만든 settings(환경설정) 객체를 가져와서 DB 접속 주소를 읽어온다.
from app.config import settings

# create_engine(settings.database_url, ...):
#   .env에 적힌 DATABASE_URL(postgresql://...)로 실제 DB 연결 엔진을 생성한다.
#   pool_pre_ping=True: 매번 쿼리를 보내기 전에 "이 연결이 아직 살아있나?"를 가볍게 확인해서,
#   오랫동안 안 쓰여서 끊긴 연결 때문에 에러가 나는 것을 방지한다.
engine = create_engine(settings.database_url, pool_pre_ping=True)

# sessionmaker(...)로 "세션 생성기"를 만든다. 이후 SessionLocal()을 호출할 때마다
# engine에 연결된 새로운 DB 세션(대화 창구) 객체가 하나씩 만들어진다.
# autocommit=False: 명시적으로 db.commit()을 호출하기 전까지는 DB에 실제 반영되지 않는다.
# autoflush=False: 쿼리를 날리기 직전에 자동으로 변경사항을 미리 반영(flush)하지 않는다
#                  (직접 db.flush()를 호출해야 할 때만 반영됨 → documents.py에서 사용).
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base: 앞으로 만들 모든 테이블 모델(User, Document, DocumentChunk 등)이 상속받을 부모 클래스.
# app/models.py에서 "class User(Base):"처럼 이 Base를 상속하면, SQLAlchemy가 그 클래스를
# 실제 DB 테이블과 자동으로 연결해준다. app/main.py의 Base.metadata.create_all(...)이
# 이 Base에 등록된 모든 모델을 보고 실제 테이블을 생성한다.
Base = declarative_base()
