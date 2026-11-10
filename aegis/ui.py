import csv
import hashlib
import queue
import shutil
import subprocess
import time
import tkinter as tk
from tkinter import ttk, filedialog, simpledialog, messagebox
from .core import Monitor, clean
from .services import Services


def clock(t):
    return time.strftime('%b %d %H:%M:%S',time.localtime(t)) if t else '—'


class App(tk.Tk):
    def __init__(self,args):
        super().__init__()
        self.title('Aegis Field • Linux')
        self.geometry('1180x820')
        self.minsize(850,650)
        self.configure(bg='#08171d')
        self.model = Monitor(args.data_dir/'observations.sqlite3')
        self.services = Services(args.adapter,args.probe_interface)
        self.status = {}
        self.probes = {}
        self.selected = None
        self.mode = tk.StringVar(value='live')
        self.still = tk.BooleanVar(value=False)
        self.defense = tk.BooleanVar(value=False)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.',background='#10252d',foreground='#e7f4f5',font=('Sans',11))
        style.configure('Treeview',background='#10252d',fieldbackground='#10252d',rowheight=29)
        style.map('Treeview',background=[('selected','#145f67')])
        style.configure('TButton',padding=8)
        style.configure('TNotebook.Tab',padding=(14,8))
        top = ttk.Frame(self,padding=16)
        top.pack(fill='x')
        ttk.Label(top,text='AEGIS FIELD',font=('Sans',22,'bold'),foreground='#20dfc7').pack(side='left')
        ttk.Checkbutton(top,text='Defense alerts',variable=self.defense,command=self.arm).pack(side='right',padx=12)
        ttk.Checkbutton(top,text='Laptop is stationary (manual)',variable=self.still,
                        command=lambda:self.model.motion(self.still.get())).pack(side='right')
        self.summary = ttk.Label(self,padding=12,text='Starting sensors…')
        self.summary.pack(fill='x')
        tabs = ttk.Notebook(self)
        tabs.pack(fill='both',expand=True,padx=12)
        ble = ttk.Frame(tabs,padding=10)
        tabs.add(ble,text='Bluetooth')
        controls = ttk.Frame(ble)
        controls.pack(fill='x')
        for label,value in [('Live unknown','live'),('Baseline review','review'),('Known','known')]:
            ttk.Radiobutton(controls,text=label,variable=self.mode,value=value).pack(side='left',padx=8)
        ttk.Button(controls,text='Mark known',command=lambda:self.mark(True)).pack(side='right')
        ttk.Button(controls,text='Unrecognized',command=lambda:self.mark(False)).pack(side='right')
        ttk.Button(controls,text='Rename',command=self.rename).pack(side='right')
        self.ble = self.table(ble,['Source','Signal','Trend','Confidence','Last seen'],height=8)
        self.ble.bind('<<TreeviewSelect>>',self.select)
        self.detail = ttk.Label(ble,text='Select a source to see its evidence.',wraplength=1000,padding=10)
        self.detail.pack(fill='x')
        self.chart = tk.Canvas(ble,height=175,bg='#08171d',highlightthickness=0)
        self.chart.pack(fill='both',expand=True)
        ttk.Label(ble,text='Stronger signals first in steady bands. RSSI is not distance. Confidence is a heuristic evidence score.',wraplength=1000).pack(fill='x',pady=5)
        self.wifi = self.tab_table(tabs,'Wi-Fi networks',['SSID','BSSID','Channel','Signal %','Security','Connected'],
            'Nearby access points, refreshed every 30 seconds. Signal percent is not RSSI or feet.')
        self.neighbors = self.tab_table(tabs,'Local devices',['IP','Address','Interface','Cache state'],
            'Devices in the operating system neighbor cache. This is incomplete and can contain stale entries.')
        self.probe_table = self.tab_table(tabs,'Searching devices',['Session ID','Requests','Last seen','RSSI'],
            'Probe requests on the selected monitor channel only. IDs are session-only; randomized addresses cannot identify people. No searched SSIDs are retained.')
        self.frequent = self.tab_table(tabs,'Encounters',['Name','Sessions','First recorded','Last recorded','Known'],
            'Repeat observations of the same identifier, not verified identities. History retained for 30 days.')
        self.activity = self.tab_table(tabs,'Activity',['Time','Source','Event'],'Newest events stay fixed until a new event arrives.')
        settings = ttk.Frame(tabs,padding=16)
        tabs.add(settings,text='Health & data')
        self.health = ttk.Label(settings,text='',wraplength=1000,justify='left')
        self.health.pack(fill='x',pady=12)
        ttk.Label(settings,text='Motion: manual confirmation only. GPS, camera room mapping, Apple pairing, and router quarantine are not available in this Linux edition.\n\nScanning continues while minimized; suspend or closing the app stops observation. No alert means only no qualifying evidence was received.\n\nRaw RSSI retained for 24 hours (100,000 sample cap); activity 7 days; encounter history 30 days. Known-device choices and learned signal baselines persist. Bluetooth addresses can rotate.',wraplength=980,justify='left').pack(fill='x',pady=20)
        ttk.Button(settings,text='Export encounter summary (CSV)',command=self.export).pack(anchor='w',pady=8)
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.services.start()
        self.after(250,self.refresh)

    def table(self,parent,columns,height=14):
        frame = ttk.Frame(parent)
        frame.pack(fill='both',expand=True,pady=8)
        tree = ttk.Treeview(frame,columns=columns,show='headings',height=height,selectmode='browse')
        for col in columns:
            tree.heading(col,text=col)
            tree.column(col,width=150,minwidth=80)
        scroll = ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left',fill='both',expand=True)
        scroll.pack(side='right',fill='y')
        return tree

    def tab_table(self,tabs,title,columns,note):
        frame = ttk.Frame(tabs,padding=12)
        tabs.add(frame,text=title)
        ttk.Label(frame,text=note,wraplength=1050).pack(fill='x')
        return self.table(frame,columns)

    def sync(self,tree,rows):
        wanted = {str(k) for k,v in rows}
        for key in tree.get_children():
            if key not in wanted:
                tree.delete(key)
        for index,(key,values) in enumerate(rows):
            key = str(key)
            if tree.exists(key):
                tree.item(key,values=values)
                if tree.index(key) != index:
                    tree.move(key,'',index)
            else:
                tree.insert('',index,iid=key,values=values)

    def arm(self):
        self.model.arm(self.defense.get(),time.time())

    def mark(self,known):
        if self.selected:
            self.model.review(self.selected,known)

    def rename(self):
        if self.selected:
            label = simpledialog.askstring('Label source','Your label for this source:',parent=self)
            if label is not None:
                self.model.review(self.selected,self.model.known(self.selected),label)

    def select(self,event=None):
        selected = self.ble.selection()
        if selected:
            self.selected = selected[0]

    def refresh(self):
        now = time.time()
        try:
            for _ in range(600):
                kind,data = self.services.events.get_nowait()
                if kind == 'ble':
                    self.model.ingest(*data)
                elif kind == 'status':
                    self.status[data[0]] = clean(data[1])
                elif kind == 'wifi':
                    self.sync(self.wifi,[(r[0],(clean(r[1]) or '(hidden)',r[0],r[2],r[3],r[4],r[5])) for r in sorted(data,key=lambda r:(-int(r[3] or 0),r[0]))])
                elif kind == 'neighbors':
                    self.sync(self.neighbors,[(str((r.get('dst'),r.get('dev'))),(r.get('dst'),r.get('lladdr','Unknown'),r.get('dev'),str(r.get('state')))) for r in data])
                elif kind == 'probe':
                    t,addr,rssi = data
                    # Ephemeral pseudonyms: never merge BLE and Wi-Fi identities.
                    key = hashlib.sha256((str(self.model.session_start)+addr).encode()).hexdigest()[:12]
                    count = self.probes.get(key,(0,0,None))[0]+1
                    self.probes[key] = count,t,rssi
        except queue.Empty:
            pass
        self.model.tick(now)
        profiles = {r[0]:r[1:] for r in self.model.db.execute('SELECT key,label,name,baseline,learned FROM devices')}
        rows = []
        for s in self.model.ordered(now,self.mode.get()):
            p = profiles[s.key]
            rows.append((s.key,(p[0] or p[1],f'{s.smooth:.0f} dBm',s.trend,f'{s.confidence}/100',f'{max(0,int(now-s.last))}s ago')))
        self.sync(self.ble,rows)
        s = self.model.sources.get(self.selected)
        self.chart.delete('all')
        if s:
            p = profiles[s.key]
            learned = f'{p[3]} baseline samples; usual {p[2]:.0f} dBm' if p[3] else 'Baseline still learning'
            self.detail.configure(text=f'{p[0] or p[1]} • {s.key}\n{s.metadata}\n{s.explanation} {learned}.\nStationary status is user-confirmed, not measured. Identity, distance, and danger are not established.')
            samples = list(s.samples)
            w,h = max(300,self.chart.winfo_width()),max(100,self.chart.winfo_height())
            for level in (-40,-70,-100):
                y = (abs(level)-25)/105*(h-25)
                self.chart.create_text(35,y,text=f'{level} dBm',fill='#9bb7bd')
            for (ta,ra),(tb,rb) in zip(samples,samples[1:]):
                if tb-ta <= 8:
                    self.chart.create_line(70+(ta-now+300)/300*(w-80),(abs(ra)-25)/105*(h-25),70+(tb-now+300)/300*(w-80),(abs(rb)-25)/105*(h-25),fill='#20dfc7',width=2)
            self.chart.create_text(w/2,h-12,text='Received RSSI • last five minutes • gaps stay empty',fill='#9bb7bd')
        else:
            self.detail.configure(text='Select a source to see its evidence.')
        self.probes = dict(sorted(((k,v) for k,v in self.probes.items() if now-v[1]<600),key=lambda kv:kv[1][1],reverse=True)[:1000])
        self.sync(self.probe_table,[(k,(k,v[0],clock(v[1]),f'{v[2]:.0f} dBm' if v[2] is not None else 'Unavailable')) for k,v in sorted(self.probes.items())])
        encounters = self.model.db.execute('''SELECT d.key,COALESCE(NULLIF(d.label,''),d.name),COUNT(e.id),MIN(e.start),MAX(COALESCE(e.end,e.start)),d.known FROM devices d JOIN encounters e ON e.key=d.key GROUP BY d.key ORDER BY COUNT(e.id) DESC,d.key LIMIT 200''').fetchall()
        self.sync(self.frequent,[(r[0],(r[1],r[2],clock(r[3]),clock(r[4]),'Yes' if r[5] else 'No')) for r in encounters])
        events = self.model.db.execute('SELECT id,t,key,message FROM events ORDER BY id DESC LIMIT 200').fetchall()
        self.sync(self.activity,[(r[0],(clock(r[1]),profiles.get(r[2],('','Session'))[1],r[3])) for r in events])
        active = sum(now-s.last<=8 for s in self.model.sources.values())
        self.summary.configure(text=f'{active} fresh Bluetooth sources • {len(self.model.pending)} awaiting review • '+('Baseline collection' if now<self.model.arm_until else 'Defense armed' if self.defense.get() else 'Observing'))
        self.health.configure(text='\n\n'.join(f'{k}: {v}' for k,v in self.status.items())+f'\n\nDropped observations: {self.services.dropped}')
        for key,message in self.model.alerts:
            self.bell()
            if shutil.which('notify-send'):
                subprocess.Popen(['notify-send','--app-name=Aegis Field','--','Aegis Field',message],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.model.alerts.clear()
        self.after(1000,self.refresh)

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')])
        if not path:
            return
        try:
            with open(path,'w',newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Source ID','Start','End'])
                for key,start,end in self.model.db.execute('SELECT key,start,end FROM encounters ORDER BY start'):
                    writer.writerow([hashlib.sha256(key.encode()).hexdigest()[:16],clock(start),clock(end)])
        except OSError as exc:
            messagebox.showerror('Export failed',str(exc))

    def close(self):
        self.services.stop.set()
        self.model.close()
        self.destroy()
