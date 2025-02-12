import os
import sqlite3
import datetime, zoneinfo

conn = None

def get_connection():
    """
    Returns a global SQLite connection so we have the same database across all calls
    Sets foreign keys as ON so CASCADE works for deleting messages
    """
    global conn
    if conn is None:
        db_path = os.getenv("CHAT_DB_PATH", "chat.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON") #foreign key enforcement
    return conn

def init_db():
    """
    Creates the 'users' table and the 'messages' table if they do not exist
    """
    c = get_connection()
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

def close_db():
    """
    Manually close the global connection
    """
    global conn
    if conn is not None:
        conn.close()
        conn = None

### METHODS FOR USER OPERATIONS ###

def create_user(username: str, password_hash: str, display_name: str) -> bool:
    """
    Insert a new user
    Return True if successful and False if username is taken
    """
    c = get_connection()
    try:
        c.execute("""
        INSERT INTO users (username, password_hash, display_name)
        VALUES (?, ?, ?)""", (username, password_hash, display_name))
        c.commit()
        return True
    
    except sqlite3.IntegrityError:
        # raise IntegrityError if username is already being used
        # in this case should not allow to create a new user
        print("Username already taken. Please choose a new one.")
        return False

def get_user_by_username(username: str):
    """
    Return the row for the given username or None if not found
    """
    c = get_connection()
    cur = c.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    return row

def delete_user(username: str) -> bool:
    """
    Delete the user with given username
    Return True if found/deleted else False
    Delete messages to and from user using ON DELETE CASCADE
    """
    # First, see if user exists
    row = get_user_by_username(username)
    if not row:
        # User not found
        print("The user of interest was not found.")
        return False

    user_id = row["id"]
    c = get_connection()
    cur = c.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    
    # check if any rows were deleted. Should be 1 if user was found.
    deleted_count = cur.rowcount
    c.commit()
    return (deleted_count > 0)

def list_users(pattern="*"):
    """
    List all users matching a wildcard pattern, using standard wildcard syntax
    Returns list of tuples in the form (username, display_name)
    Wildcards: * matches any number of characters, ? matches exactly one character
    """
    #convert standard wildcards (* goes to % and ? goes to _)
    sql_pattern = pattern.replace("*", "%").replace("?", "_")
    c = get_connection()
    cur = c.cursor()
    #query for users with pattern
    cur.execute("SELECT username, display_name FROM users WHERE username LIKE ?", (sql_pattern,))
    
    rows = cur.fetchall()
    return [(row["username"], row["display_name"]) for row in rows]

### METHODS FOR MESSAGE OPERATIONS ###

def create_message(sender_username: str, receiver_username: str, content: str) -> bool:
    """
    Creates a new message from sender to receiver
    Sets timestamp automatically to current UTC time
    Returns True if successful and False if sender or receiver does not exist
    """
    c = get_connection()
    sender_row = get_user_by_username(sender_username)
    if not sender_row:
        print(f"Sender user '{sender_username}' not found, try a new user.")
        return False
    
    receiver_row = get_user_by_username(receiver_username)
    if not receiver_row:
        print(f"Receiver user '{receiver_username}' not found, try a new user.")
        return False

    sender_id = sender_row["id"]
    receiver_id = receiver_row["id"]
    eastern = zoneinfo.ZoneInfo("America/New_York")
    timestamp = datetime.datetime.now(eastern).isoformat()
    cur = c.cursor()
    cur.execute("""
        INSERT INTO messages (sender_id, receiver_id, content, timestamp, read_status)
        VALUES (?, ?, ?, ?, 0)""", (sender_id, receiver_id, content, timestamp))
    c.commit()
    return True
    
def get_messages_for_user(username: str, only_unread: bool = False):
    """
    Return all messages for the user
    If only_unread is True then return only messages where read_status = 0
    Ordered by descending timestamp so the newest messages are first
    """
    c = get_connection()
    user_row = get_user_by_username(username)
    if not user_row:
        print(f"User '{username}' not found, try a different user.")
        return []
    
    receiver_id = user_row["id"]
    base_query = "SELECT * FROM messages WHERE receiver_id = ?"
    params = [receiver_id]
    
    if only_unread:
        base_query += " AND read_status = 0"
    base_query += " ORDER BY timestamp DESC"
    
    cur = c.cursor()
    cur.execute(base_query, params)
    return cur.fetchall()

def get_num_unread_messages(username: str) -> int:
    """
    Return number of unread messages for a particular user
    """
    c = get_connection()
    user_row = get_user_by_username(username)
    if not user_row:
        print(f"User '{username}' not found, try a different user.")
        return 0
    
    receiver_id = user_row["id"]
    cur = c.cursor()
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM messages
        WHERE receiver_id = ? AND read_status = 0""", (receiver_id,))
    row = cur.fetchone()
    return row["cnt"] if row else 0

def mark_message_read(message_id: int, username: str) -> bool:
    """
    Mark a message as read if the user is the receiver
    Return True if a row was updated and False otherwise
    """
    c = get_connection()
    user_row = get_user_by_username(username)
    if not user_row:
        print(f"User '{username}' not found, try a different user.")
        return False

    receiver_id = user_row["id"]
    cur = c.cursor()
    cur.execute("""
        UPDATE messages
        SET read_status = 1
        WHERE id = ? AND receiver_id = ?""", (message_id, receiver_id))
    c.commit()
    return (cur.rowcount > 0)

def delete_message(message_id: int, username: str) -> bool:
    """
    Delete a message if the user is either the sender or the receiver
    Return True if a row was deleted and False otherwise
    """
    c = get_connection()
    user_row = get_user_by_username(username)
    if not user_row:
        print(f"User '{username}' not found, try a different user.")
        return False
    
    user_id = user_row["id"]
    cur = c.cursor()
    cur.execute("""
        DELETE FROM messages
        WHERE id = ?
          AND (sender_id = ? OR receiver_id = ?)""", (message_id, user_id, user_id))
    c.commit()
    return (cur.rowcount > 0)
