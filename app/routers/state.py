# =============================================================================
# routers/state.py: 사용자별 JSON 상태 저장 (GET/PUT /api/state/{key})
# 프론트가 한 덩어리로 관리하는 데이터(과목·노트·시험·출결, 프로필·설정, 오답 북마크)를 보관한다.
# =============================================================================
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import User, UserState

router = APIRouter(prefix="/api/state", tags=["state"])

ALLOWED_KEYS = {"subjects", "profile", "wrong_meta", "equipment"}
MAX_STATE_BYTES = 2 * 1024 * 1024


def _check_key(key: str) -> None:
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=404, detail="알 수 없는 상태 키입니다.")


@router.get("/{key}")
def get_state(key: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_key(key)
    row = db.get(UserState, (current_user.id, key))
    return {"data": row.data if row else None}


@router.put("/{key}")
def put_state(
    key: str,
    body: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check_key(key)
    data = body.get("data")
    if data is None:
        raise HTTPException(status_code=400, detail="data가 필요합니다.")
    if len(str(data)) > MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="저장할 데이터가 너무 큽니다.")
    row = db.get(UserState, (current_user.id, key))
    if row is None:
        db.add(UserState(user_id=current_user.id, key=key, data=data))
    else:
        row.data = data
    db.commit()
    return {"ok": True}
