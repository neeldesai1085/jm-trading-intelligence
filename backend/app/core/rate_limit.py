from collections import defaultdict, deque
from time import monotonic
from fastapi import Request, HTTPException
from app.core.config import settings

_buckets=defaultdict(deque)

def rate_limit(request:Request,key_prefix:str='global'):
    limit=max(1,settings.rate_limit_per_minute); client=request.client.host if request.client else 'unknown'; key=f'{key_prefix}:{client}'; now=monotonic(); bucket=_buckets[key]
    while bucket and now-bucket[0]>60: bucket.popleft()
    if len(bucket)>=limit: raise HTTPException(429,'Rate limit exceeded')
    bucket.append(now)
