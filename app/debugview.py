import sqlite3
from app.config import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("\n===== QUESTIONS =====")
for row in conn.execute("SELECT * FROM questions"):
    print(dict(row))

print("\n===== SESSIONS =====")
for row in conn.execute("SELECT * FROM sessions"):
    print(dict(row))

print("\n===== QUESTION RESULTS =====")
for row in conn.execute("SELECT * FROM question_results"):
    print(dict(row))

conn.close()