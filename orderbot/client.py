import asyncio
import os
import logging as log
from contextlib import suppress
from os.path import exists
from pathlib import Path

from nio import AsyncClient, InviteMemberEvent, RoomMessageText, AsyncClientConfig, MegolmEvent, \
    LocalProtocolError, SyncResponse, JoinError
from sqlalchemy import select

from orderbot.db_classes import setup_db, Rooms

loglevel = log.DEBUG
log.basicConfig(format="%(levelname)s|%(asctime)s: %(message)s", level=loglevel)

for logger_name in ["nio.client", "nio.store.sql", "peewee", "nio.responses", "sqlalchemy.engine", "nio.store.database",
                    "nio.crypto"]:
    logger = log.getLogger(logger_name)
    logger.setLevel(log.WARNING)


class MultiRoomOrderbot:
    def __init__(self, load_all=False):
        self.homeserver = os.environ.get("MSERVER")
        self.mxid = os.environ.get("MUSERNAME")

        raw = os.environ.get("MSTORE", "./multi_room_store/")
        store_dir = Path(raw).expanduser().resolve()
        store_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = str(store_dir)
        self.batch_store_path = os.path.join(self.storage_path, "multi_room_bot_store")

        self.client = AsyncClient(self.homeserver, "@" + self.mxid, store_path=self.storage_path,
                                  device_id="MULTIROOMBOT", config=AsyncClientConfig(encryption_enabled=True))

        self.session = None

        self.joined_rooms = []
        self.registered_rooms = {}

        self.init = False
        self.load_all = load_all

    async def connect(self):
        try:
            if "DBPATH" not in os.environ:
                db_path = os.path.join(self.storage_path, "multi_room_bot_db.sqlite")
                os.environ["DBPATH"] = f"sqlite:///{db_path}"
                log.debug(f"DBPATH not found in environment, setting to default: {os.environ['DBPATH']}")
            else:
                log.debug(f"Using DBPATH from environment: {os.environ['DBPATH']}")

            self.session = setup_db(os.environ["DBPATH"])
            log.info(await self.client.login(os.environ["MPASSWORD"]))

        except Exception as error:
            log.error(error)

        finally:
            with suppress(Exception):
                await self.client.close()

        self.client.load_store()

        if self.client.config.encryption_enabled:
            if not self.client.olm_account_shared:
                await self.client.keys_upload()

            try:
                await self.client.keys_query()
                await self.client.keys_claim()

            except LocalProtocolError:
                log.debug("Keys already queried, skipping")

        if not self.load_all:
            if exists(self.batch_store_path):
                with open(self.batch_store_path, "r") as next_batch_token:
                    log.debug("Loading next_batch token from file.")
                    self.client.next_batch = next_batch_token.read()

        self.client.add_event_callback(self.on_invite, InviteMemberEvent)
        self.client.add_response_callback(self.sync, SyncResponse)
        self.client.add_response_callback(self.check_for_leaves, SyncResponse)
        self.client.add_event_callback(self.handle_registration_msg, RoomMessageText)
        self.client.add_event_callback(self.on_encrypted, MegolmEvent)
        self.client.add_response_callback(self.save_next_batch, SyncResponse)

    async def handle_invites(self, room):
        rid = room.room_id

        if rid in self.joined_rooms:#
            return

        resp = await self.client.join(rid)
        if isinstance(resp, JoinError):
            log.error(f"Failed to join room {rid}: {resp.message}")
            return

        self.joined_rooms.append(rid)
        log.info(f"Joined invited room: {rid}")
        log.debug(f"Current joined rooms after invite: {self.joined_rooms}")

    async def save_next_batch(self, response):
        if not isinstance(response, list) and hasattr(response, 'next_batch'):
            with open(self.batch_store_path, "w") as next_batch_token:
                next_batch_token.write(response.next_batch)
                log.debug("Saved next_batch token to file.")

    async def on_invite(self, room, event: InviteMemberEvent):
        if event.state_key != self.client.user:
            return

        log.info(f"Received invite to room {room.room_id} from {event.sender}")
        log.debug(event)
        await self.handle_invites(room)

    async def sync(self, response):
        if not self.init:
            for room_id, room in response.rooms.join.items():
                log.debug(response.rooms)
                self.joined_rooms.append(room_id)

            for room_id, room in response.rooms.invite.items():
                await self.handle_invites(room)

            self.init = True

        # do a db check, register rooms that are in the db
        stmt = select(Rooms.room_id).where(Rooms.is_active.is_(True))
        rooms = self.session.execute(stmt).all()
        for (room_id,) in rooms:
            if room_id in self.joined_rooms:
                if room_id not in self.registered_rooms:
                    self.registered_rooms[room_id] = None

    async def check_for_leaves(self, response):
        if not isinstance(response, list) and hasattr(response.rooms, 'leave'):
            for room_id, room in response.rooms.leave.items():
                if room_id in self.joined_rooms:
                    self.joined_rooms.remove(room_id)
                    log.info(f"Left room: {room_id}")

    async def on_encrypted(self, room, event: MegolmEvent):
        try:
            decrypted = await self.client.decrypt_event(event)
            if decrypted and hasattr(decrypted, "body"):
                log.info(f"[{room.display_name}] {event.sender}: {decrypted.body}")
        except Exception as e:
            log.warning(f"Could not decrypt message in {room.room_id}: {e}")

    async def handle_registration_msg(self, room, event: RoomMessageText):
        if event.sender == self.mxid:
            return

        inp = event.body.split("\n")
        for message in inp:
            message = message.strip()
            log.debug(f"Registration message in room {room.room_id} from {event.sender}: {message}")
            if message.lower().startswith("!ob register"):
                if room.room_id not in self.registered_rooms:
                    self.registered_rooms[room.room_id] = None  # todo: add parser mapping
                    await self.client.room_send(
                        room.room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text",
                            "body": f"Room {room.room_id} registered successfully by {event.sender}!",
                        },
                    )
                    log.info(f"Registered room {room.room_id} by {event.sender}")
                    # but room into database
                    new_room = Rooms(room_id=room.room_id, name=room.display_name, is_active=True)
                    self.session.add(new_room)
                else:
                    await self.client.room_send(
                        room.room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text",
                            "body": f"Room {room.room_id} is already registered.",
                        },
                    )
                    log.info(f"Room {room.room_id} is already registered.")

            if message.lower().startswith(
                    "!ob unregister"):  # todo: check balance in database, add if balance is zero -> delete from db else only unregister + final balance.
                if room.room_id in self.registered_rooms:
                    del self.registered_rooms[room.room_id]
                    await self.client.room_send(
                        room.room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text",
                            "body": f"Room {room.room_id} unregistered successfully by {event.sender}!",
                        },
                    )
                    log.info(f"Unregistered room {room.room_id} by {event.sender}")
                else:
                    await self.client.room_send(
                        room.room_id,
                        message_type="m.room.message",
                        content={
                            "msgtype": "m.text",
                            "body": f"Room {room.room_id} is not registered.",
                        },
                    )
                    log.info(f"Room {room.room_id} is not registered.")

    async def listen(self):
        await self.client.sync_forever(timeout=10000, full_state=False, )
