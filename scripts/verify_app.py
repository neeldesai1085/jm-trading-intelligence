import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.db.session import Base,engine,SessionLocal
from app.models.entities import User
from app.services.analytics import overview
Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    user=db.query(User).order_by(User.id).first()
    if not user: print('No users found; register or seed a user first.')
    else:
        o=overview(db,user.id);print('user',user.email,'contracts',o['contracts'],'executions',o['executions'],'open_qty',o['open_qty'],'realized_pnl',round(o['realized_pnl'],2))
