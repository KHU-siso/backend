# =============================================================================
# 이 파일의 역할 (services/email_service.py)
# -----------------------------------------------------------------------------
# "복습할 시간이에요" 알림 메일을 실제로 발송하는 파일입니다. 서비스용 Gmail 계정 하나로
# smtplib + STARTTLS(587)를 이용해 보내며, 구글 OAuth/Gmail API는 사용하지 않습니다.
# 어떤 이유로든 발송이 실패해도 예외를 밖으로 던지지 않고 로그만 남긴 뒤 False를 반환합니다.
# =============================================================================

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from app.config import settings
from app.services.email_templates import deadline_email_html, verification_email_html

logger = logging.getLogger("app.email")

# SMTP 서버 연결/응답 대기 제한 시간(초)
SMTP_TIMEOUT_SECONDS = 10


# send_review_email: 복습 알림 메일 한 통을 보내는 함수.
# 반환값: 실제로 발송에 성공하면 True, 비활성화/설정 누락으로 건너뛰었거나 실패하면 False.
# 일반 텍스트와 간단한 HTML을 함께 담은 multipart(alternative)로 보낸다.
def email_configured() -> bool:
    """메일을 실제로 보낼 수 있는 설정(EMAIL_ENABLED + SMTP 계정)이 갖춰졌는지."""
    return bool(settings.email_enabled and settings.smtp_user and settings.smtp_password)


def send_review_email(to_email: str, user_name: str, subject_name: str, message: str) -> bool:
    if not settings.email_enabled:
        logger.info("메일 발송 건너뜀: EMAIL_ENABLED=false")
        return False
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("메일 발송 건너뜀: SMTP_USER/SMTP_PASSWORD가 설정되지 않음")
        return False

    try:
        subject = f"[MORAM] {subject_name} 복습할 시간이에요"
        text_body = (
            f"{user_name}님, 안녕하세요!\n\n"
            f"{message}\n\n"
            f"'{subject_name}' 수업 내용을 잊기 전에 짧게라도 복습해 보세요.\n\n"
            f"- {settings.email_from_name} 드림\n"
        )
        html_body = (
            "<div style=\"font-family:sans-serif;line-height:1.6;color:#222\">"
            f"<p>{escape(user_name)}님, 안녕하세요!</p>"
            f"<p><strong>{escape(message)}</strong></p>"
            f"<p>'{escape(subject_name)}' 수업 내용을 잊기 전에 짧게라도 복습해 보세요.</p>"
            f"<p style=\"color:#888\">- {escape(settings.email_from_name)} 드림</p>"
            "</div>"
        )

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((settings.email_from_name, settings.smtp_user))
        msg["To"] = to_email
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

        logger.info("복습 알림 메일 발송 완료: to=%s", to_email)
        return True
    except Exception as exc:  # 어떤 오류든 밖으로 던지지 않는다 (비밀번호가 담길 수 있는 상세 내용은 남기지 않음)
        logger.error("복습 알림 메일 발송 실패: to=%s, error=%s", to_email, type(exc).__name__)
        return False


def send_verification_email(to_email: str, code: str, expire_minutes: int) -> bool:
    """회원가입 인증 코드 메일을 보낸다. 성공하면 True, 설정 누락/발송 실패면 False."""
    if not settings.email_enabled or not settings.smtp_user or not settings.smtp_password:
        logger.warning("인증 메일 발송 불가: EMAIL_ENABLED/SMTP_USER/SMTP_PASSWORD 설정을 확인하세요")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = "[MORAM] 이메일 인증 코드"
        msg["From"] = formataddr((settings.email_from_name, settings.smtp_user))
        msg["To"] = to_email
        msg.set_content(
            f"MORAM 회원가입 인증 코드입니다.\n\n인증 코드: {code}\n\n"
            f"{expire_minutes}분 안에 입력해 주세요.\n\n본인이 요청하지 않았다면 이 메일을 무시하세요.\n"
        )
        msg.add_alternative(verification_email_html(code, expire_minutes), subtype="html")
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("인증 메일 발송 완료: to=%s", to_email)
        return True
    except Exception as exc:
        logger.error("인증 메일 발송 실패: to=%s, error=%s", to_email, type(exc).__name__)
        return False


def send_assignment_deadline_email(to_email: str, user_name: str, subject_name: str, assignment_title: str, deadline_text: str, remaining_text: str = "") -> bool:
    """과제 마감 24시간 이내 알림 메일을 보낸다. 성공하면 True, 설정 누락/발송 실패면 False."""
    if not email_configured():
        logger.warning("과제 마감 메일 발송 불가: EMAIL_ENABLED/SMTP_USER/SMTP_PASSWORD 설정을 확인하세요")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[MORAM] '{assignment_title}' 과제 마감이 24시간 안으로 다가왔어요"
        msg["From"] = formataddr(("MORAM", settings.smtp_user))
        msg["To"] = to_email
        msg.set_content(
            f"{user_name}님, 안녕하세요!\n\n"
            f"'{subject_name}' 과목의 과제 '{assignment_title}' 마감이 24시간 안으로 다가왔어요.\n"
            f"마감: {deadline_text}\n\n"
            "MORAM에서 과제 상태를 확인하고 마무리해 보세요.\n\n"
            "- MORAM 드림\n\n"
            "이 알림은 MORAM 마이페이지의 '과제 마감 알림'에서 끌 수 있어요.\n"
        )
        msg.add_alternative(
            deadline_email_html(user_name, subject_name, assignment_title, deadline_text, remaining_text),
            subtype="html",
        )
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("과제 마감 메일 발송 완료: to=%s", to_email)
        return True
    except Exception as exc:
        logger.error("과제 마감 메일 발송 실패: to=%s, error=%s", to_email, type(exc).__name__)
        return False
