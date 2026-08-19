import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from shared_lib.crud import SessionLocal
from sqlalchemy import text

s = SessionLocal()
s.execute(text("DROP TABLE IF EXISTS qq_configs"))
s.execute(text("DROP TABLE IF EXISTS qq_event_logs"))
s.commit()
rows = s.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'qq_%'")).fetchall()
print("remaining qq tables:", rows)
s.close()
