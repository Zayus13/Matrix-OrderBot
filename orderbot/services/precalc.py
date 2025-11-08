from dataclasses import dataclass
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..db.db_classes import Cuts, Rooms
from ..db.crud import get_participant_by_matrix

@dataclass(frozen=True)
class RoomTotal:
    rid: int
    room_id: str
    room_name: str
    total_cut: int

def compute_user_totals_by_room(session: Session, matrix_address: str):
    participant = get_participant_by_matrix(session, matrix_address)
    if participant is None:
        return []

    stmt = (
        select(Rooms.rid, Rooms.room_id, Rooms.name, func.sum(Cuts.cut))
        .join(Cuts, Cuts.rid == Rooms.rid)
        .where(Cuts.pid == participant.pid, Rooms.is_active.is_(True))
        .group_by(Rooms.rid, Rooms.room_id, Rooms.name)
    )

    return [
        RoomTotal(rid, room_id, name, total_cut or 0)
        for rid, room_id, name, total_cut in session.execute(stmt)
    ]
