# =============================================================================
# 이 파일의 역할 (error_handlers.py)
# -----------------------------------------------------------------------------
# 앱 전체에서 발생하는 예외(에러)를 한 곳에서 잡아, 항상 같은 형태의 JSON 응답
# ( {"detail": "...", "error_code": "..."} )으로 바꿔주는 "전역 예외 처리기" 모음입니다.
#
# 이게 없으면 무슨 문제가 생기나:
#   - routers/*.py에서 raise HTTPException(...)으로 명시적으로 처리한 에러는 괜찮지만,
#     Claude API 호출 실패, DB 커넥션 끊김, 그 외 예상 못한 파이썬 에러가 나면
#     FastAPI가 스택트레이스가 그대로 담긴 500 응답을 유저에게 그대로 보여줄 수 있다.
#     이는 내부 구조(파일 경로, 쿼리문, 라이브러리 버전 등)를 외부에 노출하는 보안 문제이기도 하다.
#
# register_exception_handlers(app) 함수 하나를 app/main.py에서 호출하면, 아래 4가지
# 종류의 예외에 대해 각각 안전한 응답을 반환하도록 등록된다. 어떤 핸들러가 실제로 실행될지는
# FastAPI/Starlette이 예외의 타입 상속 관계(MRO)를 보고 "가장 구체적으로 일치하는 것"을
# 자동으로 골라주므로, 아래 등록 순서 자체는 동작에 영향을 주지 않는다.
#   1) StarletteHTTPException : 라우터에서 직접 raise한 HTTPException (400/401/404/413 등)
#   2) RequestValidationError  : Pydantic이 요청 body/쿼리를 검증하다 실패한 경우 (422)
#   3) anthropic.APIError       : Claude API 호출 실패/타임아웃/레이트리밋 등
#   4) SQLAlchemyError          : DB 쿼리/커넥션 관련 에러
#   5) Exception (catch-all)    : 위 어디에도 안 걸리는, 예상 못한 나머지 모든 에러
# =============================================================================

# 파이썬 표준 라이브러리 — 에러를 서버 로그에 남기기 위해 사용 (응답에는 내용을 노출하지 않음)
import logging

# anthropic: Claude API 호출 관련 예외들의 공통 부모가 APIError다.
# (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError 등이 모두 이 클래스를 상속한다.)
import anthropic
# FastAPI에서 가져옴
# - FastAPI: register_exception_handlers의 매개변수 타입 힌트용
# - Request: 에러가 발생한 요청 정보(메서드, 경로 등)를 로그에 남기기 위해 사용
# - status: HTTP 상태코드 상수
from fastapi import FastAPI, Request, status
# RequestValidationError: 요청 body/쿼리 파라미터가 app/schemas.py의 Pydantic 스펙과
# 맞지 않을 때 FastAPI가 자동으로 발생시키는 예외.
from fastapi.exceptions import RequestValidationError
# JSONResponse: 이 파일의 모든 핸들러가 공통으로 사용할, 직접 상태코드/본문을 지정하는 응답 타입.
from fastapi.responses import JSONResponse
# SQLAlchemyError: SQLAlchemy가 발생시키는 모든 DB 관련 예외의 공통 부모 클래스.
from sqlalchemy.exc import SQLAlchemyError
# StarletteHTTPException: FastAPI의 HTTPException은 이 클래스를 상속한다. 이 클래스 기준으로
# 핸들러를 등록해야, 라우터가 직접 raise한 HTTPException뿐 아니라 "없는 경로 요청" 같은
# Starlette 내부에서 발생하는 HTTPException(404)까지 같은 포맷으로 통일해서 응답할 수 있다.
from starlette.exceptions import HTTPException as StarletteHTTPException

# 이 파일 전용 로거. 아직 app 전체의 로깅 설정(포맷/레벨)은 되어 있지 않지만, logger.error(...)로
# 남긴 로그는 파이썬 기본 설정으로도 stderr에 출력된다 (로깅 설정 자체는 이후 단계에서 정비한다).
logger = logging.getLogger("app.errors")

# HTTP 상태코드 → error_code 매핑. 라우터마다 제각각인 HTTPException(detail=...)의 status_code를
# 프론트엔드가 분기 처리하기 쉬운 고정된 문자열 코드로 바꿔준다. 매핑에 없는 상태코드는
# f"HTTP_{status_code}" 형태로 대체한다 (아래 http_exception_handler 참고).
_STATUS_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
}


def register_exception_handlers(app: FastAPI) -> None:
    """app/main.py에서 FastAPI 앱 생성 직후 한 번 호출해서, 아래 5개의 예외 핸들러를
    등록한다. (여기서 def로 감싸는 이유: main.py가 이 함수 하나만 import해서 부르면 되도록
    등록 로직을 이 파일 안에 캡슐화하기 위함.)"""

    # 1) 라우터에서 명시적으로 raise한 HTTPException + Starlette이 자동으로 내는 404 등.
    #    detail 메시지는 라우터가 이미 유저에게 보여줘도 안전하다고 판단해 작성한 것이므로 그대로 쓰고,
    #    error_code만 상태코드 기준으로 붙여준다.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        error_code = _STATUS_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_code": error_code},
            headers=exc.headers,
        )

    # 2) 요청 body/쿼리 파라미터가 Pydantic 스키마 검증에 실패한 경우.
    #    exc.errors()는 "어떤 필드가 왜 잘못됐는지"를 담고 있는데, 이건 서버 내부 정보가 아니라
    #    유저가 보낸 입력값 자체에 대한 설명이라 그대로 응답에 포함해도 안전하다.
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "요청 값이 올바르지 않습니다.",
                "error_code": "VALIDATION_ERROR",
                "errors": exc.errors(),
            },
        )

    # 3) Claude API 호출 실패 (연결 실패, 타임아웃, 레이트리밋, 인증 오류 등 anthropic.APIError와
    #    그 하위 클래스 전부가 여기서 잡힌다). 유저에게는 원인을 구분해서 알려주지 않고 "일시적으로
    #    응답할 수 없다"는 안전한 메시지만 주고, 실제 원인(exc)은 서버 로그에만 남긴다.
    #    503 Service Unavailable: 서버 자체가 아니라 "외부 서비스(Claude)"가 일시적으로 문제라는 의미.
    @app.exception_handler(anthropic.APIError)
    async def claude_api_exception_handler(request: Request, exc: anthropic.APIError) -> JSONResponse:
        logger.error(
            "Claude API error on %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "AI 응답을 일시적으로 생성할 수 없습니다. 잠시 후 다시 시도해주세요.",
                "error_code": "CLAUDE_API_ERROR",
            },
        )

    # 4) DB 쿼리/커넥션 관련 에러 (SQLAlchemyError와 그 하위 클래스 전부). 원본 예외에는 SQL문,
    #    테이블/컬럼 이름 같은 내부 구조가 그대로 담겨 있을 수 있어 절대 응답에 그대로 노출하지 않는다.
    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "Database error on %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "서버에서 데이터를 처리하는 중 오류가 발생했습니다.",
                "error_code": "DATABASE_ERROR",
            },
        )

    # 5) catch-all: 위 4개 핸들러 중 어느 것에도 해당하지 않는 나머지 모든 예외.
    #    이게 없으면 예상 못한 버그가 날 때 FastAPI 기본 500 응답(스택트레이스 포함 가능)이
    #    그대로 유저에게 노출된다. 항상 안전한 메시지 하나로 통일해서 응답한다.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=exc
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "서버에 예상치 못한 오류가 발생했습니다.",
                "error_code": "INTERNAL_SERVER_ERROR",
            },
        )
