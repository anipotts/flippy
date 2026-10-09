"""Freshness watches intended input regions, not unrelated desktop animation."""
import tempfile
from pathlib import Path
import unittest

from PIL import Image, ImageDraw

from flippy.frames import prepare_frame


class TestRegions(unittest.TestCase):
    def pair(self, paint):
        with tempfile.TemporaryDirectory() as directory:
            first=Image.new('RGB',(400,300),'white')
            second=first.copy(); paint(ImageDraw.Draw(second))
            target=('dev.flippy.fixture',123,7,(40,30,200,180),(1,(400,300)))
            result=[]
            for index,image in enumerate((first,second)):
                path=Path(directory,str(index)+'.png'); image.save(path)
                result.append(prepare_frame(path,400,logical_size=(400,300),target=target))
            return result

    def test_background_and_caret_scale_changes_are_tolerated(self):
        a,b=self.pair(lambda draw: draw.rectangle((300,220,399,299),fill='black'))
        self.assertNotEqual(a.fingerprint,b.fingerprint)
        self.assertFalse(a.substantial_change(b,'click',{'x':100,'y':100}))
        self.assertFalse(a.substantial_change(b,'type',{'text':'hello'}))
        a,b=self.pair(lambda draw: draw.line((100,90,100,109),fill='black'))
        self.assertFalse(a.substantial_change(b,'click',{'x':100,'y':100}))
        self.assertFalse(a.substantial_change(b,'type',{'text':'hello'}))

    def test_label_replacement_and_each_drag_endpoint_are_detected(self):
        a,b=self.pair(lambda draw: draw.rectangle((80,94,120,104),fill='black'))
        self.assertTrue(a.substantial_change(b,'click',{'x':100,'y':100}))
        self.assertTrue(a.substantial_change(b,'scroll',{'x':100,'y':100}))
        self.assertTrue(a.substantial_change(b,'drag',{'x':100,'y':100,'to_x':200,'to_y':160}))
        a,b=self.pair(lambda draw: draw.rectangle((180,150,220,170),fill='blue'))
        self.assertTrue(a.substantial_change(b,'drag',{'x':100,'y':100,'to_x':200,'to_y':160}))
        self.assertFalse(a.substantial_change(b,'click',{'x':100,'y':100}))

    def test_keyboard_window_change_and_replaced_display_are_detected(self):
        a,b=self.pair(lambda draw: draw.rectangle((50,40,100,100),fill='blue'))
        self.assertTrue(a.substantial_change(b,'key',{'combo':'return'}))
        from dataclasses import replace
        replacement=replace(a,target=(*a.target[:4],(2,(400,300))))
        self.assertTrue(a.substantial_change(replacement,'click',{'x':100,'y':100}))

    def test_invalid_regions_fail_closed_and_pixels_are_not_repr_or_content(self):
        a,b=self.pair(lambda draw: None)
        for args in ({'x':-1,'y':2},{'x':True,'y':2},{'x':400,'y':0},{}):
            self.assertTrue(a.substantial_change(b,'click',args))
        self.assertNotIn('pixels=',repr(a))
        self.assertTrue(all('pixels' not in block for block in a.content()))

    def test_keyboard_crop_uses_logical_to_model_mapping(self):
        from dataclasses import replace
        a,b=self.pair(lambda draw: draw.rectangle((250,100,290,140),fill='black'))
        target=('dev.flippy.fixture',123,7,(20,15,100,90),(1,(200,150)))
        # Retina-like mapping: this change is outside window (40..240,30..210).
        a,b=[replace(frame,logical_size=(200,150),target=target) for frame in (a,b)]
        self.assertFalse(a.substantial_change(b,'type',{'text':'hello'}))
