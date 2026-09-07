import sys
sys.path.insert(0, ".")
from sqlalchemy import text, inspect
from shared_lib.models import engine

insp = inspect(engine)
cols = [c["name"] for c in insp.get_columns("bots")]
print("before:", cols)
if "last_error" not in cols:
    with engine.connect() as c:
        c.execute(text("ALTER TABLE bots ADD COLUMN last_error TEXT"))
        c.commit()
    cols2 = [c["name"] for c in inspect(engine).get_columns("bots")]
    print("after:", cols2)
else:
    print("last_error already exists")
