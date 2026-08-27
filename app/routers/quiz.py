# =============================================================================
# 이 파일의 역할 (routers/quiz.py)
# -----------------------------------------------------------------------------
# AI 퀴즈 생성/채점과 오답노트를 담당하는 API 라우터입니다.
#
#   - POST /api/quiz/generate                              : 문서 기반 퀴즈 세트 생성 (10문제)
#   - GET  /api/quiz/{quiz_set_id}/questions/{question_index} : 세트 안의 n번째 문제 조회
#   - POST /api/quiz/questions/{question_id}/submit          : 답 제출 → 채점 → 기록
#   - POST /api/quiz/questions/{question_id}/retry           : 재도전 (submit과 동일하게 채점,
#                                                                새 기록으로 쌓임)
#   - GET  /api/quiz/{quiz_set_id}/result                    : 세트 전체 채점 결과
#   - GET  /api/wrong-notes                                   : 오답노트 (최근 오답만, 문제당 1개)
#
# 실제 "문제 생성"과 "채점" 로직은 services/quiz_service.py에 있고, 이 파일은
# 요청을 받아 소유권을 확인하고, 그 함수들을 호출해서 DB에 반영하는 역할만 한다.
# =============================================================================

# FastAPI에서 가져옴 — 라우터 등록, 의존성 주입, 에러 응답
from fastapi import APIRouter, Depends, HTTPException, status
# SQLAlchemy의 func — MAX() 같은 집계 함수를 파이썬 코드에서 쓸 수 있게 해줌
from sqlalchemy import func
# SQLAlchemy ORM 세션 타입
from sqlalchemy.orm import Session

# app/deps.py: 로그인 유저 조회, DB 세션 생성 (documents.py, chat.py, subjects.py와 동일한 패턴)
from app.deps import get_current_user, get_db
# app/models.py: 퀴즈 관련 ORM 모델 + 소유권 확인에 필요한 Document, User
from app.models import Document, QuizAttempt, QuizQuestion, QuizSet, User
# app/schemas.py: 요청/응답 형태 정의
from app.schemas import (
    QuizGenerateRequest,
    QuizQuestionOut,
    QuizResultOut,
    QuizSetOut,
    QuizSubmitRequest,
    QuizSubmitResponse,
    WrongNoteOut,
)
# services/coin_service.py: 퀴즈 결과에 따른 코인 지급 (LOW_SCORE_THRESHOLD는 "재도전 선택지"
# 문구를 다시 보여줄지 판단할 때도 재사용한다)
from app.services.coin_service import LOW_SCORE_THRESHOLD, calculate_quiz_reward
# services/quiz_service.py: 퀴즈 생성(Claude 호출 + ChromaDB 조회), 채점 로직
from app.services.quiz_service import generate_quiz_questions, grade_answer

router = APIRouter(prefix="/api", tags=["quiz"])

# TOTAL_QUESTIONS: 퀴즈 세트 하나를 생성할 때 요청할 문제 수 (스펙 기본값 10).
TOTAL_QUESTIONS = 10


# generate_quiz: 문서 하나를 골라 퀴즈 세트(문제 10개)를 새로 만드는 함수.
# 어디서 온 기능인가: payload: QuizGenerateRequest로 document_id/quiz_type을 받는다.
# 무슨 기능을 하나:
#   1) 그 문서가 실제로 있고 내 것이 맞는지 확인 (documents.py의 소유권 확인 패턴과 동일)
#   2) quiz_service.generate_quiz_questions로 Claude에게 문제 10개를 만들어 받음
#   3) QuizSet 1행 + QuizQuestion 여러 행을 한 번에 저장
# 언제 쓰이나: 프론트엔드에서 특정 문서를 열어 "퀴즈 생성" 버튼을 눌렀을 때 호출된다.
@router.post("/quiz/generate", response_model=QuizSetOut, status_code=status.HTTP_201_CREATED)
def generate_quiz(
    payload: QuizGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    document = db.get(Document, payload.document_id)
    if document is None or document.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        questions_data = generate_quiz_questions(document.id, payload.quiz_type, TOTAL_QUESTIONS)
    except ValueError as exc:
        # 문서에 청크가 없거나 Claude 응답을 파싱하지 못한 경우 등, 우리 쪽 요청이 아니라
        # "지금은 퀴즈를 만들 수 없는 상황"이므로 502(Bad Gateway 성격)로 응답한다.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if not questions_data:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="퀴즈 문제를 생성하지 못했습니다")

    quiz_set = QuizSet(
        user_id=current_user.id,
        document_id=document.id,
        quiz_type=payload.quiz_type,
        total_questions=len(questions_data),
    )
    db.add(quiz_set)
    # db.flush(): documents.py의 upload_document와 동일한 이유로, 아래에서 QuizQuestion을
    # 만들 때 필요한 quiz_set.id를 commit 전에 미리 확보한다.
    db.flush()

    for index, question in enumerate(questions_data, start=1):
        db.add(
            QuizQuestion(
                quiz_set_id=quiz_set.id,
                question_index=index,
                question_text=question.get("question", ""),
                options=question.get("options"),
                correct_answer=question.get("correct_answer", ""),
                explanation=question.get("explanation", ""),
            )
        )
    db.commit()
    db.refresh(quiz_set)
    return quiz_set


# get_question: 퀴즈 세트 안의 n번째 문제를 조회하는 함수. 정답/해설은 포함하지 않는다
# (schemas.py의 QuizQuestionOut 설명 참고 — 풀기 전에 정답이 노출되면 안 되므로).
# 언제 쓰이나: 프론트엔드가 퀴즈 화면에서 문제를 한 문제씩 순서대로 보여줄 때 호출된다.
@router.get("/quiz/{quiz_set_id}/questions/{question_index}", response_model=QuizQuestionOut)
def get_question(
    quiz_set_id: int,
    question_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quiz_set = _get_owned_quiz_set(db, quiz_set_id, current_user.id)
    question = (
        db.query(QuizQuestion)
        .filter(QuizQuestion.quiz_set_id == quiz_set.id, QuizQuestion.question_index == question_index)
        .first()
    )
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question


# submit_answer: 문제 하나에 대한 답을 제출받아 채점하고 기록하는 함수.
# 무슨 기능을 하나: quiz_service.grade_answer로 채점한 뒤, 그 결과를 새 QuizAttempt 행으로
#   저장하고, 정답/해설과 함께 채점 결과를 응답한다 (이 시점부터 정답이 공개된다).
# 언제 쓰이나: 유저가 문제를 보고 답을 골라(또는 입력해) 제출 버튼을 눌렀을 때 호출된다.
@router.post(
    "/quiz/questions/{question_id}/submit",
    response_model=QuizSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_answer(
    question_id: int,
    payload: QuizSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question = _get_owned_question(db, question_id, current_user.id)
    is_correct = grade_answer(question.correct_answer, payload.user_answer, question.quiz_set.quiz_type)

    attempt = QuizAttempt(
        quiz_question_id=question.id,
        user_id=current_user.id,
        user_answer=payload.user_answer,
        is_correct=is_correct,
    )
    db.add(attempt)
    db.commit()

    return QuizSubmitResponse(
        question_id=question.id,
        user_answer=payload.user_answer,
        is_correct=is_correct,
        correct_answer=question.correct_answer,
        explanation=question.explanation,
    )


# retry_answer: "재도전" 엔드포인트. 채점 로직과 저장 방식이 submit_answer와 완전히 동일하므로
# (QuizAttempt는 매번 새 행으로 쌓이는 구조라 애초에 "제출"과 "재도전"을 코드로 구분할 이유가
# 없다) 로직을 중복 작성하지 않고 submit_answer를 그대로 호출한다. 별도 엔드포인트로 나눈 이유는
# 프론트엔드 입장에서 "최초 제출"과 "다시 풀기"가 다른 화면/버튼에서 오는 별개의 사용자 행동이기 때문이다.
@router.post(
    "/quiz/questions/{question_id}/retry",
    response_model=QuizSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def retry_answer(
    question_id: int,
    payload: QuizSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return submit_answer(question_id, payload, current_user, db)


# get_result: 퀴즈 세트 하나를 다 풀었을 때, 전체 결과(맞은 개수/정답률)를 계산하고
# coin_service.calculate_quiz_reward로 코인을 지급하는 함수.
# 무슨 기능을 하나:
#   1) 세트 안의 문제마다 "이 유저의 가장 최근 시도"만 채점 대상으로 삼는다
#      (재도전으로 정답을 고친 경우 최신 결과가 반영되도록).
#   2) 이 세트의 코인을 아직 지급한 적이 없으면(quiz_set.reward_claimed가 False)
#      calculate_quiz_reward를 호출해 코인을 지급하고, 다시는 지급하지 않도록 표시해둔다.
#      이미 지급했다면 예전에 저장해둔 coins_awarded 값을 그대로 보여주기만 한다 — 그렇지 않으면
#      "결과 보기" 화면을 새로고침할 때마다 코인이 계속 늘어나는 버그가 생긴다.
# 언제 쓰이나: 유저가 마지막 문제까지 제출한 뒤 "결과 보기" 화면으로 넘어갈 때 호출된다.
@router.get("/quiz/{quiz_set_id}/result", response_model=QuizResultOut)
def get_result(
    quiz_set_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quiz_set = _get_owned_quiz_set(db, quiz_set_id, current_user.id)

    correct_count = 0
    for question in quiz_set.questions:
        latest_attempt = (
            db.query(QuizAttempt)
            .filter(QuizAttempt.quiz_question_id == question.id, QuizAttempt.user_id == current_user.id)
            .order_by(QuizAttempt.answered_at.desc(), QuizAttempt.id.desc())
            .first()
        )
        if latest_attempt is not None and latest_attempt.is_correct:
            correct_count += 1

    score_percent = round(correct_count / quiz_set.total_questions * 100) if quiz_set.total_questions else 0
    quiz_set.score = score_percent

    if not quiz_set.reward_claimed:
        reward = calculate_quiz_reward(current_user.id, db, correct_count, quiz_set.total_questions)
        quiz_set.coins_awarded = reward["coins_awarded"]
        quiz_set.reward_claimed = True
        choices = reward["choices"]
    else:
        # 이미 코인을 지급한 세트를 다시 조회하는 경우: coin_service를 다시 호출하지 않고,
        # "다시 도전할지" 선택지 문구만 현재 점수 기준으로 새로 계산해서 보여준다.
        choices = ["다시 복습할까요?", "다시 퀴즈 풀어볼까요?"] if score_percent < LOW_SCORE_THRESHOLD else None

    db.commit()
    db.refresh(quiz_set)

    return QuizResultOut(
        quiz_set_id=quiz_set.id,
        total_questions=quiz_set.total_questions,
        correct_count=correct_count,
        score=score_percent,
        coins_awarded=quiz_set.coins_awarded,
        choices=choices,
    )


# list_wrong_notes: 로그인 유저의 오답노트를 조회하는 함수.
# 무슨 기능을 하나: 이 유저의 QuizAttempt 중 is_correct=False인 것만 모은 뒤, 문제(quiz_question_id)
#   별로 "그 오답들 중 가장 최근 것" 하나만 남긴다 — 같은 문제를 세 번 틀렸다면 세 번째(가장 최근)
#   오답 기록만 오답노트에 나타난다.
# 어디서 온 기능인가: func.max(QuizAttempt.id)로 문제별 최신 오답의 id를 구한 뒤,
#   그 id들과 다시 조인해서 실제 행을 가져오는 "그룹별 최신 행 찾기"의 표준적인 SQL 패턴이다.
# 언제 쓰이나: 프론트엔드의 "오답노트" 화면에 들어갔을 때 호출된다.
@router.get("/wrong-notes", response_model=list[WrongNoteOut])
def list_wrong_notes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    latest_wrong_ids = (
        db.query(func.max(QuizAttempt.id).label("latest_wrong_id"))
        .filter(QuizAttempt.user_id == current_user.id, QuizAttempt.is_correct.is_(False))
        .group_by(QuizAttempt.quiz_question_id)
        .subquery()
    )

    wrong_attempts = (
        db.query(QuizAttempt)
        .join(latest_wrong_ids, QuizAttempt.id == latest_wrong_ids.c.latest_wrong_id)
        .order_by(QuizAttempt.answered_at.desc())
        .all()
    )

    return [
        WrongNoteOut(
            quiz_question_id=attempt.quiz_question_id,
            quiz_set_id=attempt.question.quiz_set_id,
            question_text=attempt.question.question_text,
            options=attempt.question.options,
            user_answer=attempt.user_answer,
            correct_answer=attempt.question.correct_answer,
            explanation=attempt.question.explanation,
            answered_at=attempt.answered_at,
        )
        for attempt in wrong_attempts
    ]


# _get_owned_quiz_set: "이 quiz_set_id가 실제로 존재하고, 요청한 유저의 것이 맞는지" 확인하는
# 내부 헬퍼 함수. documents.py의 _get_owned_document와 동일한 패턴이다.
def _get_owned_quiz_set(db: Session, quiz_set_id: int, user_id: int) -> QuizSet:
    quiz_set = db.get(QuizSet, quiz_set_id)
    if quiz_set is None or quiz_set.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz set not found")
    return quiz_set


# _get_owned_question: "이 question_id가 실제로 존재하고, 그 문제가 속한 세트가 요청한 유저의
# 것이 맞는지" 확인하는 내부 헬퍼 함수. QuizQuestion에는 user_id가 직접 없으므로 QuizSet과
# 조인해서 한 번의 쿼리로 확인한다.
def _get_owned_question(db: Session, question_id: int, user_id: int) -> QuizQuestion:
    question = (
        db.query(QuizQuestion)
        .join(QuizSet, QuizQuestion.quiz_set_id == QuizSet.id)
        .filter(QuizQuestion.id == question_id, QuizSet.user_id == user_id)
        .first()
    )
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question
