import math
import statistics as stats
import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field


def clean(value):
    return ''.join(c for c in str(value) if c.isprintable())[:100].strip()


def analyze(samples, now, stationary=False):
    """Median time buckets keep burst rate from masquerading as evidence."""
    valid = sorted((t, r) for t, r in samples if math.isfinite(t) and math.isfinite(r)
                   and -127 < r < 0 and 0 <= now-t <= 25)
    if not valid or now-valid[-1][0] > 8:
        return ('STALE', 0, 'No fresh evidence. Silence does not prove departure.')
    for i in range(len(valid)-1, 0, -1):
        if valid[i][0]-valid[i-1][0] > 8:
            valid = valid[i:]
            break
    def fit(window):
        buckets = {}
        for t, r in window:
            buckets.setdefault(int(t), []).append(r)
        points = [(t, stats.median(v)) for t, v in sorted(buckets.items())]
        if len(points) < 6 or points[-1][0]-points[0][0] < 5:
            return None
        # Median of pairwise slopes is resistant to isolated spikes.
        slopes = [(b[1]-a[1])/(b[0]-a[0]) for i, a in enumerate(points)
                  for b in points[i+1:] if b[0]-a[0] >= 2]
        slope = stats.median(slopes)
        origin = points[0][0]
        intercept = stats.median(r-slope*(t-origin) for t, r in points)
        residual = stats.median(abs(r-(intercept+slope*(t-origin))) for t, r in points)
        change = stats.median([r for _, r in points[-3:]])-stats.median([r for _, r in points[:3]])
        direction = 'STABLE'
        if abs(change) >= max(8, residual*3) and abs(slope) >= .65 and change*slope > 0:
            direction = 'APPROACHING' if slope > 0 else 'DEPARTING'
        score = round(90*min(1, len(points)/12)*min(1, (points[-1][0]-origin)/12)/(1+residual/4))
        score = min(score, 85) if stationary else min(round(score*.35), 30)
        return direction, score, f'{change:+.1f} dB change; {len(points)} separate seconds; noise {residual:.1f} dB. '
    fast = fit([(t, r) for t, r in valid if now-t <= 9])
    result = fast if fast and fast[0] != 'STABLE' else fit(valid) or fast
    return result if result else ('LEARNING', 0, 'Need at least six time-separated observations.')


@dataclass
class Source:
    key: str
    name: str
    first: float
    last: float
    samples: deque = field(default_factory=lambda: deque(maxlen=300))
    smooth: float = -100
    band: int = 0
    candidate: str = ''
    candidate_since: float = 0
    trend: str = 'LEARNING'
    confidence: int = 0
    explanation: str = ''
    metadata: str = ''
    persisted_second: int = -1
    alert_at: float = -1e12
    arrival_notified: bool = False


class Monitor:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS devices(key TEXT PRIMARY KEY,name TEXT,known INTEGER DEFAULT 0,
          label TEXT DEFAULT '',baseline REAL DEFAULT 0,learned INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS observations(key TEXT,t REAL,r REAL);
        CREATE INDEX IF NOT EXISTS obs_time ON observations(t);
        CREATE TABLE IF NOT EXISTS encounters(id INTEGER PRIMARY KEY,key TEXT,start REAL,end REAL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,t REAL,key TEXT,message TEXT);
        ''')
        self.sources = {}
        self.pending = set()
        self.stationary = False
        self.armed = False
        self.arm_until = 0
        self.alerts = []
        self.pruned = 0
        self.session_start = time.time()
        self.db.execute('UPDATE encounters SET end=start WHERE end IS NULL')
        self.db.commit()

    def event(self, t, key, message, notify=False):
        self.db.execute('INSERT INTO events(t,key,message) VALUES(?,?,?)', (t,key,message))
        if notify:
            self.alerts.append((key,message))

    def arm(self, enabled, now):
        self.armed = enabled
        self.arm_until = now+15 if enabled else 0
        self.pending = {k for k,s in self.sources.items() if now-s.last <= 8} if enabled else set()
        self.event(now, '', 'Defense armed: baseline review for 15 seconds' if enabled else 'Defense disarmed')

    def motion(self, stationary):
        self.stationary = stationary
        for s in self.sources.values():
            s.samples.clear()
            s.trend, s.confidence = 'LEARNING', 0
            s.candidate = ''

    def known(self, key):
        row = self.db.execute('SELECT known FROM devices WHERE key=?', (key,)).fetchone()
        return bool(row and row[0])

    def review(self, key, known, label=None):
        self.db.execute('UPDATE devices SET known=? WHERE key=?', (int(known),key))
        if label is not None:
            self.db.execute('UPDATE devices SET label=? WHERE key=?', (clean(label),key))
        self.pending.discard(key)
        self.db.commit()

    def ingest(self, key, name, rssi, now, metadata=''):
        if not math.isfinite(rssi) or not -127 < rssi < 0 or not math.isfinite(now):
            return
        key, name = clean(key), clean(name) or 'Unnamed source'
        self.db.execute('INSERT OR IGNORE INTO devices(key,name) VALUES(?,?)', (key,name))
        if name != 'Unnamed source':
            self.db.execute('UPDATE devices SET name=? WHERE key=?', (name,key))
        s = self.sources.get(key)
        if s and now < s.last:
            return
        if not s or now-s.last > 30:
            if s:
                self.db.execute('UPDATE encounters SET end=? WHERE key=? AND end IS NULL', (s.last,key))
            s = Source(key,name,now,now,smooth=rssi)
            s.band = int((rssi+128)//8)
            self.sources[key] = s
            self.db.execute('INSERT INTO encounters(key,start) VALUES(?,?)', (key,now))
            self.event(now,key,'Source observed')
        if len(self.sources) > 1000:
            oldest = min(self.sources, key=lambda k:self.sources[k].last)
            self.db.execute('UPDATE encounters SET end=? WHERE key=? AND end IS NULL', (self.sources[oldest].last,oldest))
            del self.sources[oldest]
            self.pending.discard(oldest)
        if name != 'Unnamed source':
            s.name = name
        if now-s.last > 8:
            s.samples.clear()
            s.candidate = ''
        dt = now-s.last
        s.samples.append((now,rssi))
        median = stats.median([r for t,r in s.samples if now-t <= 3])
        s.smooth += (1-math.exp(-dt/3))*(median-s.smooth)
        s.last, s.metadata = now, clean(metadata)
        # Wide ranking bands plus hysteresis prevent noisy row shuffling.
        if s.smooth < s.band*8-128-3 or s.smooth > (s.band+1)*8-128+3:
            s.band = int((s.smooth+128)//8)
        result, confidence, reason = analyze(s.samples, now, self.stationary)
        if result != s.candidate:
            s.candidate, s.candidate_since = result, now
        if result in ('STALE','LEARNING') or now-s.candidate_since >= 2:
            s.trend = result
        s.confidence, s.explanation = confidence, reason
        if self.armed and now < self.arm_until:
            self.pending.add(key)
        if int(now) != s.persisted_second:
            self.db.execute('INSERT INTO observations VALUES(?,?,?)', (key,now,rssi))
            s.persisted_second = int(now)
            if self.stationary and result == 'STABLE' and confidence >= 55:
                mean, n = self.db.execute('SELECT baseline,learned FROM devices WHERE key=?',(key,)).fetchone()
                n += 1
                mean += (median-mean)/min(n,100)
                self.db.execute('UPDATE devices SET baseline=?,learned=? WHERE key=?',(mean,n,key))
        eligible = self.armed and now >= self.arm_until and key not in self.pending and not self.known(key)
        if eligible and now-s.alert_at >= 90:
            if s.trend == 'APPROACHING' and result == 'APPROACHING' and confidence >= 55:
                self.event(now,key,'Unknown source has a sustained strengthening signal',True)
                s.alert_at = now
            elif now-s.first >= 3 and s.first >= self.arm_until and not s.arrival_notified:
                self.event(now,key,'New observable source',True)
                s.arrival_notified = True

    def tick(self, now):
        for key,s in list(self.sources.items()):
            if now-s.last > 8:
                s.trend, s.confidence = 'STALE',0
                s.explanation = 'No fresh evidence. Silence does not prove departure.'
            if now-s.last > 30:
                row = self.db.execute('SELECT id FROM encounters WHERE key=? AND end IS NULL',(key,)).fetchone()
                if row:
                    self.db.execute('UPDATE encounters SET end=? WHERE id=?',(s.last,row[0]))
                    self.event(now,key,'No longer observed; departure unconfirmed')
            if now-s.last > 600:
                del self.sources[key]
                self.pending.discard(key)
        if now-self.pruned > 60:
            self.db.execute('DELETE FROM observations WHERE t<?',(now-86400,))
            self.db.execute('DELETE FROM events WHERE t<?',(now-7*86400,))
            self.db.execute('DELETE FROM encounters WHERE start<?',(now-30*86400,))
            self.db.execute('DELETE FROM observations WHERE rowid NOT IN (SELECT rowid FROM observations ORDER BY t DESC LIMIT 100000)')
            self.pruned = now
        self.db.commit()

    def ordered(self, now, mode='live'):
        items = [s for s in self.sources.values() if now-s.last <= 30]
        if mode == 'review':
            items = [s for s in items if s.key in self.pending]
        elif mode == 'known':
            items = [s for s in items if self.known(s.key)]
        else:
            items = [s for s in items if not self.known(s.key) and s.key not in self.pending]
        return sorted(items,key=lambda s:(-s.band,s.key))

    def close(self):
        for key,s in self.sources.items():
            self.db.execute('UPDATE encounters SET end=? WHERE key=? AND end IS NULL',(s.last,key))
        self.db.commit()
        self.db.close()
