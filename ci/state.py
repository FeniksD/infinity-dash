"""Local state for a restricted build gateway. A reserved run is never restarted."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import tempfile


def state_path(root,run_id,attempt):
    if type(run_id) is not int or not 1 <= run_id < 2**63 or type(attempt) is not int or not 1 <= attempt <= 1000:
        raise ValueError('invalid run identity')
    return Path(root)/f'{run_id}-{attempt}.json'


def sync_directory(root):
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load(root,run_id,attempt):
    path=state_path(root,run_id,attempt)
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    except OSError as exc:
        if isinstance(exc,FileNotFoundError): raise
        raise ValueError('unsafe state file') from exc
    with os.fdopen(fd,'r') as source:
        info=os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>1024*1024:
            raise ValueError('unsafe state file')
        value=json.load(source)
    if not isinstance(value,dict) or value.get('run_id')!=run_id or value.get('attempt')!=attempt:
        raise ValueError('state identity mismatch')
    return value


def reserve(root,request,source_sha):
    path=state_path(root,request['run_id'],request['attempt'])
    if not isinstance(request.get('head'),str) or not re.fullmatch(r'[0-9a-f]{40}',request['head']):
        raise ValueError('invalid head')
    Path(root).mkdir(parents=True,exist_ok=True,mode=0o700)
    value={k:request[k] for k in ('run_id','attempt','head')}
    value.update(status='accepted',source_sha=source_sha)
    data=(json.dumps(value,sort_keys=True)+'\n').encode()
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    except FileExistsError:
        current=load(root,request['run_id'],request['attempt'])
        if current.get('head')!=request['head'] or current.get('source_sha')!=source_sha:
            raise ValueError('reserved run context mismatch')
        return current,False
    with os.fdopen(fd,'wb') as output:
        output.write(data); output.flush(); os.fsync(output.fileno())
    sync_directory(root)
    return value,True


@contextmanager
def locked(root):
    fd=os.open(Path(root)/'.state.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def update(root,run_id,attempt,**changes):
    allowed={'status','pid','artifacts','error','started_at','finished_at'}
    if not set(changes)<=allowed: raise ValueError('immutable state fields cannot change')
    with locked(root):
        value=load(root,run_id,attempt)
        if 'status' in changes and changes['status'] not in {'accepted','running','ready','failed'}:
            raise ValueError('invalid state status')
        if value['status'] in {'ready','failed'} and changes.get('status',value['status'])!=value['status']:
            raise ValueError('terminal state cannot restart')
        value.update(changes)
        fd,temp=tempfile.mkstemp(prefix='.state-',dir=root)
        try:
            with os.fdopen(fd,'w') as output:
                json.dump(value,output,sort_keys=True); output.write('\n'); output.flush(); os.fsync(output.fileno())
            os.replace(temp,state_path(root,run_id,attempt))
            sync_directory(root)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return value
