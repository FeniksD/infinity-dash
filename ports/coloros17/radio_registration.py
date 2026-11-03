"""Guard the optional OPPO radio notification lookup on the dash vendor stack."""
import hashlib

METHOD = '.method private registerForOplusRadioServiceCallback()V'
ORIGINAL_METHOD_SHA256 = '090c1444ed4bcd5ee43184f1152169f224acb40f5f9d37899184e922e452b1f8'
REMOTE_CATCH = '    .catch Landroid/os/RemoteException; {:try_start_7 .. :try_end_1a} :catch_1b'
SECURITY_CATCH = '    .catch Ljava/lang/SecurityException; {:try_start_7 .. :try_end_1a} :catch_1b'


def patch_registration(text):
    if text.count(METHOD) != 1:
        raise ValueError('expected one OPPO radio registration method')
    start = text.index(METHOD)
    end = text.index('.end method', start) + len('.end method')
    method = text[start:end]
    if hashlib.sha256(method.encode()).hexdigest() != ORIGINAL_METHOD_SHA256:
        raise ValueError('OPPO radio registration method differs from the pinned donor')
    if method.count(REMOTE_CATCH) != 1:
        raise ValueError('unexpected registration exception boundary')
    replacement = method.replace(REMOTE_CATCH, REMOTE_CATCH + '\n' + SECURITY_CATCH)
    return text[:start] + replacement + text[end:]
