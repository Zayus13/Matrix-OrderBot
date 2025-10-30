import os
import logging as log
from contextlib import suppress

from os.path import exists
from pathlib import Path

from nio import AsyncClient, InviteMemberEvent, RoomMessageText, AsyncClientConfig, MegolmEvent, \
    LocalProtocolError, SyncResponse, JoinError

from sqlalchemy import select

from orderbot.db_classes import setup_db, Rooms
from orderbot.order_parser_class import ParserWrapper

loglevel = log.DEBUG
log.basicConfig(format="%(levelname)s|%(asctime)s: %(message)s", level=loglevel)

for logger_name in ["nio.client", "nio.store.sql", "peewee", "nio.responses", "sqlalchemy.engine", "nio.store.database",
                    "nio.crypto"]:
    logger = log.getLogger(logger_name)
    logger.setLevel(log.WARNING)

MAINTENANCE_INTERVAL = 10

class MultiRoomOrderbot:
    def __init__(self, load_all=False):
        self.homeserver = os.environ.get("MSERVER")
        self.mxid = os.environ.get("MUSERNAME")

        raw = os.environ.get("MSTORE", "./multi_room_store/")
        store_dir = Path(raw).expanduser().resolve()
        store_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = str(store_dir)
        self.batch_store_path = os.path.join(self.storage_path, "multi_room_bot_store")

        self.client = AsyncClient(self.homeserver,
                                  "@" + self.mxid,
                                  store_path=self.storage_path,
                                  device_id="MULTIROOMBOT",
                                  config=AsyncClientConfig(
                                      encryption_enabled=True,
                                  ))

        self.session = None

        self.joined_rooms = set()
        self.registered_rooms = {}
        self.room_types = {}

        self.init = False
        self.load_all = load_all

        self._sync_tick = -1
        self.run_maintenance = False

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

        if rid in self.joined_rooms:
            return False

        resp = await self.client.join(rid)
        if isinstance(resp, JoinError):
            log.error(f"Failed to join room {rid}: {resp.message}")
            return False

        self.joined_rooms.add(rid)
        log.info(f"Joined invited room: {rid}")
        log.debug(f"Current joined rooms after invite: {self.joined_rooms}")
        return True

    async def save_next_batch(self, response):
        if not isinstance(response, list) and hasattr(response, 'next_batch'):
            with open(self.batch_store_path, "w") as next_batch_token:
                next_batch_token.write(response.next_batch)
                log.debug("Saved next_batch token to file.")

    async def on_invite(self, room, event: InviteMemberEvent):
        if event.state_key != self.client.user:
            return
        log.info(f"Received invite to room {room.room_id} from {event.sender}")
        success = await self.handle_invites(room)
        self.run_maintenance = self.run_maintenance or success

    async def maintain_room_state(self):
        for room_id in list(self.joined_rooms):
            with suppress(Exception):
                member_resp = await self.client.joined_members(room_id)
                members = getattr(member_resp, "members", {}) or {}
                if len(members) <= 1:
                    with suppress(Exception):
                        await self.client.room_leave(room_id)
                    with suppress(Exception):
                        await self.client.room_forget(room_id)
                    self.joined_rooms.discard(room_id)
                    log.info(f"Left empty room: {room_id}")

        with suppress(Exception):
            direct_resp = await self.client.list_direct_rooms()
            direct_map = getattr(direct_resp, "rooms", {}) or {}
            dm_rooms = {r for rooms in direct_map.values() for r in rooms}
        if "dm_rooms" not in locals():
            dm_rooms = set()

        for rid in self.joined_rooms:
            self.room_types[rid] = "dm" if rid in dm_rooms else "room"

        for rid in list(self.room_types.keys()):
            if rid not in self.joined_rooms:
                self.room_types.pop(rid, None)

        log.info(
            f"Joined Rooms: {len(self.joined_rooms)}, "
            f"Registered Room: {len(self.registered_rooms)}"
        )
        log.debug(f"Room type map: {self.room_types}")

    async def sync(self, response):
        joined_resp = await self.client.joined_rooms()
        self.joined_rooms = set(getattr(joined_resp, "rooms", []) or [])

        stmt = select(Rooms.room_id).where(Rooms.is_active.is_(True))
        db_rooms = {rid for (rid,) in self.session.execute(stmt).all()}
        for room_id in db_rooms & self.joined_rooms:
            if room_id not in self.registered_rooms:
                self.registered_rooms[room_id] = None
                log.debug(f"Registered active room: {room_id}")

        invited = getattr(response, "rooms", None)
        if invited and hasattr(invited, "invite"):
            for rid, invite_info in invited.invite.items():
                with suppress(Exception):
                    success = await self.handle_invites(invite_info)
                    if success:
                        log.info(f"Joined new invited room: {rid}")
                        self.run_maintenance = True

        self._sync_tick += 1
        if self.run_maintenance or (self._sync_tick % MAINTENANCE_INTERVAL == 0):
            self._sync_tick = 0
            self.run_maintenance = False
            await self.maintain_room_state()

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

    async def send_text_message(self, room_id: str, body: str):
        return await self.client.room_send(
            room_id,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": body},
            ignore_unverified_devices=True,
        )

    async def handle_registration_msg(self, room, event: RoomMessageText):
        if event.sender == self.mxid:
            return

        room_id = room.room_id
        room_kind = self.room_types.get(room_id)
        is_registered = room_id in self.registered_rooms.keys()

        for raw_line in event.body.splitlines():
            message = raw_line.strip()
            if not message:
                continue

            log.debug(f"Registration message in room {room_id} from {event.sender}: {message}")
            m = message.lower()

            # --- REGISTER ---
            if m.startswith("!ob register"):
                if not is_registered and room_kind == "room":
                    self.registered_rooms[room_id] = ParserWrapper()
                    await self.send_text_message(room_id, f"Room {room_id} registered successfully by {event.sender}!")
                    log.info(f"Registered room {room_id} by {event.sender}")

                elif room_kind != "room":
                    await self.send_text_message(room_id, f"Room {room_id} is a direct message room.")
                    log.info(f"Room {room_id} cannot be registered as it is a DM.")
                else:
                    await self.send_text_message(room_id, f"Room {room_id} is already registered.")
                    log.info(f"Room {room_id} is already registered.")

            # --- UNREGISTER ---
            elif m.startswith("!ob unregister"):
                if is_registered:
                    del self.registered_rooms[room_id]
                    await self.send_text_message(room_id,
                                                 f"Room {room_id} unregistered successfully by {event.sender}!")
                    log.info(f"Unregistered room {room_id} by {event.sender}")
                else:
                    await self.send_text_message(room_id, f"Room {room_id} is not registered.")
                    log.info(f"Room {room_id} is not registered.")

    async def handle_order_msg(self, room, event: RoomMessageText):
        valid = True
        if valid:
            self.registered_rooms[room.room_id].parse_msg(event.body, direct=False)

    async def listen(self):
        await self.client.sync_forever(timeout=10000, full_state=False, )
