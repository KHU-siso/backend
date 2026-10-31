# =============================================================================
# services/note_context_service.py
# -----------------------------------------------------------------------------
# 과목 AI 채팅의 근거에 "내가 직접 쓴 학습 노트"를 포함시키기 위한 헬퍼.
#
# 노트는 별도 테이블이 아니라 프론트가 저장하는 user_states('subjects') JSON 안
# (data["notes"] = [{id, subjectId, title, body, updatedAt, ...}])에 있다. 그래서 Chroma에
# 따로 인덱싱하지 않고, 채팅 시점에 그 JSON에서 (현재 사용자 · 현재 과목) 노트만 꺼내 프롬프트에 넣는다.
#   - 항상 최신 노트가 반영된다 (수정·삭제 때 별도 갱신/재인덱싱이 필요 없다).
#   - 사용자·과목 필터가 쿼리 조건(user_id)과 subjectId 비교로 구조적으로 보장된다.
#   - 서버가 여러 대여도 공유 상태(DB)만 읽으므로 불일치가 없다.
# 길이는 제한한다: 노트가 많으면 질문과 단어가 겹치는 노트를 먼저, 그다음 최근 수정순으로 담는다.
# =============================================================================
import re

from sqlalchemy.orm import Session

from app.models import UserState

NOTES_MAX_CHARS = 8000  # 프롬프트에 넣는 노트 전체 글자 수 상한
NOTE_MAX_CHARS = 3000  # 노트 하나당 상한
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def load_subject_notes(db: Session, user_id: int, subject_ref: str) -> list[dict]:
    """이 사용자가 이 과목에 쓴 노트만 돌려준다. (user_id 행 하나만 읽고, subjectId가 같은 노트만 고른다)"""
    row = db.get(UserState, (user_id, "subjects"))
    data = row.data if row is not None and isinstance(row.data, dict) else {}
    notes = data.get("notes")
    if not isinstance(notes, list):
        return []
    return [
        note
        for note in notes
        if isinstance(note, dict) and note.get("subjectId") == subject_ref and isinstance(note.get("body"), str)
    ]


def _score(note: dict, tokens: set[str]) -> int:
    text = f"{note.get('title', '')} {note.get('body', '')}".lower()
    # 한국어는 조사가 붙어("적분이", "미분을") 그대로는 안 맞으므로 끝 1~2글자를 뗀 형태도 허용한다.
    return sum(
        1
        for token in tokens
        if token in text or (len(token) >= 3 and token[:-1] in text) or (len(token) >= 4 and token[:-2] in text)
    )


def build_notes_context(notes: list[dict], question: str) -> str:
    """노트들을 '[내 노트] 제목 + 본문' 형태 하나의 문자열로. 비어 있거나 본문이 없으면 ''."""
    tokens = {token.lower() for token in _TOKEN.findall(question or "")}
    usable = [note for note in notes if note["body"].strip()]  # 본문이 없는 노트는 근거가 되지 않는다
    usable.sort(key=lambda note: str(note.get("updatedAt") or ""), reverse=True)  # 최근 수정순
    usable.sort(key=lambda note: _score(note, tokens), reverse=True)  # 질문과 겹치는 노트 우선 (안정 정렬이라 동점은 최근순)
    parts: list[str] = []
    used = 0
    for note in usable:
        title = str(note.get("title") or "제목 없음").strip()
        body = note["body"].strip()[:NOTE_MAX_CHARS]
        entry = f"[내 노트] {title}\n{body}"
        if used + len(entry) > NOTES_MAX_CHARS:
            entry = entry[: max(0, NOTES_MAX_CHARS - used)]
            if len(entry) < 40:
                break
        parts.append(entry)
        used += len(entry)
        if used >= NOTES_MAX_CHARS:
            break
    return "\n\n".join(parts)
