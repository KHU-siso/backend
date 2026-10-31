# 수동 테스트용: 빈 시간 학습 알림 확인을 지금 한 번 실행한다. (서버를 띄우지 않아도 됨)
# 실행 (프로젝트 루트에서): python -m scripts.run_free_time_check
# 사전 조건: .env 의 EMAIL_ENABLED=true, SMTP_USER, SMTP_PASSWORD, 그리고 테스트 계정이 마이페이지에서 "빈 시간 학습 알림"을 켜 둔 상태.
import logging

from app.services.free_time_scheduler import run_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(f"발송한 메일: {run_once()}통")


if __name__ == "__main__":
    main()
