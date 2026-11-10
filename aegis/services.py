import asyncio
import json
import os
import queue
import re
import subprocess
import threading
import time


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20,
                            env={**os.environ, 'LC_ALL':'C'})
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:240] or 'Command failed')
    return result.stdout


def fields(line):
    """Parse nmcli escaped colons and backslashes, including SSIDs."""
    out, word, escaped = [], '', False
    for c in line:
        if escaped:
            word += c
            escaped = False
        elif c == '\\':
            escaped = True
        elif c == ':':
            out.append(word)
            word = ''
        else:
            word += c
    out.append(word)
    return out


def probe(line):
    p = line.rstrip('\n').split('\t')
    if len(p) != 3 or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',p[1]):
        return None
    try:
        return float(p[0]), p[1].lower(), float(p[2].split(',')[0]) if p[2] else None
    except ValueError:
        return None


def monitor_interfaces(text):
    """Select only interfaces whose current mode is monitor, in stable order."""
    found, current = set(), None
    for line in text.splitlines():
        match = re.fullmatch(r'\s*Interface ([\w.-]{1,32})\s*',line)
        if match:
            current = match.group(1)
        elif line.strip().startswith('phy#'):
            current = None
        elif line.strip() == 'type monitor' and current:
            found.add(current)
    return sorted(found)


class Services:
    def __init__(self, adapter=None, probe_interface=None):
        self.events = queue.Queue(maxsize=4000)
        self.stop = threading.Event()
        self.adapter, self.probe_interface = adapter, probe_interface
        self.threads = []
        self.dropped = 0

    def emit(self, kind, data):
        try:
            self.events.put_nowait((kind,data))
        except queue.Full:
            self.dropped += 1

    def start(self):
        for fn in (self.bluetooth,self.wifi,self.probes):
            t = threading.Thread(target=fn,daemon=True)
            self.threads.append(t)
            t.start()

    def bluetooth(self):
        async def scan():
            from bleak import BleakScanner
            def received(device, advert):
                services = advert.service_uuids or []
                kind = 'Type unknown'
                if any(s.lower().startswith('0000180d-') for s in services):
                    kind = 'Heart-rate service advertised'
                elif any(s.lower().startswith('00001812-') for s in services):
                    kind = 'Input-device service advertised'
                company = ','.join(hex(i) for i in advert.manufacturer_data)
                self.emit('ble',(device.address,advert.local_name or device.name or '',advert.rssi,
                                  time.time(),f'{kind}; manufacturer IDs {company or "unavailable"}'))
            opts = {'bluez':{'adapter':self.adapter}} if self.adapter else {}
            async with BleakScanner(detection_callback=received, **opts):
                self.emit('status',('Bluetooth','Scanning advertisements'))
                while not self.stop.is_set():
                    await asyncio.sleep(.25)
        while not self.stop.is_set():
            try:
                asyncio.run(scan())
            except Exception as exc:
                self.emit('status',('Bluetooth',f'Unavailable: {exc}. Retrying in 10 seconds.'))
            if self.stop.wait(10):
                break

    def wifi(self):
        while not self.stop.is_set():
            try:
                text = run(['nmcli','-t','-e','yes','-f','BSSID,SSID,CHAN,SIGNAL,SECURITY,IN-USE',
                            'device','wifi','list','--rescan','yes'])
                rows = [fields(line) for line in text.splitlines()]
                self.emit('wifi',[r for r in rows if len(r)==6])
                self.emit('status',('Wi-Fi',f'Updated {time.strftime("%H:%M:%S")}; refresh every 30 seconds'))
            except Exception as exc:
                self.emit('status',('Wi-Fi',str(exc)))
            try:
                rows = json.loads(run(['ip','-j','neigh','show']))
                self.emit('neighbors',rows)
                self.emit('status',('Local devices','Neighbor cache only; not a complete router client list'))
            except Exception as exc:
                self.emit('status',('Local devices',str(exc)))
            if self.stop.wait(30):
                break

    def probes(self):
        while not self.stop.is_set():
            try:
                iface = self.probe_interface
                if not iface:
                    interfaces = monitor_interfaces(run(['iw','dev']))
                    if not interfaces:
                        raise RuntimeError('No active monitor interface found. Waiting for the monitor adapter')
                    iface = interfaces[0]
                self.capture_probes(iface)
            except Exception as exc:
                self.emit('status',('Probe requests',f'Unavailable: {exc}. Retrying in 10 seconds.'))
            if self.stop.wait(10):
                break

    def capture_probes(self, iface):
        try:
            if not re.fullmatch(r'[\w.-]{1,32}',iface):
                raise ValueError('Invalid interface name')
            info = run(['iw','dev',iface,'info'])
            if not re.search(r'^\s*type monitor\s*$',info,re.M):
                raise ValueError('Selected adapter is not in monitor mode; use a dedicated monitor adapter')
            while not self.stop.is_set():
                self.emit('status',('Probe requests',f'Listening on {iface}; current channel only'))
                # Header fields only, no SSID histories or packet files. Bounded runs
                # ensure shutdown, errors, and hardware loss are observed promptly.
                process = subprocess.Popen(['tshark','-l','-n','-i',iface,'-a','duration:5',
                    '-f','type mgt subtype probe-req','-T','fields',
                    '-e','frame.time_epoch','-e','wlan.sa','-e','radiotap.dbm_antsignal'],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    out, err = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise RuntimeError('Capture timed out')
                if process.returncode:
                    raise RuntimeError(err[-240:])
                for line in out.splitlines():
                    row = probe(line)
                    if row:
                        self.emit('probe',row)
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
