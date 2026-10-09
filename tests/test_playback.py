import unittest
from flippy.playback import Playback, Options

class PlaybackTests(unittest.TestCase):
    def test_stream_and_incomplete_tag(self):
        p=Playback(0); p.append('hello [PO'); self.assertEqual(p.tick(1,Options(),lambda x:(x.x,x.y)),[])
        p.append('INT:10,20:menu]'); events=p.tick(2,Options(),lambda x:(x.x,x.y))
        self.assertEqual(events[0][0],'point'); self.assertTrue(p.pointed)

    def test_pause_freezes_hold_even_at_zero(self):
        p=Playback(0); p.finish('hi [POINT:1,2:x] next [POINT:2,3:y]')
        p.shown=2; p.typed_at=0; p.paused=True
        p.tick(5,Options(),lambda x:(x.x,x.y)); self.assertEqual(p.typed_at,5)
        self.assertEqual(p.step,0)

    def test_click_typing_and_continuation(self):
        p=Playback(0); p.finish('type hello [POINT:10,20:field:click]')
        o=Options(tutorial=True,clicks_available=True,typing_available=True)
        self.assertIn(('watch_clicks',True),p.tick(1,o,lambda x:(x.x,x.y)))
        self.assertTrue(p.click(10,20,1,o)); self.assertFalse(p.click(10,20,2,o))
        self.assertNotIn(('continue',None),p.tick(2,o,lambda x:(x.x,x.y),0))
        events=p.tick(3,o,lambda x:(x.x,x.y),1.5)
        self.assertIn(('watch_clicks',False),events); self.assertIn(('continue',None),events)

    def test_next_skips_last_gate(self):
        p=Playback(0); p.finish('click [POINT:1,2:x:click]'); o=Options(tutorial=True,clicks_available=True)
        p.tick(1,o,lambda x:(x.x,x.y)); self.assertIn(('continue',None),p.control('next',0,2,o))

    def test_replay_seek_and_stop(self):
        p=Playback(0); p.finish('one [POINT:1,2:x] two [POINT:2,3:y]'); o=Options()
        p.control('seek',1,1,o); self.assertEqual(p.step,1)
        p.tick(2,o,lambda x:(x.x,x.y)); self.assertTrue(p.finished)
        p.control('play',0,3,o); self.assertEqual(p.step,0); self.assertEqual(p.shown,0)
        p.stop(); self.assertEqual(p.tick(9,o,lambda x:None),[])

    def test_remarks_continue_after_performed_step(self):
        p=Playback(0); p.finish('click [POINT:1,2:x:click] good job'); o=Options(tutorial=True,clicks_available=True)
        p.tick(1,o,lambda x:(x.x,x.y)); p.click(1,2,1,o); p.tick(2,o,lambda x:(x.x,x.y))
        p.tick(3,o,lambda x:(x.x,x.y)); self.assertIn(('continue',None),p.tick(10,o,lambda x:(x.x,x.y)))
