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
from pysyncobj import SyncObj, replicated, SyncObjConf

class DBHelper:
    """
    A helper class to manage SQLite operations. 
    It wraps around a SQLite database connection and provides thread-safe
    methods to create, read, update, and delete data. 
    
    This class ensures PySyncObj does NOT try to pickle the sqlite3.Connection
    by keeping the connection object non-serializable.
    """
    def __init__(self, db_path):
        """
        Initialize the DBHelper with a given path to the SQLite database file.

        :param db_path: The filesystem path to the SQLite database file.
        """
        self.__db_path = db_path
        self.__conn = None
        self.__conn_lock = threading.Lock()
        self._init_db()

    def _get_connection(self):
        """
        Internal method to retrieve the SQLite connection, creating one if necessary.

        :return: A SQLite connection object.
        """
        if self.__conn is None:
            self.__conn = sqlite3.connect(self.__db_path, check_same_thread=False)
            self.__conn.row_factory = sqlite3.Row
            self.__conn.execute("PRAGMA foreign_keys = ON")
        return self.__conn

    def _init_db(self):
        """
        Internal method to initialize the database schema if it doesn't exist.
        Creates 'users' and 'messages' tables with the appropriate schema.
        """
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
        """
        Close the database connection if it is active.
        """
        if self.__conn is not None:
            with self.__conn_lock:
                self.__conn.close()
                self.__conn = None

    # ---------- DB Methods ---------- #

    def insert_user(self, username, password_hash, display_name):
        """
        Insert a new user into the 'users' table.

        :param username: Unique username for the new user.
        :param password_hash: Hashed password string.
        :param display_name: Display name for the user.
        :return: True if the user was inserted successfully, False if username is taken.
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
        """
        Delete a user by their numeric ID.

        :param user_id: The unique ID of the user to delete.
        :return: The number of rows deleted (0 if none).
        """
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted_count = cur.rowcount
            c.commit()
            return deleted_count

    def insert_message(self, sender_id, receiver_id, content):
        """
        Insert a new message into the 'messages' table.

        :param sender_id: The user ID of the sender.
        :param receiver_id: The user ID of the receiver.
        :param content: The text content of the message.
        :return: True if the message was inserted successfully.
        """
        eastern = zoneinfo.ZoneInfo("America/New_York")
        timestamp = datetime.datetime.now(eastern).isoformat()
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("""
                INSERT INTO messages (sender_id, receiver_id, content, timestamp, read_status)
                VALUES (?, ?, ?, ?, 0)
            """, (sender_id, receiver_id, content, timestamp))
            c.commit()
        return True

    def mark_message_read(self, message_id, receiver_id):
        """
        Mark a message as read (read_status = 1).

        :param message_id: The unique ID of the message to update.
        :param receiver_id: The user ID of the receiver who is marking the message as read.
        :return: True if a message was updated, False otherwise.
        """
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("""
                UPDATE messages
                SET read_status = 1
                WHERE id = ? AND receiver_id = ?
            """, (message_id, receiver_id))
            c.commit()
            return (cur.rowcount > 0)

    def delete_message(self, message_id, user_id):
        """
        Delete a message if the user is either the sender or the receiver of the message.

        :param message_id: The unique ID of the message to delete.
        :param user_id: The user ID of whoever is attempting the delete.
        :return: True if the message was deleted, False otherwise.
        """
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("""
                DELETE FROM messages
                WHERE id = ?
                AND (sender_id = ? OR receiver_id = ?)
            """, (message_id, user_id, user_id))
            c.commit()
            return (cur.rowcount > 0)

    def get_user_by_username(self, username):
        """
        Retrieve a user's record by username.

        :param username: The username to query.
        :return: A sqlite3.Row if found, or None if not.
        """
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("SELECT * FROM users WHERE username = ?", (username,))
            return cur.fetchone()

    def list_users(self, pattern):
        """
        List users whose usernames match the given pattern. 
        Wildcard characters (* and ?) are transformed to SQLite patterns (% and _).

        :param pattern: A pattern string, e.g., "a*" to find users starting with "a".
        :return: A list of tuples (username, display_name).
        """
        sql_pattern = pattern.replace("*", "%").replace("?", "_")
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("SELECT username, display_name FROM users WHERE username LIKE ?", (sql_pattern,))
            rows = cur.fetchall()
            return [(row["username"], row["display_name"]) for row in rows]

    def get_messages_for_user(self, receiver_id, only_unread=False, limit=None):
        """
        Retrieve messages for a user, optionally filtering by unread status, and limiting the result set.

        :param receiver_id: The user ID of the message receiver.
        :param only_unread: If True, only retrieve unread messages. Default is False.
        :param limit: Optional numeric limit to cap the number of messages returned.
        :return: A list of sqlite3.Row objects containing message data.
        """
        base_query = """
        SELECT 
            m.id,
            m.sender_id,
            m.receiver_id,
            m.content,
            m.timestamp,
            m.read_status,
            sender.username AS sender_username
        FROM messages m
        JOIN users AS sender ON sender.id = m.sender_id
        WHERE m.receiver_id = ?
        """

        if only_unread:
            base_query += " AND m.read_status = 0"
        base_query += " ORDER BY m.timestamp DESC"

        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            if limit is not None and limit > 0:
                base_query += " LIMIT ?"
                cur.execute(base_query, (receiver_id, limit))
            else:
                cur.execute(base_query, (receiver_id,))
            return cur.fetchall()

    def get_unread_count(self, receiver_id):
        """
        Get the count of unread messages for a specific user.

        :param receiver_id: The user ID of the receiver.
        :return: An integer count of unread messages.
        """
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM messages
                WHERE receiver_id = ? AND read_status = 0
            """, (receiver_id,))
            row = cur.fetchone()
            return row["cnt"] if row else 0

class RaftDB(SyncObj):
    """
    Database wrapper that integrates with the Raft consensus algorithm using PySyncObj. 
    It replicates certain write operations (create, update, delete) across multiple nodes
    to ensure consistency. Read operations are local (non-replicated).
    """
    
    def __init__(self, self_address, other_addresses, db_path):
        """
        Initialize the Raft consensus database wrapper.

        :param self_address: The local node's address, e.g., "localhost:5000".
        :param other_addresses: A list of addresses for other nodes in the cluster.
        :param db_path: Filesystem path to the SQLite database file.
        """
        # Configure Raft with auto recovery
        conf = SyncObjConf(
            autoTick=True,
            appendEntriesUseBatch=True,
            dynamicMembershipChange=True,
            commandsQueueSize=100000,
            appendEntriesPeriod=0.05,        # Faster heartbeats
            raftMinTimeout=1.0,             # Must be > 3 * appendEntriesPeriod
            raftMaxTimeout=2.0,
            electionTimeout=5.0,            # Increased election timeout
            connectionRetryDelay=0.5,
            connectionTimeout=10.0,
            leaderFallbackTimeout=10.0,      # Increased leader fallback timeout
        )
        super().__init__(self_address, other_addresses, conf)
        self.__db = DBHelper(db_path)

        # Replicated state
        self._active_users = {}  # Track active/logged in users
    
    def close(self):
        """
        Close the underlying database connection.
        """
        self.__db.close()
    
    # Replicated write operations (will be synchronized through Raft)
    
    @replicated
    def create_user(self, username, password_hash, display_name):
        """
        Create a new user (replicated operation).

        :param username: Unique username for the new user.
        :param password_hash: Hashed password for the user.
        :param display_name: Display name for the user.
        :return: True if the user was created successfully, False if a user
                 with the same username already exists.
        """
        return self.__db.insert_user(username, password_hash, display_name)
    
    @replicated
    def delete_user(self, username):
        """
        Delete a user by their username (replicated operation). 
        This will also remove any messages sent or received by this user,
        since foreign key constraints are ON DELETE CASCADE.

        :param username: The username of the user to delete.
        :return: True if the user existed and was deleted, False otherwise.
        """
        row = self.__db.get_user_by_username(username)
        if not row:
            return False

        user_id = row["id"]
        deleted_count = self.__db.delete_user(user_id)

        if username in self._active_users:
            del self._active_users[username]
        return (deleted_count > 0)
    
    @replicated
    def create_message(self, sender_username, receiver_username, content):
        """
        Create a new message (replicated operation).

        :param sender_username: Username of the sender.
        :param receiver_username: Username of the receiver.
        :param content: Text content of the message.
        :return: True if the sender and receiver exist and the message was created,
                 False otherwise.
        """
        sender_row = self.__db.get_user_by_username(sender_username)
        if not sender_row:
            return False
        receiver_row = self.__db.get_user_by_username(receiver_username)
        if not receiver_row:
            return False

        return self.__db.insert_message(sender_row["id"], receiver_row["id"], content)
    
    @replicated
    def mark_message_read(self, message_id, username):
        """
        Mark a specific message as read (replicated operation).

        :param message_id: The unique ID of the message to mark as read.
        :param username: Username of the recipient marking the message as read.
        :return: True if the message was successfully marked as read, 
                 False if the user or message doesn't exist or belongs to another user.
        """
        user_row = self.__db.get_user_by_username(username)
        if not user_row:
            return False
        return self.__db.mark_message_read(message_id, user_row["id"])
    
    @replicated
    def delete_message(self, message_id, username):
        """
        Delete a message (replicated operation).

        :param message_id: The unique ID of the message to delete.
        :param username: The username of the user performing the deletion 
                         (sender or receiver).
        :return: True if the message was deleted, False otherwise.
        """
        user_row = self.__db.get_user_by_username(username)
        if not user_row:
            return False
        return self.__db.delete_message(message_id, user_row["id"])
    
    # User session management (replicated)
    
    @replicated
    def user_login(self, username):
        """
        Mark a user as logged in (replicated operation). 
        This is a simple in-memory flag, not persisted in the database.

        :param username: The username of the user who is logging in.
        :return: True once the user is marked as active in the cluster state.
        """
        self._active_users[username] = True
        return True
    
    @replicated
    def user_logout(self, username):
        """
        Mark a user as logged out (replicated operation).
        This is a simple in-memory flag, not persisted in the database.

        :param username: The username of the user who is logging out.
        :return: True if the user was active and is now removed, False otherwise.
        """
        if username in self._active_users:
            del self._active_users[username]
            return True
        return False
    
    # Non-replicated read-only operations
    
    def get_user_by_username(self, username):
        """
        Get a user record by username (local read-only operation).

        :param username: The username to query.
        :return: A sqlite3.Row containing user data if found, None otherwise.
        """
        return self.__db.get_user_by_username(username)
    
    def list_users(self, pattern="*"):
        """
        List all users matching a given pattern (local read-only operation).

        :param pattern: A pattern string. Defaults to "*" for all users.
        :return: A list of (username, display_name) tuples.
        """
        return self.__db.list_users(pattern)
    
    def get_messages_for_user(self, username, only_unread=False, limit=None):
        """
        Retrieve messages for a user (local read-only operation).

        :param username: The username of the receiver.
        :param only_unread: If True, only unread messages are returned. Default is False.
        :param limit: Optional integer limit on the number of messages returned.
        :return: A list of sqlite3.Row objects representing messages.
        """
        row = self.__db.get_user_by_username(username)
        if not row:
            return []
        return self.__db.get_messages_for_user(row["id"], only_unread, limit)
    
    def get_num_unread_messages(self, username):
        """
        Get the count of unread messages for a user (local read-only operation).

        :param username: The username for which to retrieve unread count.
        :return: Integer count of unread messages.
        """
        row = self.__db.get_user_by_username(username)
        if not row:
            return 0
        return self.__db.get_unread_count(row["id"])
    
    def is_user_active(self, username):
        """
        Check if a user is currently marked as active (logged in) in the cluster.

        :param username: The username to check.
        :return: True if the user is in the active users list, False otherwise.
        """
        return (username in self._active_users)
