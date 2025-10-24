from orderbot.orderbot import loglevel
import logging as log


loglevel = log.DEBUG
log.basicConfig(format="%(levelname)s|%(asctime)s: %(message)s", level=log.DEBUG)

class MultiRoomOrderbot:
    def __init__(self):
        self.bots = {}

    def add_bot(self, room_id, bot_instance):
        self.bots[room_id] = bot_instance

    async def connect_all(self):
        for room_id, bot in self.bots.items():
            log.info(f"Connecting bot for room {room_id}")
            await bot.connect()