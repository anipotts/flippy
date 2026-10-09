import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flippy import daemon
from flippy.diagnostics import Diagnostics
from flippy.frames import ScreenFrame
from flippy.playback import Options, Playback

class ControllerTests(unittest.TestCase):
    def host(self):
        h=daemon.Flippy.__new__(daemon.Flippy)
        calls=[]; h.gen=3; h.play=None; h.play_id=0; h.tutorial=True
        h.ui=SimpleNamespace(screen_size=lambda:(100,100),watch_clicks=lambda fn:calls.append(('watch',True)),
                             unwatch_clicks=lambda:calls.append(('watch',False)))
        h.overlay=SimpleNamespace(point=lambda *v:calls.append(('point',v)),
                                  show_text=lambda *a,**v:calls.append(('card',v)),
                                  queue_draw=lambda:None,card=None,pressed=None)
        h._play_options=lambda:Options(tutorial=True,clicks_available=True)
        h._scale=lambda:2
        h._schedule_fade=lambda n:calls.append(('fade',n)); h._cancel_fade=lambda:None
        return h,calls

    def test_frame_coordinate_clamp_and_click_watcher_lifetime(self):
        h,calls=self.host()
        with patch.object(daemon.loop,'timeout_add',return_value=12), patch.object(daemon.loop,'source_remove'):
            h._start_playback(3,(200,200),(400,400),ScreenFrame('',(200,200),(100,100)))
            h.play.finish('click [POINT:999,100:button:click]')
            h.play.last=0
            with patch.object(daemon.time,'monotonic',return_value=2): self.assertTrue(h._play_tick())
            self.assertEqual(next(v for k,v in calls if k=='point'),(99.5,50.,'button'))
            self.assertIn(('watch',True),calls)
            h._stop_playback(); self.assertIn(('watch',False),calls); self.assertIsNone(h.play)

    def test_final_skip_continues_and_does_not_leave_timer(self):
        h,calls=self.host(); h.play=Playback(0)
        h.play.gen=3; h.play.frame=None; h.play.img=(100,100); h.play.shot=(100,100)
        h.play.finish('click [POINT:1,2:x:click]'); h.play.waiting=True
        submissions=[]; h.submit=lambda *a,**k:submissions.append((a,k))
        with patch.object(daemon.loop,'source_remove'):
            h.control('next')
        self.assertIsNone(h.play); self.assertEqual(len(submissions),1)
        self.assertIn(('watch',False),calls)

    def test_commands_and_logs_do_not_reveal_content(self):
        h,calls=self.host(); h.submit=lambda q:None
        with tempfile.TemporaryDirectory() as tmp:
            d=Diagnostics(str(Path(tmp)/'events'))
            output=io.StringIO()
            with patch.object(daemon,'diagnostics',d), contextlib.redirect_stderr(output):
                h.command('q private question')
                self.assertEqual(h.command(' '),'unknown command')
            self.assertNotIn('private question',Path(d.path).read_text())
            self.assertNotIn('private question',output.getvalue())  # nor in the log
            # log() itself prints its message: operational lines (why a task stopped, update checks) are the log's
            # whole point; callers never pass questions, answers or typed text
            output=io.StringIO()
            with contextlib.redirect_stderr(output): daemon.log('act: ended after 2 input(s), none')
            self.assertIn('act: ended after 2 input(s), none',output.getvalue())

    def test_onboarding_receives_raw_in_memory_event_without_disk_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            diag=Diagnostics(str(Path(tmp)/'events')); got=[]
            listener=lambda name,data:got.append((name,data))
            with patch.object(daemon,'diagnostics',diag), patch.object(daemon,'LISTENERS',[listener]):
                daemon.event('point',x=1,label='menu',text='private explanation')
            self.assertEqual(got,[('point',{'x':1,'label':'menu','text':'private explanation'})])
            self.assertNotIn('private explanation',Path(diag.path).read_text())
