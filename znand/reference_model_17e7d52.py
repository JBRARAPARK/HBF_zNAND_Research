"""Deterministic discrete-event model. Time: us, sizes: bytes, bandwidth: GB/s.
Not a NAND/AXI protocol implementation. Payloads are represented by physical tags.
"""
from dataclasses import dataclass, asdict
from collections import deque, Counter
import heapq
import math
import random
import json
from functools import lru_cache
from pathlib import Path

PAGE = 16384
EPS = 1e-9

@dataclass(frozen=True)
class Config:
    ports: int = 4
    channels: int = 4
    planes: int = 8
    stripe: int = 4096
    outstanding: int = 128
    buffer_pages: int = 512
    ca_us: float = .1
    output_ca_us: float = .1
    io_gbps: float = 80.1125
    turnaround_us: float = .05
    ecc_us: float = .2
    lookup_us: float = .5
    lookup_clock_mhz: float = 500.
    lookup_pipelines: int = 2
    lookup_slots: int = 500
    host_bits: int = 512
    host_mhz: float = 1000.
    first_us: float = 20.69
    short_us: float = 2.
    mid_us: float = 2.08
    long_us: float = 12.16
    group_us: float = 20.69
    availability: float = .85
    maintenance_period_us: float = 100.
    maintenance_sync: bool = False
    prefetch: bool = False
    accuracy: float = 1.
    lead_us: float = 10.
    prefetch_limit: int = 128
    seed: int = 7
    remap_fraction: float = 0.
    snapshot: str = ''
    trace: bool = False
    ca_policy: str = 'fifo'
    locality_max_bypass: int = 8
    locality_age_us: float = 1000.

    def validate(self):
        assert self.ca_policy in ('fifo', 'locality')
        assert isinstance(self.locality_max_bypass,int) and self.locality_max_bypass > 0
        assert math.isfinite(self.locality_age_us) and self.locality_age_us >= 0
        assert 1 <= self.ports <= 4 and self.channels == 4
        assert isinstance(self.planes, int) and self.planes in (8, 16)
        assert self.stripe in (4096, 16384)
        assert self.buffer_pages >= self.ports + 1
        assert min(self.outstanding, self.lookup_slots, self.lookup_pipelines) > 0
        assert 0 < self.availability <= 1 and self.maintenance_period_us > 0
        assert 0 <= self.accuracy <= 1 and 0 <= self.remap_fraction <= 1
        assert min(self.ca_us, self.output_ca_us, self.ecc_us, self.lookup_us,
                   self.turnaround_us, self.lead_us, self.first_us, self.short_us,
                   self.mid_us, self.long_us, self.group_us) >= 0
        assert min(self.io_gbps, self.host_bits, self.host_mhz, self.lookup_clock_mhz) > 0
        assert self.host_bits % 8 == 0 and self.prefetch_limit > 0


def address(q):
    """Plane-local sequential page -> (group, descending WL, block, SSL, E/O)."""
    r = q % 10104
    return (q // 10104, 420-r//24, (r%24)//12, (r%12)//2, r%2)


def tr_kind(previous, current):
    if previous is None:
        return 'first'
    if address(previous)[0] != address(current)[0]:
        return 'group'
    if current == previous + 1:
        return 'short' if current % 2 else 'mid'
    return 'long'


class Mapper:
    def __init__(self, c):
        self.c = c
        self.external = None
        if c.snapshot:
            doc = json.loads(Path(c.snapshot).read_text())
            assert doc['page_bytes'] == PAGE
            # Legacy MQSim snapshots describe the original 4x8 geometry.
            # A 4x16 experiment must explicitly declare its imported layout.
            geometry = doc.get('model_geometry')
            expected = {'channels': c.channels, 'planes_per_channel': c.planes}
            if (geometry is not None and geometry != expected) or (c.planes == 16 and geometry != expected):
                raise ValueError('snapshot model_geometry must match channels and planes_per_channel')
            self.external = {int(k): tuple(v) for k,v in doc['mapping'].items()}
            assert len(set(self.external.values())) == len(self.external)
            for ch,pl,q in self.external.values():
                assert 0 <= ch < c.channels and 0 <= pl < c.planes and q >= 0

    @lru_cache(maxsize=262144)
    def map(self, byte_address):
        c = self.c
        if c.stripe == 4096:
            l = byte_address//4096
            ch = l % c.channels
            slot = (l//c.channels)//4
            offset = ((l//c.channels)%4)*4096+byte_address%4096
        else:
            page = byte_address//PAGE
            ch = page%c.channels
            slot = page//c.channels
            offset = byte_address%PAGE
        pl = slot%c.planes
        q = slot//c.planes
        # External snapshot is a 16KiB-slot permutation applied AFTER packing.
        # Preserve imported channel/plane and use rank within plane, not native WL.
        packed_id = (q*c.planes+pl)*c.channels+ch
        if self.external is not None:
            if packed_id not in self.external:
                raise ValueError(f'snapshot missing packed page {packed_id}')
            return self.external[packed_id], offset
        if c.remap_fraction and random.Random(c.seed+packed_id*65537).random()<c.remap_fraction:
            # One-to-one relocation into disjoint fresh groups, synthetic only.
            q = 10104*100 + q*37
        return (ch,pl,q), offset


@dataclass(frozen=True)
class Input:
    port: int
    addr: int
    size: int
    offer: float


def workload(pattern='B3', ports=4, per_port=2048, overlap=0., host_mhz=1000., seed=7):
    """Finite, nonwrapping trace. B3 revisits at +64B, not same data.
    A2/B2 are local nonsequential 1,3,2 permutations, NOT uniform random.
    """
    assert pattern in ('A1','A2','B1','B2','B3') and 0 <= overlap <= 1
    size = 4096 if pattern.startswith('A') else 64
    step = max(1,math.ceil(size/64))/host_mhz
    span = ((per_port*4096+PAGE*32-1)//(PAGE*32))*PAGE*32
    result=[]
    for p in range(ports):
        for i in range(per_port):
            if pattern == 'B3':
                group,k = divmod(i,4)
                logical = group*3+(0,2,0,1)[k]
                offset = 64 if k == 2 else 0
            elif pattern in ('A2','B2'):
                group,k=divmod(i,3)
                logical=group*3+(0,2,1)[k];offset=0
            else:
                logical=i;offset=0
            # Select shared/unique by group to keep B3 revisit association intact.
            shared = random.Random(seed+logical//3).random()<overlap
            base = 0 if shared else (p+1)*span
            result.append(Input(p,base+logical*4096+offset,size,30.+i*step))
    return sorted(result,key=lambda r:(r.offer,r.port))


class Simulator:
    def __init__(self,c,inputs):
        c.validate(); self.c=c; self.mapper=Mapper(c); self.now=0.; self.serial=0
        self.events=[];self.log=[];self.count=Counter();self.items={};self.used_peak=0
        self.req=[];self.sources=[deque() for _ in range(c.ports)]
        self.fifo=[deque() for _ in range(c.ports)]
        self.lookupq=[deque() for _ in range(c.ports)]
        self.lookup_active=[0]*c.ports
        self.lanes=[[0.]*c.lookup_pipelines for _ in range(c.ports)]
        self.next_ar=[0.]*c.ports;self.rb=[False]*c.ports;self.peak=[0]*c.ports
        self.ca=[False]*c.channels;self.data=[False]*c.channels
        self.locality_bypasses=Counter()
        self.plane={ (ch,pl):dict(busy=False,last=None,pb=None,off=False,pending=0) for ch in range(c.channels) for pl in range(c.planes)}
        self.cb=[0.]*c.channels;self.db=[0.]*c.channels
        self.channel_data=[0]*c.channels;self.first_nand=None
        self.nextwake=None;self.finished=0;self.taskseq=0
        self.last_r=[-1]*c.ports;self.busy_intervals=[]
        if c.availability<1:
            for key in self.plane:
                phase=0. if c.maintenance_sync else random.Random(c.seed+key[0]*97+key[1]*13).random()*c.maintenance_period_us
                self.event(phase,'maintenance_due',key)
        for inp in inputs:
            assert 0<=inp.port<c.ports and inp.size in (64,4096) and inp.addr%inp.size==0
            key,off=self.mapper.map(inp.addr)
            assert off+inp.size<=PAGE
            idx=len(self.req)
            self.req.append(dict(port=inp.port,addr=inp.addr,size=inp.size,offer=inp.offer,key=key,
                                 offset=off,lookup=False,accepted=None,ready=None,end=None))
            self.sources[inp.port].append(idx)
            self.event(inp.offer,'wake')
        assert self.req
        if c.prefetch:
            # Deduplicate by physical page; oracle candidate timing from first offered demand.
            first={}
            for r in self.req:first.setdefault(r['key'],r['offer'])
            rng=random.Random(c.seed)
            for k,t in first.items():
                correct=rng.random()<c.accuracy
                target=k if correct else (k[0],k[1],k[2]+10104*1000)
                self.event(max(0.,t-c.lead_us),'prefetch',target)
        self.pump()

    def event(self,t,kind,data=None):
        assert t >= self.now-EPS,(t,self.now,kind)
        self.serial+=1;heapq.heappush(self.events,(max(t,self.now),self.serial,kind,data))

    def trace(self,kind,**kw):
        if self.c.trace:self.log.append(dict(time_us=self.now,event=kind,**kw))

    def wake(self,t):
        if t>self.now+EPS and (self.nextwake is None or t<self.nextwake-EPS):
            self.nextwake=t;self.event(t,'timer',t)

    def capacity(self,head=False):
        # Reserve one free slot for each port with no accepted head. Already
        # accepted requests claim their page atomically; pins cannot deadlock heads.
        reserve=sum(not q and bool(self.sources[p]) for p,q in enumerate(self.fifo))
        if head:reserve=max(0,reserve-1)
        while len(self.items)+1+reserve>self.c.buffer_pages:
            candidates=[x for x in self.items.values() if not x['refs'] and x['state']=='ready']
            if not candidates:return False
            victim=min(candidates,key=lambda x:(x['ready'],x['seq']))
            del self.items[victim['key']];self.count['prefetch_evicted']+=1
            self.trace('evict',key=victim['key'])
        return True

    def new_item(self,key,pf=False):
        self.taskseq+=1
        x=dict(key=key,state='waiting',refs=set(),pf=pf,used=False,seq=self.taskseq,ready=None,
               queued=self.now,eligible=self.now if pf else None,transfer_ready=None)
        self.items[key]=x;self.used_peak=max(self.used_peak,len(self.items))
        return x

    def admit(self):
        for p in range(self.c.ports):
            if not self.sources[p] or len(self.fifo[p])>=self.c.outstanding:continue
            idx=self.sources[p][0];r=self.req[idx]
            when=max(r['offer'],self.next_ar[p])
            if when>self.now+EPS:self.wake(when);continue
            x=self.items.get(r['key'])
            if x is None:
                if not self.capacity(head=not self.fifo[p]):
                    self.count['buffer_admission_stalls']+=1;continue
                x=self.new_item(r['key'])
            else:
                self.count['merged_at_accept']+=1
            x['refs'].add(idx)
            self.sources[p].popleft();self.fifo[p].append(idx);self.lookupq[p].append(idx)
            r['accepted']=self.now;r['merged_state']=x['state']
            self.next_ar[p]=self.now+1/self.c.host_mhz
            self.peak[p]=max(self.peak[p],len(self.fifo[p]))
            self.trace('accept',request=idx,port=p,key=r['key'])
            if self.sources[p] and len(self.fifo[p])<self.c.outstanding:self.wake(self.next_ar[p])

    def lookups(self):
        c=self.c
        for p in range(c.ports):
            while self.lookupq[p] and self.lookup_active[p]<c.lookup_slots:
                lane=min(range(c.lookup_pipelines),key=lambda i:self.lanes[p][i])
                t=math.ceil((max(self.now,self.lanes[p][lane])-EPS)*c.lookup_clock_mhz)/c.lookup_clock_mhz
                if t>self.now+EPS:self.wake(t);break
                idx=self.lookupq[p].popleft()
                self.req[idx]['lookup_start']=self.now
                self.lookup_active[p]+=1;self.lanes[p][lane]=self.now+1/c.lookup_clock_mhz
                self.event(self.now+c.lookup_us,'lookup',idx)

    def begin_maintenance(self,key):
        p=self.plane[key]
        if p['busy'] or p['off'] or not p['pending']:return
        p['off']=True
        duration=p['pending']*(1-self.c.availability)*self.c.maintenance_period_us
        p['pending']=0
        self.busy_intervals.append((key,self.now,self.now+duration))
        self.event(self.now+duration,'maintenance_end',key)
        self.trace('maintenance_start',key=key,duration=duration)

    def demand(self,x):
        return any(self.req[i]['lookup'] for i in x['refs'])

    def ca_candidates(self,waiting):
        """One issuable candidate per channel; the FIFO default is unchanged.

        Locality selection uses only already-eligible work and recorded page
        buffer/sensing state. It never waits for or invents a future request.
        Within each plane, demand wins over prefetch. A same-buffer page or
        q+1 in the same group may bypass older work, with age/count limits.
        Across planes retain the oldest represented work's ordering priority.
        """
        available=[]
        for x in waiting:
            ch,pl,q=x['key'];plane=self.plane[(ch,pl)]
            if not (self.ca[ch] or plane['busy'] or plane['off']):
                available.append(x)
        if self.c.ca_policy=='fifo':
            best={}
            for x in available:
                ch=x['key'][0];rank=(not self.demand(x),x['seq'])
                if ch not in best or rank<best[ch][0]:best[ch]=(rank,x)
            return best,{}
        planes={}
        for x in available:planes.setdefault(x['key'][:2],[]).append(x)
        best={};decisions={}
        for key,items in planes.items():
            plane=self.plane[key]
            demand=[x for x in items if self.demand(x)]
            tier=demand or items
            oldest=min(tier,key=lambda x:x['seq'])
            old_enough=self.now-oldest['eligible'] >= self.c.locality_age_us
            exhausted=self.locality_bypasses[key] >= self.c.locality_max_bypass
            selected=oldest;reason='oldest'
            if old_enough:reason='age'
            elif exhausted:reason='bypass_limit'
            else:
                local=[]
                for x in tier:
                    q=x['key'][2]
                    hit=plane['pb']==q
                    adjacent=plane['last'] is not None and q==plane['last']+1 and address(q)[0]==address(plane['last'])[0]
                    if hit or adjacent:local.append((not hit,x['seq'],x))
                if local:
                    selected=min(local,key=lambda item:item[:2])[2]
                    if selected is not oldest:reason='locality'
            rank=(not bool(demand),oldest['seq'])
            ch=key[0]
            if ch not in best or rank<best[ch][0]:
                best[ch]=(rank,selected)
                decisions[ch]=(key,selected is not oldest,reason)
        return best,decisions

    def dispatch(self):
        c=self.c
        waiting=[x for x in self.items.values() if x['state']=='waiting' and x['eligible'] is not None]
        best,decisions=self.ca_candidates(waiting)
        for ch,(_,x) in best.items():
            if ch in decisions:
                plane_key,bypassed,reason=decisions[ch]
                if bypassed:self.locality_bypasses[plane_key]+=1
                else:self.locality_bypasses[plane_key]=0
                self.count['ca_selection_'+reason]+=1
            key=x['key'];plane=self.plane[key[:2]]
            hit=plane['pb']==key[2]
            x['state']='ca';x['pb_hit']=hit;x['issue']=self.now
            plane['busy']=True;self.ca[ch]=True
            duration=c.output_ca_us if hit else c.ca_us
            self.cb[ch]+=duration
            if self.first_nand is None:self.first_nand=self.now
            self.event(self.now+duration,'ca_done',key)
            self.count['page_buffer_hits' if hit else 'sensing_reads']+=1
            if x['pf']:self.count['prefetch_started']+=1
            self.trace('ca_start',key=key,page_buffer_hit=hit,duration=duration)
        best={}
        for x in self.items.values():
            if x['state']!='sensed':continue
            ch=x['key'][0]
            if self.data[ch]:continue
            rank=(not self.demand(x),x['transfer_ready'],x['seq'])
            if ch not in best or rank<best[ch][0]:best[ch]=(rank,x)
        for ch,(_,x) in best.items():
            self.data[ch]=True;x['state']='transfer'
            dur=PAGE/(c.io_gbps*1000)+c.turnaround_us
            self.db[ch]+=dur;self.channel_data[ch]+=PAGE
            self.event(self.now+dur,'transferred',x['key'])
            self.trace('data_start',key=x['key'],duration=dur)

    def return_data(self):
        c=self.c
        for p in range(c.ports):
            if self.rb[p] or not self.fifo[p]:continue
            idx=self.fifo[p][0];r=self.req[idx];x=self.items[r['key']]
            if not r['lookup'] or x['state']!='ready':continue
            self.rb[p]=True;r['r_start']=self.now
            dur=math.ceil(r['size']/(c.host_bits/8))/c.host_mhz
            self.event(self.now+dur,'returned',idx)

    def pump(self):
        self.admit();self.lookups();self.dispatch();self.return_data()
        assert len(self.items)<=self.c.buffer_pages

    def run(self):
        while self.events and self.finished<len(self.req):
            t,_,kind,d=heapq.heappop(self.events);self.now=t
            if self.now>1e8:raise RuntimeError('progress timeout')
            c=self.c
            if kind=='maintenance_due':
                self.plane[d]['pending']+=1
                self.event(t+c.maintenance_period_us,'maintenance_due',d)
                self.begin_maintenance(d)
            elif kind=='maintenance_end':
                self.plane[d]['off']=False;self.begin_maintenance(d)
            elif kind=='timer':
                if self.nextwake==d:self.nextwake=None
            elif kind=='prefetch':
                self.count['prefetch_candidates']+=1
                if d in self.items:self.count['prefetch_duplicate']+=1
                elif sum(x['pf'] and not x['refs'] for x in self.items.values())>=c.prefetch_limit:
                    self.count['prefetch_dropped_budget']+=1
                elif self.capacity():self.new_item(d,True)
                else:self.count['prefetch_dropped_buffer']+=1
            elif kind=='lookup':
                r=self.req[d];r['lookup']=True;r['lookup_end']=t;self.lookup_active[r['port']]-=1
                x=self.items[r['key']]
                if x['eligible'] is None:x['eligible']=t
                if x['state']=='ready':
                    r['ready']=t;self.count['buffer_ready_hits']+=1
                if x['pf']:
                    if not x['used']:self.count['prefetch_useful_pages']+=1
                    x['used']=True
            elif kind=='ca_done':
                self.ca[d[0]]=False;x=self.items[d];plane=self.plane[d[:2]]
                if x['pb_hit']:
                    x['state']='sensed';x['transfer_ready']=t
                else:
                    k=tr_kind(plane['last'],d[2]);dur=getattr(c,k+'_us')
                    self.count['tr_'+k]+=1;x['state']='sensing'
                    self.event(t+dur,'sensed',d)
                    self.trace('sense_start',key=d,tr_kind=k,duration=dur)
            elif kind=='sensed':
                x=self.items[d];x['state']='sensed';x['transfer_ready']=t
                self.plane[d[:2]]['last']=d[2];self.plane[d[:2]]['pb']=d[2]
            elif kind=='transferred':
                self.data[d[0]]=False;self.plane[d[:2]]['busy']=False
                self.begin_maintenance(d[:2])
                self.items[d]['state']='ecc';self.count['nand_bytes']+=PAGE
                self.event(t+c.ecc_us,'ready',d)
            elif kind=='ready':
                x=self.items[d];x['state']='ready';x['ready']=t
                for i in x['refs']:
                    if self.req[i]['lookup']:self.req[i]['ready']=t
                self.trace('ready',key=d)
            elif kind=='returned':
                r=self.req[d];p=r['port'];x=self.items[r['key']]
                assert self.fifo[p].popleft()==d and d>self.last_r[p]
                self.last_r[p]=d;r['end']=t;self.rb[p]=False
                x['refs'].remove(d);self.finished+=1
                self.trace('returned',request=d,port=p,key=r['key'])
                if not x['refs']:
                    del self.items[r['key']];self.count['released_pages']+=1
            self.pump()
        if self.finished!=len(self.req):raise RuntimeError(f'deadlock: {self.finished}/{len(self.req)}')
        return self.results()

    def results(self):
        def avg(xs):return sum(xs)/len(xs)
        def quant(xs,p):return sorted(xs)[min(len(xs)-1,math.ceil(len(xs)*p)-1)]
        latency=[r['end']-r['accepted'] for r in self.req]
        offerlat=[r['end']-r['offer'] for r in self.req]
        total=sum(r['size'] for r in self.req)
        start=min(r['offer'] for r in self.req);end=max(r['end'] for r in self.req)
        # Rates in GB/s: bytes/us / 1000.
        # Middle half of completions avoids some fill/drain; report cold total too.
        ordered=sorted(self.req,key=lambda r:r['end'])
        a=len(ordered)//4;b=3*len(ordered)//4
        steadybytes=sum(r['size'] for r in ordered[a+1:b+1])
        steadytime=ordered[b]['end']-ordered[a]['end'] if b>a else 0
        hol=[max(0,r['r_start']-max(r['ready'],r['lookup_end'])) for r in self.req]
        return dict(requests=len(self.req),host_bytes=total,elapsed_us=end-start,
                    bandwidth_gbps=total/(end-start)/1000,
                    inclusive_prefetch_gbps=total/(end-min(start,self.first_nand if self.first_nand is not None else start))/1000,
                    middle_bandwidth_gbps=steadybytes/steadytime/1000 if steadytime else 0,
                    mean_latency_us=avg(latency),p95_latency_us=quant(latency,.95),p99_latency_us=quant(latency,.99),
                    mean_offer_latency_us=avg(offerlat),mean_return_wait_us=avg(hol),
                    buffer_peak_pages=self.used_peak,peak_outstanding=max(self.peak),
                    leftover_prefetch_pages=sum(x['pf'] and not x['refs'] for x in self.items.values()),
                    channel_nand_bytes=self.channel_data,
                    channel_ca_busy_us=self.cb,channel_data_busy_us=self.db,
                    actual_unavailable_fraction=sum(max(0,min(b,end)-max(a,start)) for _,a,b in self.busy_intervals)/((end-start)*self.c.channels*self.c.planes),
                    mean_lookup_queue_us=avg([r['lookup_start']-r['accepted'] for r in self.req]),
                    mean_data_wait_us=avg([r['ready']-r['lookup_end'] for r in self.req]),
                    mean_admission_wait_us=avg([r['accepted']-r['offer'] for r in self.req]),
                    max_inflight_host_bytes=max(self.peak)*self.req[0]['size'],
                    counts=dict(self.count),
                    config=asdict(self.c))
