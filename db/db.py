# db/db.py
import sqlite3
import os
from datetime import datetime
from config import BASE_DB_DIR

def get_db_path(school_name):
    return os.path.join(BASE_DB_DIR, f"{school_name.lower()}_database.db")

def init_db(school_name):
    db_path = get_db_path(school_name)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        grade TEXT,
        subject TEXT,
        location TEXT UNIQUE,
        date_first_seen TEXT,
        price REAL,
        is_old INTEGER DEFAULT 0
    )
    ''')
    conn.commit()
    return conn

def add_file(conn, grade, subject, location, price):
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT id FROM files WHERE location = ?", (location,))
    if cursor.fetchone():
        cursor.execute("UPDATE files SET is_old = 0 WHERE location = ?", (location,))
    else:
        cursor.execute('''
            INSERT INTO files (grade, subject, location, date_first_seen, price)
            VALUES (?, ?, ?, ?, ?)
        ''', (grade, subject, location, today, price))
    conn.commit()


# Add to the bottom of db/db.py
def get_school_mode(school_name):
    conn = init_db(school_name)
    cursor = conn.cursor()
    # Create settings table if it doesn't exist
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("SELECT value FROM settings WHERE key = 'mode'")
    row = cursor.fetchone()
    conn.close()
    # Default to Duplex if not found
    return row[0] if row else "Duplex"

def set_school_mode(school_name, mode):
    conn = init_db(school_name)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('mode', ?)", (mode,))
    conn.commit()
    conn.close()