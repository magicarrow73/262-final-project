import os, importlib, sqlite3, datetime, zoneinfo
import pytest


def _reload_db(tmp_path):
    """
    Point CHAT_DB_PATH at a temp file, reload system_main.db so it
    opens a fresh global connection, and return the module object.
    """
    db_file = tmp_path / "smoke.sqlite"
    os.environ["CHAT_DB_PATH"] = str(db_file)
    import system_main.db as db
    importlib.reload(db)          # pick up the new env-var
    return db


def test_full_db_smoke(tmp_path):
    db = _reload_db(tmp_path)

    # --- bootstrap -----------------------------------------------------
    db.init_db()                          # create tables
    conn: sqlite3.Connection = db.get_connection()
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
    assert {"users", "messages"}.issubset(tables)

    # --- user CRUD -----------------------------------------------------
    assert db.create_user("alice", "hash", "Alice") is True
    assert db.create_user("alice", "hash", "Alice") is False   # duplicate
    row = db.get_user_by_username("alice")
    assert row["display_name"] == "Alice"

    # --- messaging flow -----------------------------------------------
    db.create_user("bob", "pw", "Bob")
    assert db.create_message("alice", "bob", "hi Bob") is True
    assert db.create_message("ghost", "bob", "boo") is False   # unknown sender

    msgs = db.get_messages_for_user("bob")
    assert len(msgs) == 1 and msgs[0]["content"] == "hi Bob"
    assert db.get_num_unread_messages("bob") == 1

    mid = msgs[0]["id"]
    assert db.mark_message_read(mid, "bob") is True
    assert db.get_num_unread_messages("bob") == 0

    # delete and ensure cascading
    assert db.delete_message(mid, "bob") is True
    assert db.get_messages_for_user("bob") == []

    # --- user delete cascades messages --------------------------------
    # send another then delete user
    db.create_message("alice", "bob", "bye")
    assert db.delete_user("alice") is True
    assert db.get_user_by_username("alice") is None
    assert db.get_messages_for_user("bob") == []

    db.close_db()
