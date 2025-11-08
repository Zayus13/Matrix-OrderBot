from sqlalchemy import select, distinct
from sqlalchemy.orm import Session
from .db_classes import Participant, Cuts, Rooms

def get_participant_by_matrix(session: Session, matrix_address: str):
    return session.scalar(select(Participant).where(Participant.matrix_address == matrix_address))

def get_rooms_for_user(session: Session, pid: int):
    stmt = (
        select(distinct(Rooms))
        .join(Cuts, Cuts.rid == Rooms.rid)
        .where(Cuts.pid == pid, Rooms.is_active.is_(True))
    )
    return session.scalars(stmt).all()
