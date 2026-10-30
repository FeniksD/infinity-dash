"""Read-only OTA container/hash checks. Not a signature or hardware validator."""
import base64
import hashlib
import os
from pathlib import PurePosixPath
import stat
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


def check_payload(source,device):
    with zipfile.ZipFile(source) as z:
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
    return digest.hexdigest()


def identity(info):
    return (info.st_dev,info.st_ino,info.st_mode,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _check_ota_integrity(path,device):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    with os.fdopen(fd,'rb') as source:
        before=os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:
            raise ValueError('OTA must be a regular file without links')
        payload_digest=check_payload(source,device)
        source.seek(0)
        archive_digest=hashlib.file_digest(source,'sha256').hexdigest()
        after=os.fstat(source.fileno())
        if identity(before)!=identity(after) or identity(after)!=identity(path.lstat()):
            raise ValueError('OTA file changed during validation')
    return {'device':device,'ota_type':'AB','size_bytes':after.st_size,'sha256':archive_digest,'payload_sha256':payload_digest,'android_signatures_verified':False,'payload_manifest_parsed':False}


def check_ota_integrity(path,device):
    try:
        return _check_ota_integrity(path,device)
    except (KeyError,OSError,zipfile.BadZipFile,UnicodeError,RuntimeError) as exc:
        raise ValueError('invalid OTA container or required properties') from exc
