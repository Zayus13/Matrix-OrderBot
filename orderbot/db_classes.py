from sqlalchemy import (
    Column,
    Integer,
    String,
    DATETIME,
    ForeignKey,
    create_engine,
    Boolean,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session
from sqlalchemy.sql.functions import now

Base = declarative_base()


class Participant(Base):
    __tablename__ = "participants"
    pid = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    matrix_address = Column(String, unique=True)
    user_total = Column(Integer, default=0)
    cuts = relationship(
        "Cuts", backref="participants", lazy=True, cascade="all,delete-orphan"
    )
    is_active = Column(Boolean, default=True)


class DBOrder(Base):
    __tablename__ = "orders"
    oid = Column(Integer, primary_key=True)
    name = Column(String)
    total = Column(Integer)
    price = Column(Integer)
    tip = Column(Integer)
    timestamp = Column(DATETIME, default=now())
    cuts = relationship(
        "Cuts", backref="orders", lazy=True, cascade="all,delete-orphan"
    )


class Cuts(Base):
    __tablename__ = "cuts"
    cid = Column(Integer, primary_key=True)
    pid = Column(Integer, ForeignKey("participants.pid"))
    oid = Column(Integer, ForeignKey("orders.oid"))
    rid = Column(Integer, ForeignKey("rooms.rid"))
    cut = Column(Integer)
    name = Column(String)
    timestamp = Column(DATETIME, default=now())

class Rooms(Base):
    __tablename__ = "rooms"
    rid = Column(Integer, primary_key=True)
    room_id = Column(String, unique=True)
    name = Column(String)
    cuts = relationship(
        "Cuts", backref="rooms", lazy=True, cascade="all,delete-orphan"
    )
    is_active = Column(Boolean, default=True)
    is_dm = Column(Boolean, default=False)



def setup_db(path: str) -> Session:
    engine = create_engine(path)
    Base.metadata.create_all(engine)

    return sessionmaker(bind=engine)()

