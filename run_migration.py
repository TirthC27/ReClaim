import os
import psycopg2
from urllib.parse import urlparse

supabase_url = "https://lefpbdeuxvzkkmmulxje.supabase.co"
password = "B0tSCKqyjEiDfvSd"

parsed = urlparse(supabase_url)
db_host = f"db.{parsed.netloc}"
db_url = f"postgresql://postgres:{password}@{db_host}:5432/postgres"

with open("app/migrations/007_cart_recovery.sql", "r") as f:
    sql = f.read()

conn = psycopg2.connect(db_url)
cur = conn.cursor()
try:
    cur.execute(sql)
    conn.commit()
    print("Migration executed successfully.")
except Exception as e:
    print("Migration failed:", e)
finally:
    cur.close()
    conn.close()
