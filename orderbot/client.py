import os
import logging as log
from contextlib import suppress

from nio import AsyncClient, InviteMemberEvent, RoomMemberEvent

from orderbot.db_classes import setup_db

loglevel = log.DEBUG
log.basicConfig(format="%(levelname)s|%(asctime)s: %(message)s", level=log.DEBUG)
log.getLogger("nio").setLevel(log.INFO)
log.getLogger("nio.client").setLevel(log.INFO)
log.getLogger("nio.responses").setLevel(log.INFO)

class MultiRoomOrderbot:
    def __init__(self):
        self.homeserver = os.environ.get("MSERVER")
        self.mxid = os.environ.get("MUSERNAME")
        self.storage_path = os.environ.get("MSTORE", ".\\multi_room_store\\")
        self.client = AsyncClient(self.homeserver, "@" + self.mxid, store_path=self.storage_path, device_id="MULTIROOMBOT")
        self.session = None
        self.joined_rooms = []
        self.registered_rooms = {}
        self.init = False

    async def connect(self):
        try:
            #database
            self.session = setup_db(os.environ["DBPATH"])
            log.info(await self.client.login(os.environ["MPASSWORD"]))

        except Exception as error:
            log.error(error)

        finally:
            with suppress(Exception):
                await self.client.close()

        self.client.add_event_callback(self.on_invite, InviteMemberEvent)
        self.client.add_response_callback(self.sync)
        self.client.add_response_callback(self.check_for_leaves)


    async def handle_invites(self, room):
        if room.room_id not in self.joined_rooms:
            await self.client.join(room.room_id)
            self.joined_rooms.append(room.room_id)
            log.info(f"Joined invited room: {room.room_id}")
            # sent welcome message
            await self.client.room_send(
                room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"Hello!",
                },
            )
            log.debug(f"Current joined rooms after invite: {self.joined_rooms}")


    async def on_invite(self, room, event: InviteMemberEvent):
        if event.state_key != self.client.user:
            return

        log.info(f"Received invite to room {room.room_id} from {event.sender}")
        await self.handle_invites(room)

    async def sync(self, response):
        if not self.init:
            for room_id, room in response.rooms.join.items():
                self.joined_rooms.append(room_id)

            for room_id, room in response.rooms.invite.items():
                await self.handle_invites(room_id)

            self.init = True

    async def check_for_leaves(self, response):
        if not isinstance(response, list) and hasattr(response.rooms, 'leave'):
            for room_id, room in response.rooms.leave.items():
                if room_id in self.joined_rooms:
                    self.joined_rooms.remove(room_id)
                    log.info(f"Left room: {room_id}")




    async def listen(self):
        await self.client.sync_forever(timeout=10000, full_state=False,)


