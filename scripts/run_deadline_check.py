# 수동 테스트용 스크립트: 과제 마감 알림 확인을 지금 한 번 실행한다. (서버를 띄우지 않아도 됨)
# 실행 (프로젝트 루트에서): python -m scripts.run_deadline_check
# 사전 조건: .env에 EMAIL_ENABLED=true, SMTP_USER, SMTP_PASSWORD가 채워져 있어야 한다.
import logging

from app.services.deadline_scheduler import run_once


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(f"발송한 메일: {run_once()}통")


if __name__ == "__main__":
    main()
