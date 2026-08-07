# =============================================================================
# 이 파일의 역할 (security.py)
# -----------------------------------------------------------------------------
# "비밀번호를 안전하게 다루는 것"과 "로그인 토큰(JWT)을 만들고 해석하는 것"을
# 전담하는 파일입니다. 이 파일에는 API 엔드포인트(라우터)가 하나도 없고,
# 다른 파일(routers/auth.py, app/deps.py)이 가져다 쓰는 "도구 함수" 4개만 정의합니다.
#
#   - hash_password / verify_password : 비밀번호 저장/검증용 (bcrypt 사용)
#   - create_access_token / decode_access_token : 로그인 토큰 발급/해석용 (JWT 사용)
# =============================================================================

# 파이썬 표준 라이브러리 datetime에서 가져옴 — 토큰 만료 시각을 계산하기 위해 사용
# - datetime: 특정 시각(날짜+시간)을 표현하는 타입
# - timedelta: "몇 분 뒤" 같은 시간 간격을 표현하는 타입
# - timezone: 시간대(UTC 등)를 다루기 위한 타입
from datetime import datetime, timedelta, timezone

# bcrypt: 비밀번호를 "단방향 해시"로 변환해주는 라이브러리.
#   단방향이라는 것은 해시값만 보고는 원래 비밀번호를 역으로 알아낼 수 없다는 뜻이다.
#   그래서 DB에 평문 비밀번호 대신 이 해시값만 저장한다.
import bcrypt
# jwt(PyJWT): JWT(JSON Web Token) 형식의 로그인 토큰을 만들고(encode) 해석하는(decode) 라이브러리.
import jwt

# app/config.py의 settings에서 JWT 비밀키, 알고리즘, 토큰 유효기간 값을 가져와 사용한다.
from app.config import settings


# hash_password: 평문 비밀번호 → bcrypt 해시 문자열로 변환하는 함수.
# 언제 쓰이나: 회원가입 시(routers/auth.py의 signup) 사용자가 입력한 비밀번호를
# DB에 저장하기 직전에 호출된다. 원본 비밀번호는 절대 DB에 저장하지 않는다.
def hash_password(password: str) -> str:
    # bcrypt.gensalt(): 매번 랜덤한 "솔트(salt)" 값을 생성한다. 같은 비밀번호라도
    # 솔트가 다르면 해시 결과가 달라져서, 동일 비밀번호를 쓰는 두 유저의 해시값도 서로 달라진다.
    # bcrypt.hashpw(...): 비밀번호(바이트로 인코딩)와 솔트를 이용해 실제 해시를 계산한다.
    # .decode("utf-8"): bcrypt는 결과를 bytes로 주기 때문에, DB(String 컬럼)에 저장하기 좋게
    # 사람이 읽을 수 있는 문자열(str)로 바꿔준다.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# verify_password: 로그인 시 입력한 평문 비밀번호가, DB에 저장된 해시와 같은 원본에서
# 나온 것인지 확인하는 함수. bcrypt는 해시에 솔트 정보가 같이 들어있어서 별도로
# 솔트를 저장/전달하지 않아도 이 함수 하나로 비교가 가능하다.
# 언제 쓰이나: 로그인 시(routers/auth.py의 login)에서 호출된다.
def verify_password(password: str, hashed: str) -> bool:
    # bcrypt.checkpw(입력한비밀번호, 저장된해시): 내부적으로 저장된 해시에서 솔트를 꺼내
    # 입력값을 같은 방식으로 해시한 뒤 두 값이 같은지 비교하고, 같으면 True를 반환한다.
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# create_access_token: 로그인에 성공한 유저의 id를 담아 JWT 토큰 문자열을 만드는 함수.
# 언제 쓰이나: 회원가입/로그인 성공 직후(routers/auth.py)에 호출되어, 프론트엔드에
# 내려줄 access_token 값을 만든다.
def create_access_token(user_id: int) -> str:
    # 현재 시각(UTC 기준) + 설정된 유효기간(기본 7일)을 더해서 "이 토큰이 몇 시까지 유효한지"를 계산한다.
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    # JWT의 payload(토큰 안에 담기는 내용물).
    # "sub"(subject): 이 토큰이 누구의 것인지 나타내는 표준 필드 이름. 여기서는 user_id를 문자열로 담는다.
    # "exp"(expiration): 이 토큰의 만료 시각. JWT 표준에서 정한 이름이라 jwt 라이브러리가
    # 이 필드를 보고 자동으로 만료 여부를 판단해준다.
    payload = {"sub": str(user_id), "exp": expire}
    # jwt.encode(payload, 비밀키, algorithm=...):
    #   payload를 비밀키로 서명해서 하나의 토큰 문자열로 만든다. 이 비밀키를 모르는 사람은
    #   유효한 토큰을 위조할 수 없다(서명 검증에 실패하기 때문).
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


# decode_access_token: 클라이언트가 보낸 토큰 문자열을 해석해서, 그 안에 담긴 user id를
# 정수로 돌려주는 함수. 서명이 위조되었거나 만료된 토큰이면 jwt 라이브러리가 예외(에러)를
# 던지는데, 이 예외 처리는 이 함수를 호출하는 쪽(app/deps.py의 get_current_user)에서 담당한다.
# 언제 쓰이나: 로그인이 필요한 모든 API 요청마다(app/deps.py의 get_current_user 안에서) 호출된다.
def decode_access_token(token: str) -> int:
    # jwt.decode(토큰, 비밀키, algorithms=[...]):
    #   서명이 올바른지, 아직 만료되지 않았는지를 검증하면서 payload를 복원한다.
    #   검증에 실패하면 여기서 바로 예외가 발생한다.
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    # 토큰을 만들 때 문자열로 저장해둔 "sub"(유저 id)를 다시 정수(int)로 변환해서 반환한다.
    return int(payload["sub"])
