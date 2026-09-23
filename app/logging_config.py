# =============================================================================
# 이 파일의 역할 (logging_config.py)
# -----------------------------------------------------------------------------
# 파이썬 표준 logging 모듈의 기본 설정(포맷, 레벨)을 한 곳에서 정하는 파일입니다.
# 이 설정이 없으면 logger.error(...)/logger.info(...) 같은 호출은 파이썬의 "최후의 수단"
# 핸들러(WARNING 이상만, 포맷도 없이 메시지만) 로만 출력되어 로그를 실제로 쓸모 있게 보기 어렵다.
#
# configure_logging()을 app/main.py에서 앱이 만들어지기 전에 딱 한 번 호출하면,
# 이후 프로젝트 어디서든 "logging.getLogger(__name__)"으로 로거를 만들어 쓰기만 하면
# 동일한 포맷/레벨로 로그가 남는다.
# =============================================================================

# 파이썬 표준 라이브러리 — 로깅 설정 자체를 담당
import logging

# app/config.py의 settings에서 로그 레벨(.env의 LOG_LEVEL, 기본값 "INFO")을 읽어온다.
from app.config import settings


def configure_logging() -> None:
    """앱 전체에서 쓸 로깅 포맷/레벨을 설정한다. app/main.py의 최상단에서 한 번만 호출된다."""
    # settings.log_level(문자열, 예: "DEBUG")을 logging 모듈이 이해하는 정수 레벨 상수로 바꾼다.
    # 오타 등으로 존재하지 않는 레벨 이름이 들어와도 서버가 죽지 않도록 기본값 INFO로 대체한다.
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # logging.basicConfig: 루트 로거(모든 로거의 최상위 부모)에 콘솔 출력 핸들러와 포맷을 설정한다.
    # 이후 만들어지는 모든 하위 로거(logging.getLogger("app.errors") 등)는 별도 설정이 없으면
    # 이 루트 설정을 그대로 물려받아 같은 포맷으로 출력된다.
    #   - asctime: 로그가 남은 시각
    #   - levelname: DEBUG/INFO/WARNING/ERROR 등
    #   - name: 어느 로거(보통 모듈 경로)에서 남긴 로그인지
    #   - message: 실제 로그 내용
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
