import os
from pathlib import Path
import types
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker



class FakeConfig:
    def __init__(self, encryption_enabled=True):
        self.encryption_enabled = encryption_enabled

class FakeRoom:
    def __init__(self, room_id, display_name="Test Room"):
        self.room_id = room_id
        self.display_name = display_name

class FakeJoinedRooms:
    def __init__(self, join_dict=None, invite_dict=None, leave_dict=None):
        self.join = join_dict or {}
        self.invite = invite_dict or {}
        self.leave = leave_dict or {}

class FakeSyncResponse:
    def __init__(self, next_batch="NB", rooms=None):
        self.next_batch = next_batch
        self.rooms = rooms or FakeJoinedRooms()

class FakeInviteEvent:
    def __init__(self, sender="@user:server", state_key="@bot:server"):
        self.sender = sender
        self.state_key = state_key

class FakeTextEvent:
    def __init__(self, sender="@user:server", body="hello"):
        self.sender = sender
        self.body = body

class FakeMegolmEvent:
    def __init__(self, sender="@user:server"):
        self.sender = sender


class FakeAsyncClient:
    def __init__(self, homeserver, user, store_path=None, device_id=None, config=None):
        self.homeserver = homeserver
        self.user = user
        self.store_path = store_path
        self.device_id = device_id
        self.config = config or FakeConfig()
        self.olm_account_shared = False
        self.next_batch = None

        self._event_callbacks = []
        self._resp_callbacks = []

        self.calls = {
            "login": [],
            "close": 0,
            "load_store": 0,
            "keys_upload": 0,
            "keys_query": 0,
            "keys_claim": 0,
            "join": [],
            "room_send": [],
            "decrypt_event": [],
            "sync_forever": [],
        }

    async def login(self, password):
        self.calls["login"].append(password)
        return types.SimpleNamespace(access_token="tok")

    async def close(self):
        self.calls["close"] += 1

    def load_store(self):
        self.calls["load_store"] += 1

    async def keys_upload(self):
        self.calls["keys_upload"] += 1

    async def keys_query(self):
        self.calls["keys_query"] += 1

    async def keys_claim(self):
        self.calls["keys_claim"] += 1

    async def join(self, room_id):
        self.calls["join"].append(room_id)
        return types.SimpleNamespace(room_id=room_id)

    async def room_send(self, room_id, message_type, content):
        self.calls["room_send"].append((room_id, message_type, content))

    async def decrypt_event(self, event):
        self.calls["decrypt_event"].append(event)
        return types.SimpleNamespace(body="decrypted")

    def add_event_callback(self, func, event_type):
        self._event_callbacks.append((func, event_type))

    def add_response_callback(self, func, response_type):
        self._resp_callbacks.append((func, response_type))

    async def sync_forever(self, timeout, full_state):
        self.calls["sync_forever"].append({"timeout": timeout, "full_state": full_state})


@pytest.fixture
def fake_client_cls(monkeypatch):
    import orderbot.client as mod

    monkeypatch.setattr(mod, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(mod, "AsyncClientConfig", FakeConfig)
    monkeypatch.setattr(mod, "InviteMemberEvent", FakeInviteEvent)
    monkeypatch.setattr(mod, "RoomMessageText", FakeTextEvent)
    monkeypatch.setattr(mod, "MegolmEvent", FakeMegolmEvent)
    monkeypatch.setattr(mod, "SyncResponse", FakeSyncResponse)
    return FakeAsyncClient

@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("MSERVER", "https://matrix.example")
    monkeypatch.setenv("MUSERNAME", "bot")
    monkeypatch.setenv("MSTORE", str(store))
    monkeypatch.setenv("MPASSWORD", "secret")
    # leave DBPATH unset by default
    yield store

@pytest.fixture
def db_session(monkeypatch, tmp_path):
    from orderbot.db_classes import Rooms, setup_db as real_setup_db
    # Build our own engine / session but reuse Rooms metadata
    db_file = tmp_path / "test.sqlite"
    engine = create_engine(f"sqlite:///{db_file}")
    # create the Rooms table if not present
    Rooms.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def fake_setup_db(url):
        # ignore url passed; return our session
        return session

    import orderbot.client as mod
    monkeypatch.setattr(mod, "setup_db", fake_setup_db)
    return session

@pytest.fixture
def bot_instance(fake_client_cls, temp_env):
    from orderbot.client import MultiRoomOrderbot
    return MultiRoomOrderbot(load_all=False)