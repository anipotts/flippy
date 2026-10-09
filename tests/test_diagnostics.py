import json, os, tempfile, unittest
from pathlib import Path
from flippy.diagnostics import Diagnostics

class DiagnosticsTests(unittest.TestCase):
    def test_default_excludes_content_and_restricts_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,'events'); diag=Diagnostics(path,clock=lambda:3)
            diag.event('point',question='secret',text='private',ch='x',path='private',n=3)
            self.assertEqual(json.loads(Path(path).read_text()),{'t':3,'ev':'point','n':3})
            self.assertEqual(os.stat(path).st_mode & 0o777,0o600)
    def test_recording_explicit_and_no_objects(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,'events'); diag=Diagnostics(path,record_content=True)
            diag.event('typed',ch='a',object=object()); row=json.loads(Path(path).read_text())
            self.assertEqual(row['ch'],'a'); self.assertNotIn('object',row)
    def test_command_sanitization_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,'events'); diag=Diagnostics(path)
            diag.command('type secret'); self.assertNotIn('secret',Path(path).read_text())
            target=os.path.join(d,'target'); os.symlink(path,target)
            old=Path(path).read_text(); Diagnostics(target).event('oops'); self.assertEqual(Path(path).read_text(),old)

    def test_recording_excludes_images_tokens_and_unknown_controls(self):
        with tempfile.TemporaryDirectory() as d:
            path=os.path.join(d,'events'); diag=Diagnostics(path,record_content=True)
            diag.event('control',control='private typed text',key='private key',image='base64',jpeg='base64',access_token='token')
            row=json.loads(Path(path).read_text())
            self.assertEqual(set(row),{'t','ev'})
