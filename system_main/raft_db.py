"""raft_db.py
================
SQLite-backed **replicated** database and auction state-machine driven by
:pypi:`pysyncobj` (Raft).

Two layers are provided:

* :class:`DBHelper` – thin wrapper around SQLite that handles schema creation
  and basic CRUD helpers.  It is **NOT** thread-safe by itself, so a private
  lock protects every DB interaction.
* :class:`RaftDB` – a :class:`pysyncobj.SyncObj` subclass that exposes high-level
  operations (user management, simple sealed-bid auctions, arbitrary SQL
  execution).  Methods that *mutate* state are decorated with
  :func:`pysyncobj.replicated`, meaning they are replicated via Raft before
  executing on each node.
"""
import sqlite3
import threading
import time
from pysyncobj import SyncObj, replicated, SyncObjConf

class DBHelper:
    """Thread-safe helper for **single-node** SQLite operations.

    Parameters
    ----------
    db_path
        Filesystem path of the SQLite DB.  The file is created on first use.
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
        """Close the underlying SQLite connection (idempotent)."""
        if self.__conn is not None:
            with self.__conn_lock:
                self.__conn.close()
                self.__conn = None

    # ─── Prevent pickle of locks & connections ─────────────────────────────────
    def __getstate__(self):
        st = self.__dict__.copy()
        st.pop('_DBHelper__conn_lock', None)
        st.pop('_DBHelper__conn', None)
        return st

    def __setstate__(self, st):
        self.__dict__.update(st)
        self.__conn_lock = threading.Lock()
        self.__conn = None

    def insert_user(self, username, password_hash, display_name):
        """Insert a new user row.

        Returns ``True`` on success, ``False`` if username already exists.
        """
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
        """Delete user by id; returns number of rows removed (0 or 1)."""
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted = cur.rowcount
            c.commit()
            return deleted

    def get_user_by_username(self, username):
        """Return user row for username or None if not found."""
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("SELECT * FROM users WHERE username = ?", (username,))
            return cur.fetchone()

class RaftDB(SyncObj):
    """Distributed chat / auction store backed by Raft‑replicated SQLite.

    Parameters
    ----------
    self_address
        host:port string for this node’s Raft endpoint.
    other_addresses
        List of host:port strings for peer nodes.
    db_path
        Local path of the SQLite file to use per node.
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
            logCompactionMinEntries=10**12,
            logCompactionMinTime=10**12,
        )
        super().__init__(self_address, other_addresses, conf)
        self.__db = DBHelper(db_path)

        # replicated in‑memory state
        self._active_users = {}      # username → True
        self._auctions     = {}      # auction_id → {deadline, item_name, bids, ended, result}

    def close(self):
        """Close the underlying SQLite connection (non‑replicated)."""
        self.__db.close()

    # ---------- replicated user/message methods ---------- #
    @replicated
    def create_user(self, username, password_hash, display_name):
        """Create a new user; returns *False* if username is already taken."""
        return self.__db.insert_user(username, password_hash, display_name)

    @replicated
    def delete_user(self, username):
        """Remove *username* and all dependent rows (messages)."""
        row = self.__db.get_user_by_username(username)
        if not row: return False
        deleted = self.__db.delete_user(row["id"])
        self._active_users.pop(username, None)
        return deleted > 0

    @replicated
    def user_login(self, username):
        """Mark user as *online* in the replicated set."""
        self._active_users[username] = True
        return True

    @replicated
    def user_logout(self, username):
        """Mark user as *offline*.  Returns ``False`` if user wasn’t active."""
        return self._active_users.pop(username, None) is not None

    # ---------- auction methods ---------- #
    @replicated
    def start_auction(self, auction_id, duration_seconds, item_name):
        """Create a new sealed‑bid auction.

        The auction closes after *duration_seconds* **wall‑clock** seconds.
        Returns ``False`` if *auction_id* already exists.
        """
        if auction_id in self._auctions:
            return False
        now = int(time.time())
        deadline = now + duration_seconds
        self._auctions[auction_id] = {
            "deadline":  deadline,
            "item_name": item_name,
            "bids":      [],
            "ended":     False,
            "result":    None
        }
        return True

    @replicated
    def submit_bid(self, auction_id, bidder_id, amount):
        """Place a bid; fail if auction expired or already ended."""
        a = self._auctions.get(auction_id)
        now = int(time.time())
        if not a or a["ended"] or now > a["deadline"]:
            return False
        a["bids"].append((bidder_id, amount))
        return True

    @replicated
    def end_auction(self, auction_id):
        """Manually close an auction and compute second‑price outcome."""
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
    
    @replicated
    def execute(self, sql: str, params: tuple = ()):
        """Replicated write query – issued identically on every node."""
        with self.__db._DBHelper__conn_lock:
            cur = self.__db._get_connection()
            cur.execute(sql, params)
            cur.commit()
        return True

    def query(self, sql: str, params: tuple = ()):
        """Run a read‑only query and return *all* rows as ``list``."""
        with self.__db._DBHelper__conn_lock:
            cur = self.__db._get_connection().execute(sql, params)
            return list(cur.fetchall())

    def query_one(self, sql: str, params: tuple = ()):
        """Return first row of a read‑only query or ``None``."""
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---------- read-only methods ---------- #
    def get_user_by_username(self, username):
        """Retrieve user row via underlying DBHelper (local read)."""
        return self.__db.get_user_by_username(username)

    def is_user_active(self, username):
        """Return ``True`` iff username is currently logged in."""
        return username in self._active_users

    def get_auction_result(self, auction_id):
        """Return (winner, winning_bid, price_paid) tuple or ``None``."""
        a = self._auctions.get(auction_id)
        if not a or not a["ended"]:
            return None
        return a["result"]

    def list_auctions(self):
        """Enumerate auctions → ``[(id, item, ended, deadline), …]``."""
        return [
            (aid, info["item_name"], info["ended"], info["deadline"])
            for aid, info in self._auctions.items()
        ]
