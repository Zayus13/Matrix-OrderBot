import os
import io
import pytest
from pathlib import Path
from freezegun import freeze_time

pytestmark = pytest.mark.asyncio

def _get_callbacks(client):
    return client._event_callbacks, client._resp_callbacks

async def test_construct_creates_store_dir(bot_instance, temp_env):
    store = Path(os.environ["MSTORE"]).resolve()
    assert store.exists()
    assert store.is_dir()
    assert bot_instance.storage_path == str(store)
    assert bot_instance.batch_store_path.endswith("multi_room_bot_store")
    assert isinstance(bot_instance.client, object)

async def test_connect_sets_default_dbpath_and_closes_client(bot_instance, db_session):
    os.environ.pop("DBPATH", None)

    await bot_instance.connect()

    assert "DBPATH" in os.environ
    assert os.environ["DBPATH"].startswith("sqlite:///")

    client = bot_instance.client
    assert client.calls["login"] == ["secret"]
    assert client.calls["close"] == 1
    assert client.calls["load_store"] == 1

async def test_connect_encryption_key_bootstrap(bot_instance, db_session):
    await bot_instance.connect()
    c = bot_instance.client
    assert c.calls["keys_upload"] == 1
    assert c.calls["keys_query"] == 1
    assert c.calls["keys_claim"] == 1

async def test_connect_loads_next_batch_when_file_exists(bot_instance, db_session, tmp_path):
    token_path = Path(bot_instance.batch_store_path)
    token_path.write_text("SAVED_TOKEN")

    await bot_instance.connect()
    assert bot_instance.client.next_batch == "SAVED_TOKEN"

async def test_callbacks_registered(bot_instance, db_session):
    await bot_instance.connect()
    ev_cbs, resp_cbs = bot_instance.client._event_callbacks, bot_instance.client._resp_callbacks

    ev_names = {cb[0].__name__ for cb in ev_cbs}
    assert {"on_invite", "handle_registration_msg", "on_encrypted"} <= ev_names

    resp_names = {cb[0].__name__ for cb in resp_cbs}
    assert {"sync", "check_for_leaves", "save_next_batch"} <= resp_names

async def test_save_next_batch_writes_file(bot_instance, db_session):
    await bot_instance.connect()
    await bot_instance.save_next_batch(type("R", (), {"next_batch": "NB_TOKEN"})())
    assert Path(bot_instance.batch_store_path).read_text() == "NB_TOKEN"

async def test_on_invite_joins_and_welcomes(bot_instance, db_session):
    await bot_instance.connect()
    room = type("R", (), {"room_id": "!abc:server", "display_name": "R"})()
    event = type("E", (), {"state_key": "@bot", "sender": "@alice"})()
    bot_instance.client.user = "@bot"
    await bot_instance.on_invite(room, event)

    c = bot_instance.client
    assert "!abc:server" in bot_instance.joined_rooms
    assert c.calls["join"] == ["!abc:server"]
    assert len(c.calls["room_send"]) == 1
    (room_id, msgtype, content) = c.calls["room_send"][0]
    assert room_id == "!abc:server"
    assert content["body"] == "Hello!"

async def test_on_invite_ignores_if_not_for_bot(bot_instance, db_session):
    await bot_instance.connect()
    room = type("R", (), {"room_id": "!abc:server", "display_name": "R"})()
    event = type("E", (), {"state_key": "@someoneelse", "sender": "@alice"})()
    bot_instance.client.user = "@bot"
    await bot_instance.on_invite(room, event)

    assert "!abc:server" not in bot_instance.joined_rooms
    assert bot_instance.client.calls["join"] == []

async def test_sync_reads_active_rooms_from_db(bot_instance, db_session):
    from orderbot.db_classes import Rooms
    active = Rooms(room_id="!active:server", name="Active", is_active=True)
    db_session.add(active)
    db_session.commit()

    await bot_instance.connect()
    bot_instance.joined_rooms = ["!active:server"]

    resp = type("Resp", (), {"rooms": type("RoomsX", (), {"join": {}, "invite": {}})()})()
    await bot_instance.sync(resp)
    assert "!active:server" in bot_instance.registered_rooms

async def test_check_for_leaves_removes_joined(bot_instance, db_session):
    await bot_instance.connect()
    bot_instance.joined_rooms = ["!leave:server", "!stay:server"]
    leave_resp = type("Resp", (), {
        "rooms": type("Rooms", (), {"leave": {"!leave:server": object()}})()
    })()
    await bot_instance.check_for_leaves(leave_resp)
    assert bot_instance.joined_rooms == ["!stay:server"]

async def test_on_encrypted_logs_decrypted(bot_instance, db_session, capsys):
    await bot_instance.connect()
    room = type("R", (), {"room_id": "!r:server", "display_name": "Name"})()
    event = type("E", (), {"sender": "@alice"})()
    await bot_instance.on_encrypted(room, event)
    assert len(bot_instance.client.calls["decrypt_event"]) == 1

async def test_on_encrypted_handles_errors(bot_instance, db_session, monkeypatch):
    await bot_instance.connect()
    async def boom(event):
        raise RuntimeError("nope")
    monkeypatch.setattr(bot_instance.client, "decrypt_event", boom)
    room = type("R", (), {"room_id": "!r:server", "display_name": "Name"})()
    event = type("E", (), {"sender": "@alice"})()
    await bot_instance.on_encrypted(room, event)

async def test_handle_registration_flow(bot_instance, db_session):
    await bot_instance.connect()
    room = type("R", (), {"room_id": "!reg:server", "display_name": "Reg"})()

    event = type("E", (), {"sender": "@alice", "body": "!ob register"})()
    await bot_instance.handle_registration_msg(room, event)

    assert "!reg:server" in bot_instance.registered_rooms
    assert any("registered successfully" in sent[2]["body"] for sent in bot_instance.client.calls["room_send"])

    await bot_instance.handle_registration_msg(room, event)
    assert any("already registered" in sent[2]["body"] for sent in bot_instance.client.calls["room_send"])

    event_unreg = type("E", (), {"sender": "@alice", "body": "!ob unregister"})()
    await bot_instance.handle_registration_msg(room, event_unreg)
    assert "!reg:server" not in bot_instance.registered_rooms
    assert any("unregistered successfully" in sent[2]["body"] for sent in bot_instance.client.calls["room_send"])

async def test_handle_registration_ignores_self(bot_instance, db_session):
    await bot_instance.connect()
    bot_instance.mxid = "@bot"
    room = type("R", (), {"room_id": "!r:server", "display_name": "D"})()
    event = type("E", (), {"sender": "@bot", "body": "!ob register"})()
    await bot_instance.handle_registration_msg(room, event)
    assert "!r:server" not in bot_instance.registered_rooms
    assert bot_instance.client.calls["room_send"] == []

async def test_listen_calls_sync_forever(bot_instance, db_session):
    await bot_instance.connect()
    await bot_instance.listen()
    called = bot_instance.client.calls["sync_forever"]
    assert called and called[0]["timeout"] == 10000 and called[0]["full_state"] is False
