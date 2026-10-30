import base64
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ota_integrity',ROOT/'ci/ota_integrity.py')
ota=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ota)


class OtaIntegrityTests(unittest.TestCase):
    def package(self, *, device='dash', bad_hash=False, extra=None):
        metadata=b'manifest-fixture'
        payload=b'CrAU'+struct.pack('>QQI',2,len(metadata),0)+metadata+b'payload-data'
        header_size=24+len(metadata)
        digest=base64.b64encode(hashlib.sha256(payload).digest()).decode()
        if bad_hash: digest=base64.b64encode(bytes(32)).decode()
        props=f'FILE_SIZE={len(payload)}\nFILE_HASH={digest}\nMETADATA_SIZE={header_size}\nMETADATA_HASH={base64.b64encode(hashlib.sha256(payload[:header_size]).digest()).decode()}\n'
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            z.writestr('META-INF/com/android/metadata',f'ota-type=AB\npre-device={device}\n')
            z.writestr('payload_properties.txt',props)
            z.writestr('payload.bin',payload)
            if extra: z.writestr(extra,b'x')
        return data.getvalue()

    def inspect(self,data):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ota.zip'; path.write_bytes(data)
            return ota.check_ota_integrity(path,'dash')

    def test_matching_container_and_hashes_are_accepted(self):
        result=self.inspect(self.package())
        self.assertEqual(result['device'],'dash')
        self.assertIn('sha256',result)
        self.assertFalse(result['android_signatures_verified'])

    def test_wrong_device_and_payload_hash_are_rejected(self):
        with self.assertRaises(ValueError): self.inspect(self.package(device='other'))
        with self.assertRaises(ValueError): self.inspect(self.package(bad_hash=True))

    def test_traversal_entry_is_rejected(self):
        with self.assertRaises(ValueError): self.inspect(self.package(extra='../escape'))

    def test_missing_required_property_is_reported_as_invalid_ota(self):
        source=io.BytesIO(self.package()); output=io.BytesIO()
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(output,'w') as modified:
            for item in original.infolist():
                data=original.read(item)
                if item.filename=='payload_properties.txt':
                    data=b'\n'.join(line for line in data.splitlines() if not line.startswith(b'FILE_HASH='))+b'\n'
                modified.writestr(item,data)
        with self.assertRaises(ValueError): self.inspect(output.getvalue())
