"""Actual controller method bodies with a deterministic UI queue and no native imports."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock

from flippy.actions import ActionError
from flippy.frames import ScreenFrame
from flippy.requests import Request


class MainQueue:
    def __init__(self):
        self.calls = []
        self.sequence = 0
        self.removed = []

    def idle_add(self, fn):
        self.calls.append(fn)
        self.sequence += 1
        return self.sequence

    def timeout_add(self, ms, fn):
        return self.idle_add(fn)

    def source_remove(self, timer):
        self.removed.append(timer)

    def flush(self):
        calls, self.calls = self.calls, []
        for callback in calls:
            callback()


def controller(queue):
    tree = ast.parse((Path(__file__).parents[1] / 'flippy/daemon.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Flippy')
    names = ('_owns', '_run_request', '_action_main', '_capture_frame', '_unlink',
             '_action_perform', '_on_answer', '_begin_request', '_schedule_fade', '_action_approve')
    ns = {'asyncio': asyncio, 'loop': queue, 'Request': Request, 'ActionError': ActionError, 'approval_text': lambda *args: 'proposal',
          'os': __import__('os'), 'prepare_frame': Mock(), 'settings': SimpleNamespace(get=lambda *args: 1920),
          '_friendly_error': Mock(return_value='sanitized')}
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names:
            exec(compile(ast.Module(body=[n], type_ignores=[]), '<controller>', 'exec'), ns)
    adapter = type('Controller', (), {name: ns[name] for name in names})()
    adapter.gen = 1
    adapter.request = Request(1,'tutor')
    adapter.busy = True
    adapter.quitting = False
    adapter.input_disabled = False
    adapter.loop = asyncio.get_running_loop()
    adapter._stop_playback = Mock()
    adapter._cancel_fade = Mock()
    adapter._fail = Mock()
    adapter.box = SimpleNamespace(hide=Mock())
    adapter.overlay = SimpleNamespace(clear=Mock(), point=Mock(), queue_draw=Mock())
    adapter.ui = SimpleNamespace(screen_size=lambda: (100,100), hide_settle_ms=0,
                                 action_state=lambda: ('app',1,2,(0,0,100,100),(100,100)),
                                 action_card=SimpleNamespace(hide=Mock(), card=Mock()), hide_nudge=Mock())
    return adapter, ns


class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    async def spin(self, queue, count=5):
        for _ in range(count):
            queue.flush()
            await asyncio.sleep(0)

    async def test_new_request_stops_owned_video_recording(self):
        q=MainQueue(); f,_=controller(q)
        f.video=SimpleNamespace(recording=True,cancel=Mock())
        owner=f._begin_request('tutor')
        f.video.cancel.assert_called_once()
        self.assertIs(f.request,owner)
        self.assertTrue(f.busy)

    async def test_stale_answer_cannot_clear_or_fail_new_request(self):
        q=MainQueue(); f,_=controller(q)
        old=f.request; f.request=Request(2,'tutor')
        f.play={'gen':2,'raw':'new','done':False}
        f._on_answer(None,RuntimeError('old'),old)
        self.assertTrue(f.busy)
        self.assertEqual(f.play['raw'],'new')
        f._fail.assert_not_called()
        f._stop_playback.assert_not_called()

    async def test_old_fade_cannot_clear_new_fade_identity(self):
        q=MainQueue(); f,_=controller(q)
        f._fade_out=Mock()
        f._schedule_fade(1)
        old=q.calls.pop()
        f.request=Request(2,'tutor'); f.gen=2
        f._schedule_fade(2)
        current=f.fade_id
        old()
        self.assertEqual(f.fade_id,current)
        f._fade_out.assert_not_called()

    async def test_cancel_acknowledged_after_coroutine_cleanup(self):
        q=MainQueue(); f,_=controller(q); req=f.request
        started=asyncio.Event(); cleanup=asyncio.Event(); done=Mock()
        async def work():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleanup.wait()
        fut=f._run_request(req,work(),done)
        await started.wait()
        req.cancel(q.source_remove)
        await self.spin(q)
        self.assertTrue(f.busy)
        self.assertFalse(req.drained.is_set())
        cleanup.set()
        await asyncio.wrap_future(fut)
        await self.spin(q)
        self.assertTrue(req.drained.is_set())
        self.assertFalse(f.busy)
        done.assert_not_called()

    async def test_cancel_before_coroutine_start_still_acknowledges(self):
        q=MainQueue(); f,_=controller(q); req=f.request
        async def work():
            raise AssertionError('canceled work must not execute')
        fut=f._run_request(req,work(),Mock())
        req.cancel(q.source_remove)
        await asyncio.wrap_future(fut)
        await self.spin(q)
        self.assertTrue(req.drained.is_set())
        self.assertFalse(f.busy)

    async def test_late_capture_file_is_removed_without_preparation(self):
        q=MainQueue(); f,ns=controller(q); callbacks=[]
        f.shooter=SimpleNamespace(take=lambda cb: callbacks.append(cb))
        task=asyncio.create_task(f._capture_frame(f.request))
        await self.spin(q,10)
        self.assertEqual(len(callbacks),1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with tempfile.NamedTemporaryFile(delete=False) as file:
            path=file.name
        callbacks[0](path,None)
        await self.spin(q)
        self.assertFalse(Path(path).exists())
        ns['prepare_frame'].assert_not_called()

    async def test_queued_ui_skips_canceled_owner(self):
        q=MainQueue(); f,_=controller(q); op=Mock()
        task=asyncio.create_task(f._action_main(op,f.request))
        await asyncio.sleep(0)
        f.request.cancel(q.source_remove)
        await self.spin(q)
        with self.assertRaises(asyncio.CancelledError):
            await task
        op.assert_not_called()

    async def test_drag_outside_foreground_window_never_opens_card(self):
        q=MainQueue(); f,_=controller(q)
        frame=ScreenFrame('jpeg',(100,100),(100,100),('app',1,2,(20,20,40,40),(100,100)))
        args={'x':30,'y':30,'to_x':80,'to_y':80,'modifiers':[],'reason':'move'}
        task=asyncio.create_task(f._action_approve('drag',args,frame,f.request))
        await self.spin(q)
        with self.assertRaises(ActionError): await task
        f.ui.action_card.card.assert_not_called()

    async def test_changed_pixels_never_reach_native_input(self):
        q=MainQueue(); f,_=controller(q)
        original=ScreenFrame('jpeg',(100,100),(100,100),('target',),'first',(100,100))
        async def capture(*args,**kwargs):
            return ScreenFrame('jpeg',(100,100),(100,100),('target',),'changed',(100,100))
        f._capture_frame=capture; f.ui.action_input=Mock()
        with self.assertRaises(ActionError):
            await f._action_perform('click',{},original,threading.Event(),f.request)
        f.ui.action_input.assert_not_called()

    async def test_native_worker_cancel_waits_for_release_ack(self):
        q=MainQueue(); f,_=controller(q)
        shot=ScreenFrame('jpeg',(100,100),(100,100),('target',),'same',(100,100))
        async def capture(*args,**kwargs): return shot
        f._capture_frame=capture
        started=threading.Event(); release=threading.Event(); cancel=threading.Event()
        def perform(*args):
            started.set(); release.wait(2)
        f.ui.action_input=perform
        task=asyncio.create_task(f._action_perform('drag',{},shot,cancel,f.request))
        await asyncio.to_thread(started.wait,1)
        task.cancel(); await asyncio.sleep(.02)
        self.assertFalse(task.done())
        self.assertTrue(cancel.is_set())
        release.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(f.input_disabled)
    async def test_video_uses_shared_provider_with_ordered_frames(self):
        from flippy import video
        from unittest.mock import AsyncMock
        brain=SimpleNamespace(ask=AsyncMock(return_value='review'))
        frames=[('t=0.0s','first'),('t=1.0s','last')]
        on_text=Mock()
        result=await video.ask(brain,frames,'current',(100,100),'question',on_text)
        self.assertEqual(result,'review')
        brain.ask.assert_awaited_once_with('question','current',(100,100),on_text=on_text,extra_images=frames)


class TestRequest(unittest.TestCase):
    def test_timer_failure_does_not_skip_transport_cancel(self):
        req=Request(1,'tutor'); req.timers.update((1,2)); req.future=Mock()
        remove=Mock(side_effect=RuntimeError('expired timer'))
        self.assertTrue(req.cancel(remove))
        self.assertEqual(remove.call_count,2)
        req.future.cancel.assert_called_once()
        self.assertFalse(req.cancel(remove))
