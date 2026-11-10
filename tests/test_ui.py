"""Real Tk widget smoke test with explicitly synthetic input; no radio access."""
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class UI(unittest.TestCase):
    def test_views_receive_data(self):
        from aegis.ui import App
        fake = SimpleNamespace(events=queue.Queue(),stop=threading.Event(),dropped=0,start=lambda:None)
        now = time.time()
        fake.events.put(('ble',('fixture','SYNTHETIC TEST',-60,now,'Test fixture')))
        fake.events.put(('wifi',[['aa:bb:cc:dd:ee:ff','TEST NETWORK','6','70','WPA2','*']]))
        fake.events.put(('neighbors',[{'dst':'192.0.2.1','dev':'test0','state':['STALE']}]))
        fake.events.put(('probe',(now,'aa:bb:cc:dd:ee:ff',-70)))
        with tempfile.TemporaryDirectory() as temp, patch('aegis.ui.Services',return_value=fake):
            app = App(SimpleNamespace(data_dir=Path(temp),adapter=None,probe_interface=None))
            try:
                app.update_idletasks()
                app.refresh()
                self.assertEqual(len(app.ble.get_children()),1)
                self.assertEqual(len(app.wifi.get_children()),1)
                self.assertEqual(len(app.neighbors.get_children()),1)
                self.assertEqual(len(app.probe_table.get_children()),1)
                app.ble.selection_set('fixture')
                app.select()
                app.refresh()
                self.assertIn('SYNTHETIC TEST',app.detail.cget('text'))
                app.mark(True)
                app.refresh()
                self.assertEqual(len(app.ble.get_children()),0)
                app.mode.set('known')
                app.refresh()
                self.assertEqual(len(app.ble.get_children()),1)
            finally:
                for job in app.tk.call('after','info'):
                    app.after_cancel(job)
                app.close()
