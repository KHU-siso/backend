# =============================================================================
# 이 파일의 역할 (services/claude_service.py)
# -----------------------------------------------------------------------------
# Anthropic의 Claude AI 모델을 호출해서 실제 답변을 받아오는 부분을 전담하는 파일입니다.
# routers/chat.py는 "유저 질문 + 관련 문서 청크(컨텍스트) + 이전 대화 기록"을 준비해서
# 이 파일의 ask() 함수 하나만 호출하면 되고, Claude API를 어떻게 부르는지(모델 이름,
# 시스템 프롬프트, 요청 형식 등)에 대한 세부사항은 전부 이 파일 안에 숨겨져 있습니다.
# =============================================================================

# anthropic: Claude API를 파이썬에서 쉽게 호출할 수 있게 해주는 공식 SDK 라이브러리.
import anthropic

# app/config.py의 settings에서 Claude API 키와 사용할 모델 이름을 가져온다.
from app.config import settings

# _client: Claude API에 요청을 보낼 때 사용하는 클라이언트 객체. 파일이 처음 import될 때
# 딱 한 번만 만들어져서 이후 모든 요청에서 재사용된다(매 요청마다 새로 만들지 않음).
# settings.anthropic_api_key가 .env에 설정되어 있으면 그 키를 명시적으로 사용하고,
# 없으면(else) anthropic.Anthropic()을 인자 없이 호출해서 SDK가 알아서
# 환경변수나 로그인된 인증 정보로부터 키를 찾도록 맡긴다.
_client = (
    anthropic.Anthropic(api_key=settings.anthropic_api_key)
    if settings.anthropic_api_key
    else anthropic.Anthropic()
)

# SYSTEM_PROMPT: Claude에게 매 대화마다 공통으로 전달되는 "역할 지침".
# 유저 메시지가 아니라 AI의 행동 방식을 정의하는 별도의 지시문으로, Claude API의
# system 파라미터로 전달된다(아래 ask 함수 참고).
# 내용 요약: <context> 태그 안에 강의자료가 들어오면 그 내용에 근거해서만 답하고,
# 없으면 일반 튜터처럼 답하며, 기본적으로 한국어로 답하라는 지침을 담고 있다.
SYSTEM_PROMPT = (
    "You are 시소, a study assistant for a university student. "
    "When lecture material is provided inside <context> tags, answer strictly based on "
    "that material and say clearly when the answer isn't covered by it. "
    "When no context is given, answer as a knowledgeable, encouraging tutor. "
    "Respond in Korean unless the user writes in another language."
)


# ask: 유저의 질문에 대한 Claude의 답변을 받아오는 함수.
# 어디서 온 기능인가: _client.messages.create(...)는 anthropic SDK가 제공하는 메서드로,
#   Claude API의 "메시지 생성" 엔드포인트를 호출한다.
# 무슨 기능을 하나:
#   1) 이전 대화 기록(history) 뒤에 이번 질문을 새 user 메시지로 추가한다.
#   2) 문서 컨텍스트(context_text)가 있으면 질문 앞에 <context> 태그로 감싸서 함께 보낸다.
#   3) Claude API를 호출해서 응답을 받고, 응답 안의 텍스트 부분만 추출해서 반환한다.
# 언제 쓰이나: routers/chat.py의 send_message에서, ChromaDB로 찾은 관련 청크(context_text)와
#   대화방의 이전 메시지들(history)을 준비한 뒤 이 함수를 호출해서 실제 AI 답변을 얻는다.
def ask(question: str, history: list[dict], context_text: str | None) -> str:
    # history(예: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}])를
    # 복사해서 새 리스트를 만든다. 원본 리스트를 직접 수정하지 않기 위해 list(history)로 복사본을 만든다.
    messages = list(history)

    # 기본적으로는 질문 텍스트 그대로를 이번 메시지 내용으로 사용한다.
    user_content = question
    # context_text가 있다면(=이 대화방이 특정 문서를 기준으로 하고, 관련 청크가 검색된 경우),
    # 질문 앞에 <context>...</context> 태그로 감싼 문서 내용을 덧붙인다.
    # 이렇게 태그로 감싸는 이유는, SYSTEM_PROMPT에서 "<context> 태그 안의 내용에 근거해서 답하라"고
    # 지시해뒀기 때문에, Claude가 어디까지가 "참고 자료"이고 어디부터가 "실제 질문"인지 구분할 수 있게 하기 위함이다.
    if context_text:
        user_content = f"<context>\n{context_text}\n</context>\n\n{question}"
    # 방금 만든 이번 턴의 user 메시지를 대화 기록 맨 뒤에 추가한다.
    messages.append({"role": "user", "content": user_content})

    # _client.messages.create(...): 실제로 Claude API에 요청을 보낸다.
    #   model: settings.claude_model — 사용할 모델 (기본값 claude-opus-5)
    #   max_tokens: 4096 — Claude가 생성할 수 있는 최대 응답 길이(토큰 수)
    #   system: SYSTEM_PROMPT — 위에서 정의한 공통 역할 지침
    #   output_config={"effort": "medium"} — 답변 품질/속도/비용의 균형을 잡는 옵션.
    #     medium은 채팅처럼 응답 속도가 중요한 상황에 적절한 절충값이다.
    #   messages: 지금까지의 전체 대화 기록 + 이번 질문
    response = _client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        messages=messages,
    )
    # Claude의 응답(response.content)은 여러 종류의 "블록"으로 구성될 수 있는데(텍스트 블록 등),
    # 그중 block.type == "text"인 첫 번째 블록의 텍스트 내용만 꺼내서 반환한다.
    # 만약 텍스트 블록이 하나도 없다면(이례적인 경우) 빈 문자열("")을 대신 반환한다.
    return next((block.text for block in response.content if block.type == "text"), "")
