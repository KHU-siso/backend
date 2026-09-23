# =============================================================================
# 이 파일의 역할 (middleware.py)
# -----------------------------------------------------------------------------
# 이 앱에 들어오는 모든 HTTP 요청 하나하나를 가로채서, 처리가 끝난 뒤
# "어떤 메서드로 어떤 경로에 요청이 왔고, 몇 초 걸려서, 최종 상태코드가 뭐였는지"를
# 로그 한 줄로 남기는 미들웨어를 정의합니다.
#
# app/error_handlers.py의 전역 예외 핸들러가 먼저 예외를 안전한 응답으로 바꿔주기 때문에,
# 여기서는 call_next(request)가 예외를 던지는 경우를 따로 처리할 필요가 없다 — 이미
# Starlette이 exception handler를 거쳐 만든 최종 Response(예: 에러면 500/503 등)를
# 그대로 돌려받기 때문이다. 그래서 이 미들웨어는 "결과를 한 줄 로그로 남기는 것"에만 집중한다.
# =============================================================================

# 파이썬 표준 라이브러리
import logging  # 요청 로그를 남기기 위해 사용
import time     # 요청 처리에 걸린 시간(ms)을 재기 위해 사용

# FastAPI에서 가져옴
# - FastAPI: register_request_logging의 매개변수 타입 힌트용
# - Request: 지금 처리 중인 요청의 메서드/경로 등을 읽기 위해 사용
# - status: catch-all 예외 발생 시 로그에 남길 상태코드 상수(500)
from fastapi import FastAPI, Request, status

# 이 파일 전용 로거. app/logging_config.py의 configure_logging()이 설정한 포맷/레벨을
# 그대로 물려받는다 (루트 로거 설정을 상속하므로 여기서 따로 handler를 붙이지 않는다).
logger = logging.getLogger("app.requests")


def register_request_logging(app: FastAPI) -> None:
    """app/main.py에서 FastAPI 앱 생성 직후 한 번 호출해서, 모든 요청/응답을 로그로
    남기는 미들웨어를 등록한다."""

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        # time.perf_counter(): 처리 시간 측정에 적합한, 단조 증가하는 고정밀 타이머.
        start = time.perf_counter()
        try:
            # call_next(request): 이 미들웨어보다 안쪽(라우터, 그리고 app/error_handlers.py의
            # StarletteHTTPException/RequestValidationError/anthropic.APIError/SQLAlchemyError
            # 핸들러)에서 요청을 처리하고 만든 최종 Response를 돌려준다.
            response = await call_next(request)
        except Exception:
            # Starlette은 "그 외 모든 예외(catch-all)" 핸들러(app/error_handlers.py의
            # unhandled_exception_handler)를 ExceptionMiddleware가 아니라 ServerErrorMiddleware —
            # 즉 이 요청 로깅 미들웨어보다 더 바깥쪽 계층 — 에서 처리하도록 특별 취급한다.
            # 그래서 여기서 잡히지 않은 예외는 call_next()가 그대로 다시 던지며, 이 상태로 두면
            # "예상 못한 500 에러"만 이 로그에서 빠지게 된다. 상태코드 500으로 간주해 로그를
            # 남긴 뒤, 실제 응답 생성은 그대로 바깥의 catch-all 핸들러에게 맡기기 위해 다시 던진다.
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning(
                "%s %s %d %.1fms",
                request.method,
                request.url.path,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000

        # 상태코드 400 이상(클라이언트/서버 에러)은 warning으로, 그 외 정상 응답은 info로 남긴다.
        # 이렇게 레벨을 나눠두면, 운영 환경에서 LOG_LEVEL=INFO로 돌리는 중에도 에러성 요청만
        # 로그 뷰어에서 색이 다르게 보이거나 필터링하기 쉬워진다.
        log = logger.warning if response.status_code >= 400 else logger.info
        log(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
