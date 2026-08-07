# =============================================================================
# 이 파일의 역할 (deps.py = "dependencies", 의존성 모음)
# -----------------------------------------------------------------------------
# 여러 라우터(auth.py, dashboard.py, documents.py, chat.py)에서 공통으로 반복되는
# 두 가지 작업을 함수로 만들어 모아둔 파일입니다.
#
#   - get_db           : API 요청 하나가 들어올 때마다 새 DB 세션을 열어주고, 끝나면 자동으로 닫아줌
#   - get_current_user : 요청 헤더의 로그인 토큰을 해석해서 "지금 요청을 보낸 사람이 누구인지" 찾아줌
#
# 이 두 함수는 FastAPI의 Depends(...) 기능과 함께 각 라우터 함수의 매개변수로 쓰이며,
# "로그인이 필요한 API"를 만들 때마다 매번 인증 코드를 새로 짜지 않아도 되게 해줍니다.
# =============================================================================

# 파이썬 표준 라이브러리. Generator는 "yield로 값을 하나씩 내어주는 함수"의 타입을 표현할 때 사용.
# get_db 함수가 정확히 이런 형태(중간에 db를 yield하고, 끝나면 뒷정리)이기 때문에 타입 힌트로 사용한다.
from collections.abc import Generator

# FastAPI 라이브러리에서 가져옴
# - Depends: 의존성 주입 기능. 다른 함수(get_db 등)를 먼저 실행해서 그 결과를 인자로 넣어줌
# - HTTPException: 인증 실패 등 에러 상황에서 상태코드+메시지를 담아 응답하기 위한 예외
# - status: HTTP 상태코드 상수 모음 (예: status.HTTP_401_UNAUTHORIZED)
from fastapi import Depends, HTTPException, status
# FastAPI의 보안 관련 도구
# - HTTPBearer: "Authorization: Bearer <토큰>" 형태의 헤더를 자동으로 읽어주는 인증 스킴
# - HTTPAuthorizationCredentials: HTTPBearer가 읽어낸 토큰 정보를 담는 타입 (credentials.credentials로 토큰 문자열에 접근)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
# SQLAlchemy ORM 세션 타입 — 함수의 반환/매개변수 타입 힌트로 사용
from sqlalchemy.orm import Session

# app/database.py에서 만든 "세션 생성기"를 가져온다.
from app.database import SessionLocal
# app/models.py의 User ORM 모델 (DB에서 유저를 조회할 때 사용)
from app.models import User
# app/security.py의 토큰 해석 함수
from app.security import decode_access_token

# HTTPBearer(): "이 API는 Authorization 헤더에 Bearer 토큰이 필요하다"는 것을 FastAPI에게
# 알려주는 객체. 이걸 Depends(...)로 쓰면 FastAPI가 자동으로 /docs 문서에도
# "인증 필요" 표시를 해주고, 헤더가 없으면 알아서 에러를 응답해준다.
bearer_scheme = HTTPBearer()


# get_db: API 요청 하나마다 새로운 DB 세션을 만들어주는 함수.
# 어디서 온 기능인가: SessionLocal()은 app/database.py의 sessionmaker로 만든 세션 생성기를 호출한 것.
# 무슨 기능을 하나: try/finally 구조로, 함수를 쓰는 쪽(라우터)에게 db를 잠깐 "빌려주고"(yield),
#   그 라우터 함수가 끝나면(정상 종료든 에러든) 반드시 db.close()로 세션을 정리한다.
# 언제 쓰이나: 라우터 함수에서 "db: Session = Depends(get_db)"처럼 매개변수로 선언될 때마다
#   FastAPI가 이 함수를 실행해서 db 값을 넣어준다. 요청마다 독립적인 세션을 쓰기 때문에
#   여러 요청이 동시에 들어와도 세션이 서로 섞이지 않는다.
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()  # 새 DB 세션(대화 창구) 하나를 연다
    try:
        yield db  # 이 지점에서 실행이 잠깐 멈추고, db를 필요로 하는 라우터 함수로 넘어간다
    finally:
        # 라우터 함수가 끝나서 다시 이 지점으로 돌아오면(성공/실패 상관없이) 항상 세션을 닫는다.
        # 세션을 안 닫으면 DB 커넥션이 계속 쌓여서 나중에 "연결 초과" 에러가 날 수 있다.
        db.close()


# get_current_user: 요청에 담긴 로그인 토큰을 확인해서, 실제로 로그인한 User 객체를 찾아주는 함수.
# 어디서 온 기능인가:
#   credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)
#     → FastAPI가 요청 헤더에서 "Authorization: Bearer <토큰>"을 자동으로 파싱해서 넣어준다.
#       헤더 자체가 없으면 이 단계에서 FastAPI가 자동으로 401/403 에러를 응답한다.
#   db: Session = Depends(get_db)
#     → 바로 위에서 만든 get_db를 재사용해서 DB 세션을 받는다.
# 무슨 기능을 하나: 토큰을 해석(decode)해서 유저 id를 얻고, 그 id로 DB에서 실제 User를 조회한다.
#   토큰이 잘못됐거나, 유저 id는 맞는데 DB에 그 유저가 없으면(탈퇴 등) 401 에러를 낸다.
# 언제 쓰이나: "로그인해야만 쓸 수 있는" 모든 API(예: /api/auth/me, /api/dashboard,
#   /api/documents/*, /api/chat/*)에서 "current_user: User = Depends(get_current_user)"로 사용된다.
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        # decode_access_token(): app/security.py 함수. PyJWT로 토큰 서명을 검증하고
        # 만료 여부를 확인한 뒤, 토큰 안에 담긴 유저 id를 꺼내온다.
        # credentials.credentials: HTTPBearer가 "Bearer " 접두사를 제거하고 넘겨준 순수 토큰 문자열.
        user_id = decode_access_token(credentials.credentials)
    except Exception as exc:
        # 토큰이 위조됐거나, 형식이 잘못됐거나, 만료된 경우 등 decode 과정에서 어떤 에러가 나든
        # 클라이언트에게는 구체적인 이유 대신 "토큰이 유효하지 않다"는 401 에러로 통일해서 응답한다.
        # "from exc"는 에러 원인을 추적할 수 있도록 원래 예외를 함께 남겨두는 파이썬 문법이다.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from exc

    # db.get(User, user_id): SQLAlchemy에서 기본키(primary key)로 한 건을 빠르게 조회하는 방법.
    # "SELECT * FROM users WHERE id = user_id"와 같은 효과이며, 없으면 None을 반환한다.
    user = db.get(User, user_id)
    if user is None:
        # 토큰 자체는 유효했지만(서명/만료 통과), 그 안에 담긴 id의 유저가 DB에 없는 경우
        # (예: 회원 탈퇴 후 예전 토큰으로 접근한 경우) 역시 401로 처리한다.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # 여기까지 통과하면 정상적으로 로그인된 유저이므로, 이 User 객체를 라우터 함수에 그대로 전달한다.
    return user
