# =============================================================================
# 이 파일의 역할 (services/priority_service.py)
# -----------------------------------------------------------------------------
# "무엇부터 해야 하는가"와 "언제 하면 좋은가"를 계산하는 두 가지 함수를 모아둔 파일입니다.
#
#   - get_priority_checklist: 학습 스타일 구분 없이, 모든 유저에게 동일한 규칙(밀린 것 우선,
#     그다음 마감 임박순)으로 과제 체크리스트를 만든다.
#   - find_free_time_slots  : 특정 날짜에 그 유저의 Subject(수업)와 Event(개인 일정)를 모두
#     합쳐서, 1시간 이상 비어있는 시간대를 찾는다.
#
# 예전에는 이 로직이 routers/subjects.py 안에 있었고 User.learning_style("복습형"/
# "벼락치기형")에 따라 마감 기준과 복습 추천 방식이 갈렸다. learning_style이 없어지면서
# 그 분기를 그대로 옮기지 않고, 모두에게 같은 규칙을 적용하는 이 파일로 새로 정리했다.
# =============================================================================

# 파이썬 표준 라이브러리 — 날짜/시간 계산에 사용
from datetime import date, datetime, time, timedelta

# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/models.py: 과제/과목/개인일정 ORM 모델
from app.models import Assignment, Event, Subject

# WEEKDAY_KR: 파이썬 date.weekday()가 반환하는 0(월요일)~6(일요일) 인덱스를
# Subject.day_of_week에 저장된 한글 요일 문자열로 바꾸기 위한 표.
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# DAY_START/DAY_END: 빈 시간을 찾을 때 기준으로 삼는 하루의 시작/끝 시각.
# 새벽 시간까지 "빈 시간"으로 추천하는 건 실용적이지 않으므로, 통상적인 기상~취침 학습
# 가능 시간대(오전 9시~오후 10시)로 임의 지정했다 (routers/subjects.py에 있던
# 기존 EVENING_END=22:00 관례를 그대로 이어받았다).
DAY_START = time(9, 0)
DAY_END = time(22, 0)

# MIN_FREE_MINUTES: "빈 시간"으로 인정할 최소 길이 (1시간).
MIN_FREE_MINUTES = 60


# get_priority_checklist: 이 유저의 모든 과제를 우선순위 순서로 정리해서 반환하는 함수.
# 무슨 기능을 하나:
#   1) "이번 주 일요일까지"를 기준선으로 잡아, 그 안에 마감하는 과제만 추려온다
#      (이미 마감이 지난 과제도 due_date가 과거이므로 당연히 이 기준을 통과한다).
#   2) 마감일 오름차순으로 정렬한다 — 이미 지난 과제는 due_date가 가장 빠르므로,
#      정렬만으로 자연스럽게 "밀린 것부터" 맨 앞에 오게 된다.
#   3) 각 항목에 is_overdue(마감이 지났는지)를 계산해서 함께 내려준다.
# 언제 쓰이나: routers/schedule.py의 GET /api/dashboard/priority에서 호출된다.
def get_priority_checklist(user_id: int, db: Session) -> list[dict]:
    today = date.today()
    # week_start: 이번 주 월요일. week_end: 이번 주 일요일.
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    rows = (
        db.query(Assignment, Subject.id, Subject.name)
        .join(Subject, Assignment.subject_id == Subject.id)
        .filter(Subject.user_id == user_id)
        .filter(Assignment.due_date <= week_end)
        .order_by(Assignment.due_date.asc())
        .all()
    )

    return [
        {
            "assignment_id": assignment.id,
            "subject_id": subject_id,
            "subject_name": subject_name,
            "title": assignment.title,
            "due_date": assignment.due_date,
            "is_overdue": assignment.due_date < today,
            "days_remaining": (assignment.due_date - today).days,
        }
        for assignment, subject_id, subject_name in rows
    ]


# find_free_time_slots: 특정 날짜 하루 동안, 이 유저의 일정이 1시간 이상 비어있는 구간을
# 모두 찾아 반환하는 함수. "오늘 남은 시간에 빈 시간이 없으면 다음날을 본다"는 롤오버 자체는
# 이 함수가 아니라 이 함수를 반복 호출하는 쪽(services/notification_service.py)의 책임이다 —
# 이 함수는 항상 "주어진 특정 하루"만 계산한다.
# 무슨 기능을 하나:
#   1) 그 날짜의 요일에 해당하는 Subject(휴강 처리된 과목은 제외)와, 그 날짜의 Event를 모두 모은다.
#   2) 시작 시각 순으로 정렬한 뒤, 일정과 일정 사이(그리고 하루의 시작/끝)에서 1시간 이상
#      비는 구간을 찾는다.
#   3) 대상 날짜가 오늘이면, 이미 지나간 오전 시간을 추천하지 않도록 "지금 시각이후"부터 계산한다.
# 언제 쓰이나: services/notification_service.py의 create_review_notification에서 호출된다.
def find_free_time_slots(user_id: int, target_date: date, db: Session) -> list[tuple[time, time]]:
    weekday_kr = WEEKDAY_KR[target_date.weekday()]
    subjects = (
        db.query(Subject)
        .filter(
            Subject.user_id == user_id,
            Subject.day_of_week == weekday_kr,
            # is_canceled_this_week인 과목은 이번 주엔 실제로 수업이 없으므로, 그 시간대를
            # "바쁜 시간"이 아니라 "빈 시간"으로 계산해야 한다.
            Subject.is_canceled_this_week.is_(False),
        )
        .all()
    )
    events = db.query(Event).filter(Event.user_id == user_id, Event.date == target_date).all()

    busy_blocks = sorted(
        [(subject.start_time, subject.end_time) for subject in subjects]
        + [(event.start_time, event.end_time) for event in events]
    )

    day_start = DAY_START
    if target_date == date.today():
        now = datetime.now().time()
        if now > day_start:
            day_start = now

    free_slots: list[tuple[time, time]] = []
    cursor = day_start
    for block_start, block_end in busy_blocks:
        if block_start > cursor and _minutes_between(cursor, block_start) >= MIN_FREE_MINUTES:
            free_slots.append((cursor, block_start))
        if block_end > cursor:
            cursor = block_end
    if cursor < DAY_END and _minutes_between(cursor, DAY_END) >= MIN_FREE_MINUTES:
        free_slots.append((cursor, DAY_END))

    return free_slots


# _minutes_between: 같은 날 안의 두 시각(time) 사이의 분(minute) 차이를 계산하는 내부 함수.
# time끼리는 직접 뺄셈이 안 되므로, 임의의 같은 날짜와 결합해 datetime으로 만든 뒤 차이를 구한다.
def _minutes_between(start: time, end: time) -> float:
    anchor = date.today()
    return (datetime.combine(anchor, end) - datetime.combine(anchor, start)).total_seconds() / 60
