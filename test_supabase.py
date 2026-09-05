from app.db.client import get_supabase
sb = get_supabase()
try:
    print(sb.rpc('exec_sql', {'query': 'SELECT 1'}).execute())
except Exception as e:
    print(e)

