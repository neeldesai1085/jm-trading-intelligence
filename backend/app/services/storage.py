from __future__ import annotations
from pathlib import Path
import hashlib
from app.core.config import settings

def store_raw_pdf(data:bytes,user_id:int,portfolio_id:int,filename:str)->str|None:
    if not settings.store_raw_pdf:return None
    digest=hashlib.sha256(data).hexdigest(); safe=Path(filename).name;root=Path(settings.upload_dir)/'archive'/str(user_id)/str(portfolio_id);root.mkdir(parents=True,exist_ok=True);path=root/f'{digest[:16]}_{safe}';path.write_bytes(data);return str(path)
