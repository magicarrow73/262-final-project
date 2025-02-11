import os
import sqlite3

DB_PATH = os.getenv('CHAT_DB_PATH', 'chat.db')

def get_connection():
    """
    Opens a connection to our SQLite database. 
    If you use multiple threads, you can set check_same_thread=False.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # so we can access columns by name
    return conn

def init_db():
    """
    Creates the 'users' table if it doesn't exist.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

def create_user(username: str, password_hash: str, display_name: str) -> bool:
    """
    Insert a new user. Return True if successful, False if username is taken.
    """
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
        INSERT INTO users (username, password_hash, display_name)
        VALUES (?, ?, ?)
        """, (username, password_hash, display_name))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # If the username is already in use (unique constraint),
        # an IntegrityError is raised
        return False
    finally:
        conn.close()


def get_user_by_username(username: str):
    """
    Return the row for the given username, or None if not found.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    return row

def delete_user(username: str) -> bool:
    """
    Delete the user with given username, return True if found/deleted, else False.
    """
    # First, see if user exists
    row = get_user_by_username(username)
    if not row:
        return False

    user_id = row["id"]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    deleted_count = cur.rowcount
    conn.commit()
    conn.close()
    return deleted_count > 0

if __name__ == "__main__":
    init_db()
    # create a user
    from utils import hash_password

    pw_hash = hash_password("mypassword")

    created = create_user("alice", pw_hash, "Alice Smith")
    print("User created:", created)

    # check the user
    row = get_user_by_username("alice")
    print("Retrieved user:", row["username"], row["password_hash"], row["display_name"])

    # delete the user
    deleted = delete_user("alice")
    print("User deleted:", deleted)
