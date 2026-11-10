import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from aegis.core import analyze, Monitor
from aegis.services import fields, probe, monitor_interfaces, Services


class Checks(unittest.TestCase):
    def test_trends_and_noise(self):
        for slope,expected in [(1.4,'APPROACHING'),(-1.4,'DEPARTING'),(0,'STABLE')]:
            samples = [(i,-70+i*slope) for i in range(25)]
            self.assertEqual(analyze(samples,24,True)[0],expected)
            self.assertLessEqual(analyze(samples,24,False)[1],30)
        self.assertEqual(analyze([(i,-65+(30 if i==22 else 0)) for i in range(25)],24,True)[0],'STABLE')
        self.assertEqual(analyze([(i,-65+[0,4,-3,5,-4][i%5]) for i in range(25)],24,True)[0],'STABLE')

    def test_invalid_bursts_gaps_and_reversal(self):
        self.assertEqual(analyze([(1,-70)]*100,1)[0],'LEARNING')
        self.assertEqual(analyze([(i,-70) for i in range(20)],50)[0],'STALE')
        self.assertEqual(analyze([(0,-80),(20,-40)],20)[0],'LEARNING')
        self.assertEqual(analyze([(100,-60),(math.nan,-50),(1,127)],20)[0],'STALE')
        levels = [-58,-59,-58,-59,-60,-64,-69,-75,-81,-79,-74,-67,-59,-53,-48,-46,-45]
        self.assertEqual(analyze(list(enumerate(levels)),16,True)[0],'APPROACHING')
        rng = random.Random(42)
        for _ in range(1000):
            samples = [(rng.uniform(-20,40),rng.uniform(-150,50)) for _ in range(50)]
            _,confidence,_ = analyze(samples,30,True)
            self.assertTrue(0<=confidence<=90)

    def test_persistence_review_learning(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'state.db'
            m = Monitor(path)
            m.motion(True)
            m.arm(True,100)
            for t in range(100,180):
                m.ingest('a','My device',-65,t)
            self.assertIn('a',m.pending)
            self.assertEqual(m.ordered(179),[])
            m.review('a',True,'Mine')
            self.assertEqual(len(m.ordered(179,'known')),1)
            self.assertGreater(m.db.execute('SELECT learned FROM devices').fetchone()[0],20)
            m.close()
            n = Monitor(path)
            self.assertTrue(n.known('a'))
            self.assertEqual(n.db.execute('SELECT label FROM devices').fetchone()[0],'Mine')
            n.close()

    def test_alerts_and_disappearance(self):
        with tempfile.TemporaryDirectory() as temp:
            m = Monitor(Path(temp)/'state.db')
            m.motion(True)
            m.arm(True,100)
            for t in range(120,145):
                m.ingest('b','New',-95+(t-120)*2,t)
            messages = [message for key,message in m.alerts]
            self.assertEqual(messages.count('New observable source'),1)
            self.assertEqual(messages.count('Unknown source has a sustained strengthening signal'),1)
            m.tick(180)
            m.tick(181)
            self.assertEqual(m.db.execute("SELECT COUNT(*) FROM events WHERE message LIKE 'No longer%'").fetchone()[0],1)
            m.close()

    def test_parsers(self):
        self.assertEqual(fields(r'AA\:BB:room\:one:6:82:WPA2:*'),['AA:BB','room:one','6','82','WPA2','*'])
        self.assertEqual(probe('123.5\taa:bb:cc:dd:ee:ff\t-60'),(123.5,'aa:bb:cc:dd:ee:ff',-60))
        self.assertIsNone(probe('broken'))
        self.assertIsNone(probe('1\t; command\t-50'))

    def test_monitor_discovery(self):
        listing = 'phy#1\n\tInterface wlan0\n\t\ttype managed\nphy#2\n\tInterface mon1\n\t\ttype monitor\n\tInterface mon0\n\t\ttype monitor\n'
        self.assertEqual(monitor_interfaces(listing), ['mon0','mon1'])
        self.assertEqual(monitor_interfaces('Interface wlan0\n type managed'), [])

    def test_probe_hotplug_retry_and_override(self):
        service = Services()
        service.stop = Mock()
        service.stop.is_set.return_value = False
        service.stop.wait.side_effect = [False,True]
        with patch('aegis.services.run',side_effect=['','Interface mon0\n type monitor']), patch.object(service,'capture_probes') as capture:
            service.probes()
            capture.assert_called_once_with('mon0')
        service = Services(probe_interface='chosen0')
        service.stop = Mock()
        service.stop.is_set.return_value = False
        service.stop.wait.return_value = True
        with patch('aegis.services.run') as discover, patch.object(service,'capture_probes') as capture:
            service.probes()
            discover.assert_not_called()
            capture.assert_called_once_with('chosen0')


if __name__ == '__main__':
    unittest.main()
