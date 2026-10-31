# =============================================================================
# routers/shop.py: 코인샵 (보유/구매/착용)
# 아이템 가격·판매 여부는 app/data/shop_catalog.json(프론트 카탈로그에서 추출)을 기준으로 서버가 검증한다.
# =============================================================================
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import User, UserItem, UserState
from app.schemas import BuyRequest, EquipRequest, ShopStateOut
from app.services.coin_service import get_or_create_character_state

router = APIRouter(prefix="/api/shop", tags=["shop"])

CATALOG: dict = json.loads((Path(__file__).resolve().parent.parent / "data" / "shop_catalog.json").read_text(encoding="utf-8"))
DEFAULT_ITEM_IDS = [item_id for item_id, item in CATALOG.items() if item["default"]]


def _owned(db: Session, user_id: int) -> list[str]:
    rows = db.query(UserItem.item_id).filter(UserItem.user_id == user_id).all()
    return sorted(set(DEFAULT_ITEM_IDS) | {row[0] for row in rows})


def _state(db: Session, user: User) -> ShopStateOut:
    character = get_or_create_character_state(db, user.id)
    row = db.get(UserState, (user.id, "equipment"))
    equipped = row.data if row and isinstance(row.data, dict) else {}
    owned = _owned(db, user.id)
    equipped = {slot: item for slot, item in equipped.items() if item in owned}
    return ShopStateOut(coin_balance=character.coin_balance, owned_item_ids=owned, equipped_items=equipped)


@router.get("", response_model=ShopStateOut)
def get_shop(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _state(db, current_user)


@router.post("/buy", response_model=ShopStateOut)
def buy(payload: BuyRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = CATALOG.get(payload.item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="아이템을 찾을 수 없습니다.")
    if not item["available"]:
        raise HTTPException(status_code=400, detail="아직 판매하지 않는 아이템입니다.")
    if payload.item_id in _owned(db, current_user.id):
        raise HTTPException(status_code=409, detail="이미 보유한 아이템입니다.")
    character = get_or_create_character_state(db, current_user.id)
    if character.coin_balance < item["price"]:
        raise HTTPException(status_code=400, detail="코인이 부족합니다.")
    character.coin_balance -= item["price"]
    db.add(UserItem(user_id=current_user.id, item_id=payload.item_id))
    db.commit()
    return _state(db, current_user)


@router.put("/equipment", response_model=ShopStateOut)
def set_equipment(payload: EquipRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned = set(_owned(db, current_user.id))
    for item_id in payload.equipped_items.values():
        if item_id not in owned or not CATALOG.get(item_id, {}).get("available"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="보유하지 않은 아이템은 착용할 수 없습니다.")
    row = db.get(UserState, (current_user.id, "equipment"))
    if row is None:
        db.add(UserState(user_id=current_user.id, key="equipment", data=payload.equipped_items))
    else:
        row.data = payload.equipped_items
    db.commit()
    return _state(db, current_user)
