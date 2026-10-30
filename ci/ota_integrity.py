"""Read-only OTA container/hash checks. Not a signature or hardware validator."""
import base64
import hashlib
from pathlib import PurePosixPath
import struct
import zipfile


def key_values(text):
    result={}
    for line in text.splitlines():
        if not line.strip(): continue
        key,sep,value=line.partition('=')
        if not sep or key in result: raise ValueError('invalid/duplicate metadata key')
        result[key]=value
    return result


def small_file(z,name):
    info=z.getinfo(name)
    if info.file_size > 1024*1024: raise ValueError('metadata file is too large')
    return z.read(name).decode('utf-8')


def _check_ota_integrity(path,device):
    before=path.stat()
    with zipfile.ZipFile(path) as z:
        entries=z.infolist()
        if len(entries)>1000: raise ValueError('too many OTA entries')
        names=set()
        for info in entries:
            name=info.filename
            if name in names or name.startswith('/') or '\\' in name or '..' in PurePosixPath(name).parts:
                raise ValueError('unsafe/duplicate OTA path')
            names.add(name)
            if info.flag_bits & 1: raise ValueError('encrypted OTA entry')
            if info.file_size > (16*1024**3 if name=='payload.bin' else 64*1024**2):
                raise ValueError('OTA entry exceeds size limit')
        if not {'payload.bin','payload_properties.txt','META-INF/com/android/metadata'} <= names:
            raise ValueError('required A/B OTA files missing')
        metadata=key_values(small_file(z,'META-INF/com/android/metadata'))
        props=key_values(small_file(z,'payload_properties.txt'))
        if metadata.get('pre-device')!=device or metadata.get('ota-type')!='AB':
            raise ValueError('wrong OTA device/type')
        info=z.getinfo('payload.bin')
        if info.compress_type!=zipfile.ZIP_STORED:
            raise ValueError('payload must be stored uncompressed for streaming OTA')
        if int(props['FILE_SIZE'])!=info.file_size: raise ValueError('payload size mismatch')
        metadata_size=int(props['METADATA_SIZE'])
        if not 24 <= metadata_size <= info.file_size: raise ValueError('invalid metadata size')
        digest=hashlib.sha256(); metadata_digest=hashlib.sha256(); count=0; header=b''
        with z.open('payload.bin') as payload:
            while chunk:=payload.read(1024*1024):
                if len(header)<24: header=(header+chunk)[:24]
                digest.update(chunk)
                if count<metadata_size: metadata_digest.update(chunk[:metadata_size-count])
                count+=len(chunk)
        if len(header)!=24 or header[:4]!=b'CrAU': raise ValueError('invalid payload header')
        version,manifest_size,signature_size=struct.unpack('>QQI',header[4:])
        if version!=2 or manifest_size==0 or metadata_size!=24+manifest_size or metadata_size+signature_size>count:
            raise ValueError('unsupported/invalid payload layout')
        if digest.digest()!=base64.b64decode(props['FILE_HASH'],validate=True):
            raise ValueError('payload hash mismatch')
        if metadata_digest.digest()!=base64.b64decode(props['METADATA_HASH'],validate=True):
            raise ValueError('payload metadata hash mismatch')
        for item in entries:
            if item.filename in {'payload.bin','payload_properties.txt','META-INF/com/android/metadata'} or item.is_dir(): continue
            with z.open(item) as content:
                while content.read(1024*1024): pass
    with path.open('rb') as f:
        archive_digest=hashlib.file_digest(f,'sha256').hexdigest()
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
        raise ValueError('OTA file changed during validation')
    return {'device':device,'ota_type':'AB','size_bytes':after.st_size,'sha256':archive_digest,'payload_sha256':digest.hexdigest(),'android_signatures_verified':False,'payload_manifest_parsed':False}


def check_ota_integrity(path,device):
    try:
        return _check_ota_integrity(path,device)
    except (KeyError,zipfile.BadZipFile,UnicodeError,RuntimeError) as exc:
        raise ValueError('invalid OTA container or required properties') from exc
