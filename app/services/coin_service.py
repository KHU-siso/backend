# =============================================================================
# 이 파일의 역할 (services/coin_service.py)
# -----------------------------------------------------------------------------
# "옹이" 캐릭터의 코인/기분 상태(CharacterState)를 갱신하는 로직을 모아둔 파일입니다.
#
#   - calculate_quiz_reward   : 퀴즈 정답률에 따라 코인을 지급하고 기분을 좋게 만든다.
#   - update_mood_on_incomplete: 밀린 할 일이 있으면 기분을 나쁘게 만든다.
#   - get_or_create_character_state: 위 두 함수와 routers/schedule.py가 공통으로 쓰는,
#     "이 유저의 CharacterState가 없으면 기본값으로 하나 만들어준다"는 헬퍼.
# =============================================================================

# 파이썬 표준 라이브러리 — 마감이 지난 과제를 판단할 때 사용
from datetime import date

# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/models.py: 캐릭터 상태/과제/과목/알림 ORM 모델
from app.models import Assignment, CharacterState, Notification, Subject

# LOW_SCORE_THRESHOLD 미만: 코인 없음. 그 이상 MID_SCORE_THRESHOLD 미만: 코인 1개.
# MID_SCORE_THRESHOLD 이상(100 이하): 코인 3개.
LOW_SCORE_THRESHOLD = 50
MID_SCORE_THRESHOLD = 75
MID_SCORE_REWARD = 1
HIGH_SCORE_REWARD = 3


# get_or_create_character_state: 이 유저의 CharacterState 행을 가져오고, 아직 없으면
# (coin_balance=0, mood="neutral" 기본값으로) 새로 만들어서 반환하는 함수.
# 언제 쓰이나: 회원가입 시점에 CharacterState를 미리 만들어두지 않기 때문에, 이 상태를
# 처음 필요로 하는 모든 곳(퀴즈 보상 지급, 기분 갱신, GET /api/character 조회)에서 호출된다.
def get_or_create_character_state(db: Session, user_id: int) -> CharacterState:
    character = db.query(CharacterState).filter(CharacterState.user_id == user_id).first()
    if character is None:
        character = CharacterState(user_id=user_id)
        db.add(character)
        db.commit()
        db.refresh(character)
    return character


# calculate_quiz_reward: 퀴즈 결과(맞은 개수/전체 개수)를 보고 코인을 지급하는 함수.
# 스펙에는 인자가 correct_count/total_count뿐이었지만, "CharacterState.coin_balance를
# 업데이트하고 mood를 happy로 바꾼다"는 요구사항 자체가 DB에 접근해야 하므로 user_id와 db를
# 추가로 받도록 조정했다.
# 무슨 기능을 하나:
#   - 정답률 50% 미만: 코인 지급 없이, 다시 도전할지 물어보는 선택지 문구만 반환한다.
#   - 50% 이상 75% 미만: 코인 1개 지급.
#   - 75% 이상: 코인 3개 지급.
#   - 코인이 지급된 경우(50% 이상)에만 CharacterState.coin_balance를 늘리고 mood를 "happy"로 바꾼다.
# 언제 쓰이나: 앞으로 퀴즈 결과 조회(routers/quiz.py의 GET .../result) 시점에 연결되어 호출될
# 함수다. 이번 작업 범위에는 quiz.py 수정이 포함되어 있지 않아, 아직 실제 엔드포인트에는
# 연결돼 있지 않다.
def calculate_quiz_reward(user_id: int, db: Session, correct_count: int, total_count: int) -> dict:
    percentage = (correct_count / total_count * 100) if total_count else 0

    if percentage < LOW_SCORE_THRESHOLD:
        return {
            "percentage": percentage,
            "coins_awarded": 0,
            "choices": ["다시 복습할까요?", "다시 퀴즈 풀어볼까요?"],
        }

    coins_awarded = MID_SCORE_REWARD if percentage < MID_SCORE_THRESHOLD else HIGH_SCORE_REWARD

    character = get_or_create_character_state(db, user_id)
    character.coin_balance += coins_awarded
    character.mood = "happy"
    db.commit()
    db.refresh(character)

    return {"percentage": percentage, "coins_awarded": coins_awarded, "choices": None}


# update_mood_on_incomplete: 마감이 지난 미완료 과제나, 체크하지 않은 알림이 남아있으면
# 캐릭터 기분을 "sad"로 바꾸는 함수.
# 무슨 기능을 하나: Assignment는 "완료" 개념이 따로 없어(QuizAttempt처럼 풀이 여부를 남기지
# 않음) due_date가 지났는지만으로 "밀렸다"고 판단한다. Notification은 is_completed=False인
# 것이 하나라도 있으면 "아직 할 일이 남았다"고 본다.
# 언제 쓰이나: 대시보드를 열 때마다(또는 주기적 배치에서) 캐릭터 기분을 최신 상태로 맞추기 위해
# 호출하도록 만들어진 함수다.
def update_mood_on_incomplete(user_id: int, db: Session) -> CharacterState:
    today = date.today()
    has_overdue_assignment = (
        db.query(Assignment)
        .join(Subject, Assignment.subject_id == Subject.id)
        .filter(Subject.user_id == user_id, Assignment.due_date < today)
        .first()
        is not None
    )
    has_incomplete_notification = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_completed.is_(False))
        .first()
        is not None
    )

    character = get_or_create_character_state(db, user_id)
    if has_overdue_assignment or has_incomplete_notification:
        character.mood = "sad"
        db.commit()
        db.refresh(character)
    return character
