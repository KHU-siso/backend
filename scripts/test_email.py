# 수동 테스트용 스크립트: 인자로 받은 이메일 주소에 테스트 메일 한 통을 보낸다.
# 실행 (프로젝트 루트에서): python -m scripts.test_email you@example.com
# 사전 조건: .env에 EMAIL_ENABLED=true, SMTP_USER, SMTP_PASSWORD(앱 비밀번호)가 채워져 있어야 한다.
import logging
import sys

from app.services.email_service import send_review_email


def main() -> int:
    if len(sys.argv) != 2:
        print("사용법: python -m scripts.test_email <받는사람 이메일>")
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ok = send_review_email(sys.argv[1], "테스트", "테스트 과목", "테스트 메일이에요. 복습 알림 메일이 정상 동작합니다.")
    print("발송 성공" if ok else "발송 실패 또는 건너뜀 (위 로그를 확인하세요)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
