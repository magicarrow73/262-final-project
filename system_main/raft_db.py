"""
raft_db.py

This module provides a SQLite database helper (`DBHelper`) and a Raft-based
wrapper (`RaftDB`) for replicated state management using `pysyncobj`.
"""

import os
import sqlite3
import threading
import datetime
import zoneinfo
import time
from pysyncobj import SyncObj, replicated, SyncObjConf

class DBHelper:
    """
    A helper class to manage SQLite operations.
    """
    def __init__(self, db_path):
        self.__db_path = db_path
        self.__conn = None
        self.__conn_lock = threading.Lock()
        self._init_db()

    def _get_connection(self):
        if self.__conn is None:
            self.__conn = sqlite3.connect(self.__db_path, check_same_thread=False)
            self.__conn.row_factory = sqlite3.Row
            self.__conn.execute("PRAGMA foreign_keys = ON")
        return self.__conn

    def _init_db(self):
        c = self._get_connection()
        with self.__conn_lock:
            c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                read_status INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """)
            c.commit()

    def close(self):
        if self.__conn is not None:
            with self.__conn_lock:
                self.__conn.close()
                self.__conn = None

    def insert_user(self, username, password_hash, display_name):
        try:
            with self.__conn_lock:
                c = self._get_connection()
                c.execute("""
                INSERT INTO users (username, password_hash, display_name)
                VALUES (?, ?, ?)
                """, (username, password_hash, display_name))
                c.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_user(self, user_id):
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted = cur.rowcount
            c.commit()
            return deleted

    def insert_message(self, sender_id, receiver_id, content):
        eastern = zoneinfo.ZoneInfo("America/New_York")
        timestamp = datetime.datetime.now(eastern).isoformat()
        with self.__conn_lock:
            c = self._get_connection()
            c.execute("""
                INSERT INTO messages (sender_id, receiver_id, content, timestamp, read_status)
                VALUES (?, ?, ?, ?, 0)
            """, (sender_id, receiver_id, content, timestamp))
            c.commit()
        return True

    def mark_message_read(self, message_id, receiver_id):
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("""
                UPDATE messages SET read_status = 1
                WHERE id = ? AND receiver_id = ?
            """, (message_id, receiver_id))
            c.commit()
            return cur.rowcount > 0

    def delete_message(self, message_id, user_id):
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("""
                DELETE FROM messages
                WHERE id = ? AND (sender_id = ? OR receiver_id = ?)
            """, (message_id, user_id, user_id))
            c.commit()
            return cur.rowcount > 0

    def get_user_by_username(self, username):
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("SELECT * FROM users WHERE username = ?", (username,))
            return cur.fetchone()

    def list_users(self, pattern):
        sql_pat = pattern.replace("*", "%").replace("?", "_")
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("SELECT username, display_name FROM users WHERE username LIKE ?", (sql_pat,))
            rows = cur.fetchall()
            return [(r["username"], r["display_name"]) for r in rows]

    def get_messages_for_user(self, receiver_id, only_unread=False, limit=None):
        base = """
        SELECT m.id, m.sender_id, m.receiver_id, m.content, m.timestamp, m.read_status,
               sender.username AS sender_username
        FROM messages m
        JOIN users sender ON sender.id = m.sender_id
        WHERE m.receiver_id = ?
        """
        if only_unread:
            base += " AND m.read_status = 0"
        base += " ORDER BY m.timestamp DESC"
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            if limit:
                base += " LIMIT ?"
                cur.execute(base, (receiver_id, limit))
            else:
                cur.execute(base, (receiver_id,))
            return cur.fetchall()

    def get_unread_count(self, receiver_id):
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM messages WHERE receiver_id = ? AND read_status = 0",
                        (receiver_id,))
            row = cur.fetchone()
            return row["cnt"] if row else 0


class RaftDB(SyncObj):
    """
    Raft-backed DB wrapper.  Read methods are local, write methods are @replicated.
    """

    def __init__(self, self_address, other_addresses, db_path):
        conf = SyncObjConf(
            autoTick=True,
            appendEntriesUseBatch=True,
            dynamicMembershipChange=True,
            commandsQueueSize=100000,
            appendEntriesPeriod=0.05,
            raftMinTimeout=1.0,
            raftMaxTimeout=2.0,
            electionTimeout=5.0,
            connectionRetryDelay=0.5,
            connectionTimeout=10.0,
            leaderFallbackTimeout=10.0,
        )
        super().__init__(self_address, other_addresses, conf)
        self.__db = DBHelper(db_path)

        # replicated in‐memory state
        self._active_users = {}      # username → True
        self._auctions     = {}      # auction_id → {deadline, bids, ended, result}

    def close(self):
        self.__db.close()

    # ---------- replicated user/message methods (unchanged) ---------- #
    @replicated
    def create_user(self, username, password_hash, display_name):
        return self.__db.insert_user(username, password_hash, display_name)

    @replicated
    def delete_user(self, username):
        row = self.__db.get_user_by_username(username)
        if not row: return False
        deleted = self.__db.delete_user(row["id"])
        self._active_users.pop(username, None)
        return deleted > 0

    @replicated
    def create_message(self, s, r, content):
        sr = self.__db.get_user_by_username(s)
        rr = self.__db.get_user_by_username(r)
        if not sr or not rr: return False
        return self.__db.insert_message(sr["id"], rr["id"], content)

    @replicated
    def mark_message_read(self, mid, username):
        row = self.__db.get_user_by_username(username)
        if not row: return False
        return self.__db.mark_message_read(mid, row["id"])

    @replicated
    def delete_message(self, mid, username):
        row = self.__db.get_user_by_username(username)
        if not row: return False
        return self.__db.delete_message(mid, row["id"])

    @replicated
    def user_login(self, username):
        self._active_users[username] = True
        return True

    @replicated
    def user_logout(self, username):
        return self._active_users.pop(username, None) is not None

    # ---------- auction methods (new!) ---------- #

    @replicated
    def start_auction(self, auction_id, deadline_unix):
        if auction_id in self._auctions:
            return False
        self._auctions[auction_id] = {
            "deadline": deadline_unix,
            "bids": [],
            "ended": False,
            "result": None
        }
        return True

    @replicated
    def submit_bid(self, auction_id, bidder_id, amount):
        a = self._auctions.get(auction_id)
        now = int(time.time())
        if not a or a["ended"] or now > a["deadline"]:
            return False
        a["bids"].append((bidder_id, amount))
        return True

    @replicated
    def end_auction(self, auction_id):
        a = self._auctions.get(auction_id)
        if not a or a["ended"]:
            return False
        a["ended"] = True
        bids = sorted(a["bids"], key=lambda x: x[1], reverse=True)
        if not bids:
            a["result"] = ("", 0.0, 0.0)
        elif len(bids) == 1:
            a["result"] = (bids[0][0], bids[0][1], 0.0)
        else:
            w, wb = bids[0]
            price = bids[1][1]
            a["result"] = (w, wb, price)
        return True

    # ---------- read-only methods ---------- #

    def get_user_by_username(self, username):
        return self.__db.get_user_by_username(username)

    def list_users(self, pattern="*"):
        return self.__db.list_users(pattern)

    def get_messages_for_user(self, username, only_unread=False, limit=None):
        row = self.__db.get_user_by_username(username)
        if not row: return []
        return self.__db.get_messages_for_user(row["id"], only_unread, limit)

    def get_num_unread_messages(self, username):
        row = self.__db.get_user_by_username(username)
        if not row: return 0
        return self.__db.get_unread_count(row["id"])

    def is_user_active(self, username):
        return username in self._active_users

    def get_auction_result(self, auction_id):
        a = self._auctions.get(auction_id)
        if not a or not a["ended"]:
            return None
        return a["result"]
