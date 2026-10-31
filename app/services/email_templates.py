# =============================================================================
# 메일 HTML 템플릿 (services/email_templates.py)
# -----------------------------------------------------------------------------
# Gmail 등 메일 클라이언트는 <style>, flex, SVG, 외부 폰트를 거의 지원하지 않으므로
# 인라인 스타일 + 표(table) 레이아웃만 쓴다. 이미지는 PNG를 https URL로 불러온다
# (프론트 정적 파일 public/mail/ 에 함께 배포된다).
# =============================================================================
import os
from html import escape

APP_URL = os.environ.get("APP_PUBLIC_URL", "https://app.moram.tech").rstrip("/")
ASSET_URL = f"{APP_URL}/mail"

NAVY = "#12265b"
BLUE = "#5b7bb0"
SOFT = "#e1e6f1"
FONT = "'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',Pretendard,Arial,sans-serif"


def _shell(inner: str, preheader: str) -> str:
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head>"
        f"<body style=\"margin:0;padding:0;background:#f3f5fa;font-family:{FONT}\">"
        f"<div style=\"display:none;max-height:0;overflow:hidden;opacity:0;color:#f3f5fa\">{escape(preheader)}</div>"
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" style=\"background:#f3f5fa\"><tr><td align=\"center\" style=\"padding:16px 8px\">"
        "<table role=\"presentation\" width=\"600\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" "
        "style=\"width:100%;max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden\">"
        f"{inner}"
        "</table></td></tr></table></body></html>"
    )


def _header() -> str:
    return (
        f"<tr><td align=\"center\" style=\"background:{SOFT};padding:22px 0\">"
        f"<img src=\"{ASSET_URL}/logo.png\" width=\"150\" alt=\"MORAM\" style=\"display:block;border:0;height:auto\">"
        "</td></tr>"
    )


def _footer() -> str:
    return (
        "<tr><td style=\"padding:0;line-height:0;font-size:0\">"
        f"<img src=\"{ASSET_URL}/footer.png\" width=\"600\" alt=\"옹이가 슬퍼하고 있어요. 조금씩 꾸준하게, MORAM과 함께해요.\" "
        "style=\"display:block;width:100%;max-width:600px;height:auto;border:0\">"
        "</td></tr>"
    )


def _card(icon: str, title: str, sub: str, button: str, href: str) -> str:
    return (
        "<table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" "
        "style=\"border:1px solid #d3d8e3;border-radius:18px;background:#ffffff\"><tr>"
        f"<td width=\"72\" style=\"padding:14px 0 14px 16px\"><img src=\"{ASSET_URL}/{icon}.png\" width=\"48\" height=\"48\" alt=\"\" style=\"display:block;border:0\"></td>"
        "<td style=\"padding:14px 8px\">"
        f"<div style=\"font-size:15px;font-weight:700;color:{NAVY};line-height:1.4\">{escape(title)}</div>"
        f"<div style=\"font-size:12px;font-weight:700;color:{BLUE};line-height:1.5;margin-top:2px\">{escape(sub)}</div>"
        "</td>"
        f"<td align=\"right\" style=\"padding:14px 16px 14px 0;white-space:nowrap\">"
        f"<a href=\"{escape(href)}\" style=\"display:inline-block;background:{SOFT};color:#4a5a7a;font-size:12px;font-weight:700;"
        f"text-decoration:none;padding:9px 14px;border-radius:999px\">{escape(button)}</a></td>"
        "</tr></table>"
    )


def _section(title: str, card: str) -> str:
    return (
        "<tr><td style=\"padding:8px 28px 4px\">"
        f"<div style=\"font-size:18px;font-weight:800;color:#000;margin:18px 0 10px\">&bull;&nbsp;{escape(title)}</div>"
        f"{card}</td></tr>"
    )


def deadline_email_html(user_name: str, subject_name: str, assignment_title: str, deadline_text: str, remaining_text: str) -> str:
    """과제 마감 임박 알림 (Figma '알람UI - 이메일버전')."""
    remaining = remaining_text or "마감이 다가왔어요"
    body = (
        _header()
        + "<tr><td align=\"center\" style=\"padding:44px 24px 26px\">"
        f"<div style=\"font-size:22px;font-weight:800;color:#000;line-height:1.6\">{escape(user_name)} 님, 오늘 학습할 시간이 되었어요.</div>"
        "<div style=\"font-size:22px;font-weight:800;color:#000;line-height:1.6\">마감 전에 과제를 마무리해 보세요!</div>"
        "<div style=\"font-size:14px;font-weight:700;color:#666;margin-top:22px\">오늘의 학습과 과제 일정을 확인해보세요.</div>"
        "</td></tr>"
        "<tr><td style=\"border-top:1px solid #d9dce3;font-size:0;line-height:0\">&nbsp;</td></tr>"
        + _section(
            "마감이 얼마 남지 않은 과제",
            _card("icon_task", assignment_title, f"{subject_name} · {remaining} (마감 {deadline_text})", "과제 확인하기", APP_URL),
        )
        + _section(
            "오늘의 학습 시간",
            _card("icon_clock", "아직 오늘 학습을 시작하지 않았어요.", "지금 딱 30분만 집중해볼까요?", "학습 시작하기", APP_URL),
        )
        + "<tr><td style=\"padding:18px 28px 10px;font-size:11px;color:#9aa1b2;text-align:center\">"
        "이 알림은 MORAM 마이페이지의 '과제 마감 알림'에서 끌 수 있어요.</td></tr>"
        + _footer()
    )
    return _shell(body, f"{assignment_title} · {remaining}")


def verification_email_html(code: str, expire_minutes: int) -> str:
    """회원가입 이메일 인증 코드."""
    body = (
        _header()
        + "<tr><td align=\"center\" style=\"padding:44px 24px 12px\">"
        "<div style=\"font-size:22px;font-weight:800;color:#000;line-height:1.6\">MORAM 이메일 인증</div>"
        "<div style=\"font-size:14px;font-weight:700;color:#666;margin-top:14px\">아래 인증 코드를 회원가입 화면에 입력해 주세요.</div>"
        "</td></tr>"
        "<tr><td align=\"center\" style=\"padding:16px 28px 8px\">"
        f"<div style=\"display:inline-block;background:{SOFT};border-radius:18px;padding:18px 34px;font-size:34px;letter-spacing:10px;"
        f"font-weight:800;color:{NAVY}\">{escape(code)}</div>"
        "</td></tr>"
        "<tr><td align=\"center\" style=\"padding:14px 28px 34px;font-size:12px;color:#8a91a3;line-height:1.7\">"
        f"{expire_minutes}분 안에 입력해 주세요.<br>본인이 요청하지 않았다면 이 메일을 무시하세요.</td></tr>"
        f"<tr><td align=\"center\" style=\"background:{SOFT};padding:18px;font-size:13px;font-weight:700;color:{BLUE}\">"
        "조금씩 꾸준하게, MORAM과 함께해요.</td></tr>"
    )
    return _shell(body, f"인증 코드 {code}")
