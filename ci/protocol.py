"""Small data-only protocol for a future forced-command SSH build gateway."""
import base64
import binascii
import json
import re


def validate_request(request):
    if not isinstance(request, dict):
        raise ValueError('request must be an object')
    action=request.get('action')
    fields={'action','run_id','attempt'}
    if action=='start': fields.add('head')
    elif action=='fetch': fields.add('artifact')
    elif action!='status': raise ValueError('unsupported request action')
    if set(request)!=fields: raise ValueError('unexpected request fields')
    if type(request['run_id']) is not int or not 1 <= request['run_id'] < 2**63:
        raise ValueError('invalid run id')
    if type(request['attempt']) is not int or not 1 <= request['attempt'] <= 1000:
        raise ValueError('invalid attempt')
    if action=='start' and (not isinstance(request['head'],str) or not re.fullmatch(r'[0-9a-f]{40}',request['head'])):
        raise ValueError('invalid head commit')
    if action=='fetch' and (not isinstance(request['artifact'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}',request['artifact']) or '..' in request['artifact']):
        raise ValueError('invalid artifact name')
    return request


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate request field')
        result[key]=value
    return result


def encode_command(request):
    validate_request(request)
    data=json.dumps(request,separators=(',',':'),sort_keys=True).encode()
    return 'infinity-ci '+base64.urlsafe_b64encode(data).decode('ascii')


def decode_command(command):
    if not isinstance(command,str) or not command.startswith('infinity-ci ') or len(command)>4096:
        raise ValueError('invalid forced command')
    encoded=command[len('infinity-ci '):]
    if not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',encoded):
        raise ValueError('invalid request encoding')
    try:
        data=base64.b64decode(encoded,altchars=b'-_',validate=True)
        if len(data)>2048: raise ValueError('request is too large')
        request=json.loads(data,object_pairs_hook=unique_object)
    except (binascii.Error,UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('invalid request data') from exc
    return validate_request(request)
