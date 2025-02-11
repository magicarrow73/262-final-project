import os
import sqlite3

conn = None

def get_connection():
    """
    Returns a global SQLite connection so we have the same database across all calls
    """
    global conn
    if conn is None:
        db_path = os.getenv("CHAT_DB_PATH", "chat.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    Creates the 'users' table if it does not exist
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
    conn.commit()

def create_user(username: str, password_hash: str, display_name: str) -> bool:
    """
    Insert a new user
    Return True if successful and False if username is taken
    """
    c = get_connection()
    try:
        c.execute("""
        INSERT INTO users (username, password_hash, display_name)
        VALUES (?, ?, ?)
        """, (username, password_hash, display_name))
        c.commit()
        return True
    
    except sqlite3.IntegrityError:
        # raise IntegrityError if username is already being used
        # in this case should not allow to create a new user
        print("Username already taken!")
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
    """
    # First, see if user exists
    row = get_user_by_username(username)
    if not row:
        # User not found
        print("User not found!")
        return False

    user_id = row["id"]
    c = get_connection()
    cur = c.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    
    # check if any rows were deleted. Should be 1 if user was found.
    deleted_count = cur.rowcount
    c.commit()
    return deleted_count > 0

def create_message():
    # TODO
    pass

def list_users(pattern="*"):
    """
    List all users matching a wildcard pattern.
    
    - Uses standard wildcard syntax:
      - `*` → Matches any number of characters (in SQL, `%`)
      - `?` → Matches exactly one character (in SQL, `_`)
    
    Returns a list of tuples (username, display_name).
    """
    
    # Convert standard wildcards (* → %, ? → _)
    sql_pattern = pattern.replace("*", "%").replace("?", "_")

    c = get_connection()
    cur = c.cursor()
    
    # Query for users with pattern
    cur.execute("SELECT username, display_name FROM users WHERE username LIKE ?", (sql_pattern,))
    
    rows = cur.fetchall()
    c.close()
    
    return [(row["username"], row["display_name"]) for row in rows]
    
def get_messages_for_user(username: str):
    # TODO
    pass

def get_num_unread_messages(username: str):
    # TODO
    pass
def mark_message_read():
    # TODO
    pass

def delete_message():
    # TODO
    pass

def close_db():
    """
    Manually close the global connection
    """
    global conn
    if conn is not None:
        conn.close()
        conn = None
