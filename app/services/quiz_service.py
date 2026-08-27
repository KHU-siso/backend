# =============================================================================
# 이 파일의 역할 (services/quiz_service.py)
# -----------------------------------------------------------------------------
# PDF 문서 내용을 바탕으로 퀴즈 문제를 생성하고, 유저가 제출한 답을 채점하는 두 가지 작업을
# 전담하는 파일입니다.
#
#   - generate_quiz_questions: 문서의 청크(ChromaDB) → Claude에게 문제 생성 요청 → 파싱
#   - grade_answer           : 객관식은 문자열 비교, 주관식은 Claude에게 의미 비교를 맡김
#
# routers/quiz.py는 이 두 함수만 호출하면 되고, "Claude에게 어떻게 물어보는지"와
# "ChromaDB에서 어떻게 문서 내용을 가져오는지"의 세부사항은 이 파일 안에 숨겨져 있습니다.
# chat.py가 get_chunk_collection()으로 청크를 검색하는 것과 동일한 컬렉션을 재사용하고,
# Claude 호출도 claude_service.py의 클라이언트를 그대로 재사용한다(중복 생성하지 않음).
# =============================================================================

# 파이썬 표준 라이브러리 — Claude가 돌려준 텍스트를 JSON으로 해석할 때 사용
import json

# services/claude_service.py의 complete(): 대화 기록 없이 "시스템 프롬프트 + 사용자 메시지"
# 하나로 Claude를 한 번 호출하는 범용 함수. ask()는 챗봇 대화용이라 여기서는 쓰지 않는다.
from app.services.claude_service import complete
# services/pdf_service.py의 get_chunk_collection(): chat.py가 질문 검색에 쓰는 것과
# 동일한 ChromaDB 컬렉션 객체를 가져온다.
from app.services.pdf_service import get_chunk_collection

# QUIZ_SYSTEM_PROMPT: 퀴즈 생성 요청 때 Claude에게 공통으로 붙이는 역할 지침.
# "JSON 배열만 응답하라"고 명시해서, 코드블록이나 설명 문구가 섞여 파싱이 실패하는 것을 최대한 막는다.
QUIZ_SYSTEM_PROMPT = (
    "You are 시소, a study assistant that writes quiz questions for a university student "
    "based only on the lecture material given inside <context> tags. "
    "Always respond with a single valid JSON array and nothing else — "
    "no markdown code fences, no extra commentary, no trailing text."
)

# GRADING_SYSTEM_PROMPT: 주관식 채점 요청 때 Claude에게 붙이는 역할 지침.
# 답을 딱 한 단어(true/false)로만 받아야 파싱이 안전하므로 명시적으로 못박아둔다.
GRADING_SYSTEM_PROMPT = (
    "You are a strict but fair short-answer grader for a Korean university course. "
    "Compare the reference answer and the student's answer for semantic equivalence, "
    'ignoring differences in spacing, phrasing, or wording. Respond with exactly one '
    'word — "true" or "false" — and nothing else.'
)

# MAX_CONTEXT_CHARS: Claude에게 넘길 문서 컨텍스트 길이 상한.
# 문서가 아주 길면 청크를 전부 이어붙였을 때 프롬프트가 지나치게 커질 수 있어,
# 앞부분 일부만 사용해도 10문제를 뽑기엔 충분하다고 보고 안전하게 잘라낸다.
MAX_CONTEXT_CHARS = 20000


# generate_quiz_questions: 문서 하나를 기반으로 퀴즈 문제 num_questions개를 만들어 반환하는 함수.
# 어디서 온 기능인가:
#   get_chunk_collection().get(where=...) — chromadb 라이브러리가 제공하는 메서드로,
#   chat.py의 collection.query()(질문과 "비슷한" 청크를 찾는 유사도 검색)와 달리,
#   여기서는 유사도 비교 없이 "이 document_id에 속한 청크 전부"를 그대로 가져온다.
#   문제를 뽑으려면 질문 하나에 맞춘 부분 검색이 아니라 문서 전체 내용이 필요하기 때문이다.
# 무슨 기능을 하나: 청크들을 이어붙여 컨텍스트로 만들고, quiz_type에 맞는 형식을 지정해
#   Claude에게 문제 생성을 요청한 뒤, 응답 텍스트를 JSON 배열로 파싱해서 반환한다.
# 언제 쓰이나: routers/quiz.py의 POST /api/quiz/generate에서 호출된다.
def generate_quiz_questions(document_id: int, quiz_type: str, num_questions: int = 10) -> list[dict]:
    collection = get_chunk_collection()
    results = collection.get(where={"document_id": document_id})
    chunks = results.get("documents") or []
    if not chunks:
        raise ValueError("이 문서에서 추출된 내용이 없어 퀴즈를 만들 수 없습니다")

    context_text = "\n\n".join(chunks)[:MAX_CONTEXT_CHARS]

    if quiz_type == "객관식":
        format_hint = (
            '각 문제는 {"question": 문제 내용, "options": [보기1, 보기2, 보기3, 보기4], '
            '"correct_answer": 정답, "explanation": 해설} 형태의 JSON 객체여야 하고, '
            "options는 정확히 4개이며 correct_answer는 그 중 하나와 완전히 같은 문자열이어야 한다."
        )
    else:
        format_hint = (
            '각 문제는 {"question": 문제 내용, "correct_answer": 정답, "explanation": 해설} '
            "형태의 JSON 객체여야 한다 (options 필드는 넣지 않는다)."
        )

    user_message = (
        f"<context>\n{context_text}\n</context>\n\n"
        f"위 강의자료 내용을 바탕으로 {quiz_type} 퀴즈 {num_questions}문제를 만들어줘. "
        f"{format_hint} "
        f"응답은 이 문제들을 담은 JSON 배열 하나뿐이어야 하며, 그 외의 설명이나 코드블록 표시는 붙이지 마."
    )

    raw = complete(QUIZ_SYSTEM_PROMPT, user_message, max_tokens=4096)
    questions = _parse_json_array(raw)
    # Claude가 개수를 정확히 안 지켰을 경우를 대비해, 요청한 개수만큼만 사용한다
    # (부족하면 있는 만큼만 반환 — routers/quiz.py에서 그 개수를 total_questions로 저장한다).
    return questions[:num_questions]


# grade_answer: 문제 하나에 대한 채점 결과(정답 여부)를 반환하는 함수.
# 무슨 기능을 하나:
#   - 객관식: 대소문자/공백 차이 없이 정답 문자열과 완전히 같은지만 비교한다 (Claude 호출 없음).
#   - 주관식: 정답과 유저 답변을 Claude에게 보여주고 "의미가 같은지"만 true/false로 답하게 한다.
# 언제 쓰이나: routers/quiz.py의 submit/retry 엔드포인트에서 QuizAttempt를 만들기 직전에 호출된다.
def grade_answer(correct_answer: str, user_answer: str, quiz_type: str) -> bool:
    if quiz_type == "객관식":
        return user_answer.strip() == correct_answer.strip()

    user_message = f"정답: {correct_answer}\n사용자 답변: {user_answer}\n\n두 답변이 의미상 같으면 true, 다르면 false로만 답해줘."
    raw = complete(GRADING_SYSTEM_PROMPT, user_message, max_tokens=10)
    return raw.strip().lower().startswith("true")


# _parse_json_array: Claude 응답 문자열에서 JSON 배열을 뽑아 파싱하는 내부 헬퍼 함수.
# 시스템 프롬프트로 "JSON만 응답하라"고 지시해도 가끔 ```json ... ``` 코드블록으로 감싸서
# 돌아오는 경우가 있어, 그 껍데기를 벗겨낸 뒤 파싱을 시도한다.
def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[len("json") :].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Claude 응답을 퀴즈 JSON으로 해석하지 못했습니다") from exc
    if not isinstance(data, list):
        raise ValueError("Claude 응답이 JSON 배열 형태가 아닙니다")
    return data
