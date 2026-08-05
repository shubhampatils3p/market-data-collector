from dotenv import load_dotenv
from database.db import get_connection, release_connection

load_dotenv()

try:
    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("SELECT version();")

    version = cursor.fetchone()

    print("\n✅ Connected Successfully!\n")
    print(version[0])

    cursor.close()

    release_connection(conn)

except Exception as e:
    print("\n❌ Connection Failed\n")
    print(e)