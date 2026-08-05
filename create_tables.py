from pathlib import Path

from dotenv import load_dotenv

from database.db import get_connection, release_connection

load_dotenv()

conn = get_connection()

try:
    cursor = conn.cursor()

    schema = Path("database/schema.sql").read_text(encoding="utf-8")

    cursor.execute(schema)

    conn.commit()

    print("✅ Tables created successfully.")

    cursor.close()

finally:
    release_connection(conn)