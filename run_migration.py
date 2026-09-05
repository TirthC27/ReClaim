import os
import psycopg2

db_url = 'postgresql://postgres:B0tSCKqyjEiDfvSd@aws-0-ap-south-1.pooler.supabase.com:6543/postgres'

with open('app/migrations/015_bundle_offer_split_fulfillment.sql', 'r') as f:
    sql = f.read()

conn = psycopg2.connect(db_url)
cur = conn.cursor()
try:
    cur.execute(sql)
    conn.commit()
    print('Migration executed successfully.')
except Exception as e:
    print('Migration failed:', e)
finally:
    cur.close()
    conn.close()

