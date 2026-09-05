from collections import defaultdict
from threading import Lock

_lock=Lock(); counts=defaultdict(int); durations=defaultdict(float)

def record(path:str,method:str,status:int,duration:float):
    key=f'{method} {path} {status}'
    with _lock: counts[key]+=1; durations[key]+=duration

def render_prometheus()->str:
    lines=['# HELP jmti_http_requests_total HTTP requests processed','# TYPE jmti_http_requests_total counter']
    with _lock:
        for key,value in sorted(counts.items()):
            method,path,status=key.split(' ',2); lines.append(f'jmti_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {value}')
        lines += ['# HELP jmti_http_request_duration_seconds_total Total HTTP request duration','# TYPE jmti_http_request_duration_seconds_total counter']
        for key,value in sorted(durations.items()):
            method,path,status=key.split(' ',2); lines.append(f'jmti_http_request_duration_seconds_total{{method="{method}",path="{path}",status="{status}"}} {value}')
    return '\n'.join(lines)+'\n'
