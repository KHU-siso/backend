# =============================================================================
# 이 파일의 역할 (routers/auth.py)
# -----------------------------------------------------------------------------
# 회원가입 / 로그인 / 내 정보 조회를 담당하는 "인증(Auth)" API 라우터입니다.
# FastAPI의 APIRouter를 이용해 "/api/auth"로 시작하는 엔드포인트 3개를 정의합니다.
#
#   - POST /api/auth/signup : 회원가입 (이메일 + 비밀번호 + 이름으로 새 계정 생성)
#   - POST /api/auth/login  : 로그인 (이메일 + 비밀번호 검증 후 JWT 토큰 발급)
#   - GET  /api/auth/me     : 현재 로그인한 사용자 정보 조회 (토큰 필요)
#
# 비밀번호 해싱/검증과 JWT 토큰 발급 로직은 app/security.py에,
# "요청마다 새 DB 세션 만들기", "토큰으로 현재 로그인 유저 찾기" 같은 공용 의존성은
# app/deps.py에 따로 분리되어 있습니다. 이 파일은 그 부품들을 조합해서
# 실제 웹 API 엔드포인트로 노출하는 "조립" 역할만 합니다.
# =============================================================================

# FastAPI 라이브러리에서 가져옴
# - APIRouter: 여러 엔드포인트를 하나로 묶어 app/main.py에 등록할 수 있게 해주는 도구
# - Depends: "의존성 주입" 기능. 함수 실행 전에 다른 함수(예: DB 세션 생성)를 먼저 실행시켜 결과를 넣어줌
# - HTTPException: 에러가 발생했을 때 상태코드 + 메시지를 담아 클라이언트에 응답하기 위한 예외 클래스
# - status: 200, 401, 404 같은 HTTP 상태코드를 숫자 대신 이름으로 쓸 수 있게 해주는 상수 모음
from fastapi import APIRouter, Depends, HTTPException, status

# SQLAlchemy(ORM) 라이브러리에서 가져옴
# - Session: DB와 대화하는 "세션" 객체의 타입. 이 타입으로 힌트를 달아두면 자동완성/타입체크가 잘 됨
from sqlalchemy.orm import Session

# ---- 아래부터는 우리 프로젝트 내부 모듈들 ----

# app/deps.py: 여러 라우터에서 공통으로 쓰는 의존성 함수 모음
#   - get_db: 요청마다 새 DB 세션을 열어주고, 요청이 끝나면 자동으로 닫아줌
#   - get_current_user: Authorization 헤더의 토큰을 읽어 "지금 로그인한 유저"를 찾아줌
from app.deps import get_current_user, get_db

# app/models.py: SQLAlchemy ORM 모델. User 클래스는 PostgreSQL의 users 테이블과 1:1로 매핑됨
from app.models import User

# app/schemas.py: Pydantic 모델. API 요청/응답 데이터의 "형태(스펙)"를 정의하고 자동 검증해줌
#   - UserCreate: 회원가입 요청 body 형태 (email, password, nickname)
#   - UserLogin: 로그인 요청 body 형태 (email, password)
#   - TokenOut: 로그인/회원가입 성공 시 응답 형태 (토큰 + 유저 정보)
#   - UserOut: 유저 정보를 외부에 보여줄 때의 형태 (비밀번호 해시 같은 민감정보는 제외됨)
from app.schemas import TokenOut, UserCreate, UserLogin, UserOut

# app/security.py: 비밀번호 해시/검증, JWT 토큰 생성 함수들
#   - create_access_token: 로그인 상태를 증명하는 JWT 토큰 문자열을 만듦
#   - hash_password: bcrypt로 평문 비밀번호를 되돌릴 수 없는 해시로 변환
#   - verify_password: 입력한 평문 비밀번호와 저장된 해시가 일치하는지 확인
from app.security import create_access_token, hash_password, verify_password

# 이 라우터에 등록되는 모든 엔드포인트는 URL 앞에 자동으로 "/api/auth"가 붙는다.
# 예: 아래 signup 함수의 실제 경로는 "/api/auth/signup"이 된다.
# tags=["auth"]는 자동 생성되는 API 문서(/docs, 스웨거)에서 이 엔드포인트들을
# "auth"라는 그룹으로 묶어 보여주기 위한 설정으로, 동작 로직에는 영향이 없다.
router = APIRouter(prefix="/api/auth", tags=["auth"])


# -----------------------------------------------------------------------------
# [회원가입 API] POST /api/auth/signup
# -----------------------------------------------------------------------------
# - 어디서 온 기능인가:
#   @router.post(...)는 FastAPI의 라우터 데코레이터로, "이 함수는 POST /api/auth/signup
#   요청이 오면 실행된다"고 등록하는 역할.
#   payload: UserCreate는 app/schemas.py의 Pydantic 모델로, 요청 body(JSON)의
#   email/password/nickname 값을 FastAPI가 자동으로 읽고 검증해서 이 객체에 담아준다.
#   db: Session = Depends(get_db)는 FastAPI의 의존성 주입 기능으로, 요청이 들어올 때마다
#   app/deps.py의 get_db()가 먼저 실행되어 새 DB 세션을 만들어 넣어준다.
# - 무슨 기능을 하나: 이메일 중복 체크 → 비밀번호 해싱 → 새 유저 저장(DB) → 로그인 토큰 발급.
# - 어떤 상황에 쓰이나: 프론트엔드의 "회원가입" 화면에서 이메일/비밀번호/이름을 입력하고
#   제출 버튼을 눌렀을 때 이 엔드포인트가 호출된다.
@router.post("/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)):
    # db.query(User).filter(...).first()
    #   → SQLAlchemy ORM 문법으로 "SELECT * FROM users WHERE email = 입력한이메일 LIMIT 1"과 같은 효과.
    #   → 결과가 있으면(=이미 가입된 이메일) User 객체가, 없으면 None이 반환된다.
    if db.query(User).filter(User.email == payload.email).first():
        # 이미 같은 이메일로 가입된 유저가 있으면 409 Conflict(충돌) 에러를 응답하고 함수 실행을 즉시 종료한다.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # 새로운 User ORM 객체를 파이썬 메모리 상에서만 생성 (아직 DB에 저장된 건 아님)
    user = User(
        email=payload.email,
        nickname=payload.nickname,
        # hash_password(payload.password): 평문 비밀번호를 그대로 저장하면 위험하므로,
        # bcrypt 알고리즘으로 되돌릴 수 없는 해시 문자열로 바꿔서 저장한다.
        # 나중에 로그인할 때는 이 해시와 입력값을 비교(verify_password)하는 방식으로 검증한다.
        hashed_password=hash_password(payload.password),
    )
    db.add(user)      # 방금 만든 user 객체를 이번 DB 세션의 "저장 대기 목록"에 추가 (아직 DB에는 안 씀)
    db.commit()        # 대기 중인 변경사항을 실제로 PostgreSQL에 INSERT 쿼리로 확정 저장
    db.refresh(user)   # DB가 자동으로 채워준 값(자동증가 id, created_at 기본값 등)을 user 객체에 다시 읽어와 채움

    # create_access_token(user.id): PyJWT 라이브러리를 이용해 "이 토큰은 user.id번 유저 것"이라는
    # 정보를 담은 JWT 문자열을 만든다. 프론트엔드는 이후 API 요청마다 이 토큰을
    # "Authorization: Bearer <토큰>" 헤더에 담아 보내면 로그인 상태로 인식된다.
    token = create_access_token(user.id)
    # TokenOut(...): app/schemas.py의 응답 스펙에 맞춰 반환값을 만든다.
    # UserOut.model_validate(user): SQLAlchemy User 객체를 API로 내보내도 안전한 형태(UserOut)로 변환.
    # 이 과정에서 hashed_password 같은 민감한 필드는 UserOut에 정의되어 있지 않으므로 자동으로 빠진다.
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


# -----------------------------------------------------------------------------
# [로그인 API] POST /api/auth/login
# -----------------------------------------------------------------------------
# - 어디서 온 기능인가: signup과 마찬가지로 FastAPI(@router.post, Depends)와
#   SQLAlchemy(db.query)를 사용한다. payload: UserLogin은 app/schemas.py의 Pydantic 모델로
#   요청 body의 email/password 값을 검증해서 담아준다.
# - 무슨 기능을 하나: 이메일로 유저를 찾고, 입력한 비밀번호가 저장된 해시와 일치하는지
#   확인한 뒤, 맞으면 새 JWT 로그인 토큰을 발급한다.
# - 어떤 상황에 쓰이나: 프론트엔드의 "로그인" 화면에서 이메일/비밀번호를 입력하고
#   제출했을 때 호출된다.
@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    # 입력한 이메일과 일치하는 유저를 DB에서 한 명 조회 (없으면 None이 반환됨)
    user = db.query(User).filter(User.email == payload.email).first()
    # verify_password(payload.password, user.hashed_password):
    #   bcrypt로 "지금 입력한 평문 비밀번호"를 해시로 변환해 "DB에 저장된 해시"와 비교한다.
    # user is None or not verify_password(...):
    #   유저가 아예 없거나, 있어도 비밀번호가 틀리면 둘 다 아래의 같은 에러로 처리한다.
    #   (일부러 "이메일이 없다"와 "비밀번호가 틀렸다"를 구분해서 알려주지 않는다.
    #    구분해서 알려주면 공격자가 "이 이메일이 가입되어 있는지"를 추측할 수 있어 보안상 좋지 않다.)
    if user is None or not verify_password(payload.password, user.hashed_password):
        # 401 Unauthorized(인증 실패) 에러를 응답하고 함수 실행을 즉시 종료한다.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    # 이메일/비밀번호 검증에 성공했으므로 새 로그인 토큰을 발급한다.
    token = create_access_token(user.id)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


# -----------------------------------------------------------------------------
# [내 정보 조회 API] GET /api/auth/me
# -----------------------------------------------------------------------------
# - 어디서 온 기능인가:
#   current_user: User = Depends(get_current_user)는 FastAPI의 Depends 기능으로,
#   이 함수가 실행되기 전에 app/deps.py의 get_current_user가 먼저 실행된다.
#   get_current_user는 요청 헤더의 "Authorization: Bearer <토큰>"을 읽어서
#   app/security.py의 decode_access_token으로 토큰을 해석(PyJWT 사용)하고,
#   그 안에 담긴 user id로 DB에서 실제 User를 찾아 반환한다.
#   만약 토큰이 없거나, 형식이 잘못됐거나, 만료됐거나, 해당 유저가 DB에 없으면
#   get_current_user 단계에서 자동으로 401 에러가 발생하고 아래 함수 본문은 아예 실행되지 않는다.
# - 무슨 기능을 하나: 별도 로직 없이, 이미 인증을 통과해 확보된 현재 로그인 유저 정보를 그대로 반환한다.
# - 어떤 상황에 쓰이나: 프론트엔드 앱을 처음 켰을 때 "지금 로그인된 사용자가 누구인지" 확인하거나,
#   대시보드 화면 상단에 사용자 이름/이메일을 표시할 때 호출된다.
@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    # get_current_user가 이미 DB에서 찾아준 User 객체를 그대로 반환한다.
    # response_model=UserOut 설정 덕분에 FastAPI가 자동으로 UserOut 형태(민감정보 제외)로 변환해서 응답한다.
    return current_user
