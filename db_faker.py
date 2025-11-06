#!/usr/bin/env python3
import argparse
import random
from collections import defaultdict

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from faker import Faker

from orderbot.db_classes import Base, Participant, DBOrder, Cuts, Rooms


def make_unique(add_func, *, max_retries=10):
    for i in range(max_retries):
        try:
            return add_func()
        except IntegrityError:
            session.rollback()
            if i == max_retries - 1:
                raise


def seed_participants(session: Session, n: int, fake: Faker, matrix_domain: str) -> list[int]:
    ids = []
    for _ in range(n):
        def _do():
            name = fake.unique.name()
            mx = f"@{fake.unique.user_name()}:{matrix_domain}"
            p = Participant(name=name, matrix_address=mx, is_active=True)
            session.add(p)
            session.flush()
            ids.append(p.pid)
            return p
        make_unique(_do)
    session.commit()
    return ids


def seed_rooms(session: Session, n: int, fake: Faker) -> list[int]:
    ids = []
    for _ in range(n):
        def _do():
            r = Rooms(
                room_id=f"!{fake.unique.bothify(text='????????????:server')}",
                name=fake.unique.word(),
                is_active=True,
                is_dm=fake.pybool()
            )
            session.add(r)
            session.flush()
            ids.append(r.rid)
            return r
        make_unique(_do)
    session.commit()
    return ids


def seed_orders(session: Session, n: int, fake: Faker) -> list[int]:
    ids = []
    for _ in range(n):
        price = fake.pyint(min_value=500, max_value=5000)
        tip   = fake.pyint(min_value=0,   max_value=1000)
        total = price + tip
        o = DBOrder(
            name=fake.sentence(nb_words=3).rstrip("."),
            total=total,
            price=price,
            tip=tip,
        )
        session.add(o)
        session.flush()
        ids.append(o.oid)
    session.commit()
    return ids


def seed_cuts(session: Session, n: int, fake: Faker,
              participant_ids: list[int], order_ids: list[int], room_ids: list[int]) -> None:
    if not (participant_ids and order_ids and room_ids):
        return

    for _ in range(n):
        pid = random.choice(participant_ids)
        oid = random.choice(order_ids)
        rid = random.choice(room_ids)

        cut_amount = fake.pyint(min_value=100, max_value=3000)
        cut_name = fake.word()

        c = Cuts(
            pid=pid,
            oid=oid,
            rid=rid,
            cut=cut_amount,
            name=cut_name,
        )
        session.add(c)

    session.commit()


def update_participant_totals(session: Session) -> None:
    sums = defaultdict(int)
    rows = session.execute(select(Cuts.pid, Cuts.cut)).all()
    for pid, cut in rows:
        if pid is not None and cut is not None:
            sums[pid] += int(cut)

    # update
    participants = session.execute(select(Participant)).scalars().all()
    for p in participants:
        p.user_total = sums.get(p.pid, 0)

    session.commit()


def parse_args():
    ap = argparse.ArgumentParser(
        description="Seed database with dummy data for Participants, Orders, Rooms, and Cuts."
    )
    ap.add_argument("--db", default="",
                    help="SQLAlchemy database URL")
    ap.add_argument("--participants", type=int, default=10, help="Number of participants to create")
    ap.add_argument("--orders", type=int, default=10, help="Number of orders to create")
    ap.add_argument("--rooms", type=int, default=5, help="Number of rooms to create")
    ap.add_argument("--cuts", type=int, default=40, help="Number of cuts to create")
    ap.add_argument("--locale", default="en_GB", help="Faker locale")
    ap.add_argument("--matrix-domain", default="address.org",
                    help="Domain for matrix addresses")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    fake = Faker(args.locale)

    engine = create_engine(args.db)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        fake.unique.clear()

        print(f"→ Seeding Participants: {args.participants}")
        participant_ids = seed_participants(session, args.participants, fake, args.matrix_domain)

        print(f"→ Seeding Rooms: {args.rooms}")
        room_ids = seed_rooms(session, args.rooms, fake)

        print(f"→ Seeding Orders: {args.orders}")
        order_ids = seed_orders(session, args.orders, fake)

        print(f"→ Seeding Cuts: {args.cuts}")
        seed_cuts(session, args.cuts, fake, participant_ids, order_ids, room_ids)

        print("→ Updating participant user_total from cuts …")
        update_participant_totals(session)

        #sanity check
        p_cnt = session.scalar(select(func.count()).select_from(Participant))
        r_cnt = session.scalar(select(func.count()).select_from(Rooms))
        o_cnt = session.scalar(select(func.count()).select_from(DBOrder))
        c_cnt = session.scalar(select(func.count()).select_from(Cuts))

        print(f"Done. Participants={p_cnt}, Rooms={r_cnt}, Orders={o_cnt}, Cuts={c_cnt}")
