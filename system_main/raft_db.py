import os
import sqlite3
import threading
import datetime
import zoneinfo
from pysyncobj import SyncObj, replicated, SyncObjConf

class RaftDB(SyncObj):
    """Database wrapper that integrates with Raft consensus algorithm"""
    
    def __init__(self, self_address, other_addresses, db_path):
        """Initialize the Raft consensus database wrapper"""
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
        
        # Initialize database connection - IMPORTANT: using __ prefix to make non-serialized
        self.__db_path = db_path
        self.__conn = None
        self.__conn_lock = threading.Lock()

        # Replicated state
        self._active_users = {}  # Track active/logged in users
        
        # Initialize the database
        self.__init_db()
    
    def __get_connection(self):
        """Get a thread-local database connection"""
        if self.__conn is None:
            self.__conn = sqlite3.connect(self.__db_path, check_same_thread=False)
            self.__conn.row_factory = sqlite3.Row
            self.__conn.execute("PRAGMA foreign_keys = ON")
        return self.__conn
    
    def __init_db(self):
        """Initialize the database schema"""
        c = self.__get_connection()
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
        """Close the database connection"""
        if self.__conn is not None:
            with self.__conn_lock:
                self.__conn.close()
                self.__conn = None
    
    # Replicated write operations (will be synchronized through Raft)
    
    @replicated
    def create_user(self, username, password_hash, display_name):
        """Create a new user (replicated operation)"""
        try:
            with self.__conn_lock:
                c = self.__get_connection()
                c.execute("""
                INSERT INTO users (username, password_hash, display_name)
                VALUES (?, ?, ?)""", (username, password_hash, display_name))
                c.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    @replicated
    def delete_user(self, username):
        """Delete a user by username (replicated operation)"""
        user_row = self.get_user_by_username(username)
        if not user_row:
            return False
        
        user_id = user_row["id"]
        with self.__conn_lock:
            c = self._get_connection()
            cur = c.cursor()
            cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
            deleted_count = cur.rowcount
            c.commit()
        
        # Also remove from active users if present
        if username in self._active_users:
            del self._active_users[username]
            
        return (deleted_count > 0)
    
    @replicated
    def create_message(self, sender_username, receiver_username, content):
        """Create a new message (replicated operation)"""
        sender_row = self.get_user_by_username(sender_username)
        if not sender_row:
            return False
        
        receiver_row = self.get_user_by_username(receiver_username)
        if not receiver_row:
            return False
        
        sender_id = sender_row["id"]
        receiver_id = receiver_row["id"]
        
        eastern = zoneinfo.ZoneInfo("America/New_York")
        timestamp = datetime.datetime.now(eastern).isoformat()
        
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            cur.execute("""
                INSERT INTO messages (sender_id, receiver_id, content, timestamp, read_status)
                VALUES (?, ?, ?, ?, 0)""", (sender_id, receiver_id, content, timestamp))
            c.commit()
        return True
    
    @replicated
    def mark_message_read(self, message_id, username):
        """Mark a message as read (replicated operation)"""
        user_row = self.get_user_by_username(username)
        if not user_row:
            return False
        
        receiver_id = user_row["id"]
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            cur.execute("""
                UPDATE messages
                SET read_status = 1
                WHERE id = ? AND receiver_id = ?""", (message_id, receiver_id))
            c.commit()
            return (cur.rowcount > 0)
    
    @replicated
    def delete_message(self, message_id, username):
        """Delete a message (replicated operation)"""
        user_row = self.get_user_by_username(username)
        if not user_row:
            return False
        
        user_id = user_row["id"]
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            cur.execute("""
                DELETE FROM messages
                WHERE id = ?
                AND (sender_id = ? OR receiver_id = ?)""", (message_id, user_id, user_id))
            c.commit()
            return (cur.rowcount > 0)
    
    # User session management (replicated)
    
    @replicated
    def user_login(self, username):
        """Mark a user as logged in (replicated operation)"""
        self._active_users[username] = True
        return True
    
    @replicated
    def user_logout(self, username):
        """Mark a user as logged out (replicated operation)"""
        if username in self._active_users:
            del self._active_users[username]
            return True
        return False
    
    # Non-replicated read-only operations
    
    def get_user_by_username(self, username):
        """Get a user by username (read-only operation)"""
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            cur.execute("SELECT * FROM users WHERE username = ?", (username,))
            return cur.fetchone()
    
    def list_users(self, pattern="*"):
        """List users matching a pattern (read-only operation)"""
        sql_pattern = pattern.replace("*", "%").replace("?", "_")
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            cur.execute("SELECT username, display_name FROM users WHERE username LIKE ?", (sql_pattern,))
            rows = cur.fetchall()
            return [(row["username"], row["display_name"]) for row in rows]
    
    def get_messages_for_user(self, username, only_unread=False, limit=None):
        """Get messages for a user (read-only operation)"""
        user_row = self.get_user_by_username(username)
        if not user_row:
            return []
        
        receiver_id = user_row["id"]
        base_query = """
        SELECT 
            messages.id,
            messages.sender_id,
            messages.receiver_id,
            messages.content,
            messages.timestamp,
            messages.read_status,
            sender.username AS sender_username
        FROM messages
        JOIN users AS sender ON sender.id = messages.sender_id
        WHERE messages.receiver_id = ?
        """
        
        if only_unread:
            base_query += " AND messages.read_status = 0"
        
        base_query += " ORDER BY messages.timestamp DESC"
        
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            
            if limit is not None and isinstance(limit, int) and limit > 0:
                base_query += " LIMIT ?"
                cur.execute(base_query, (receiver_id, limit))
            else:
                cur.execute(base_query, (receiver_id,))
            
            return cur.fetchall()
    
    def get_num_unread_messages(self, username):
        """Get the number of unread messages for a user (read-only operation)"""
        user_row = self.get_user_by_username(username)
        if not user_row:
            return 0
        
        receiver_id = user_row["id"]
        with self.__conn_lock:
            c = self.__get_connection()
            cur = c.cursor()
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM messages
                WHERE receiver_id = ? AND read_status = 0""", (receiver_id,))
            row = cur.fetchone()
            return row["cnt"] if row else 0
    
    def is_user_active(self, username):
        """Check if a user is currently active (logged in)"""
        return username in self._active_users
