"""Versioned, treatment-independent candidate fault schedules. No controller inputs."""
import hashlib
import json
import math
import threading
import time
import uuid
from functools import lru_cache
from collections import Counter
from pathlib import Path

VERSION = 'memos-phase7-v1'
CATALOGUE = Path(__file__).with_name('scenario-catalogue.json')


def catalogue():
    result = json.loads(CATALOGUE.read_text())['scenarios']
    matrix = CATALOGUE.with_name('matrix-scenarios.json')
    if matrix.exists():
        extra = json.loads(matrix.read_text())['scenarios']
        if set(result) & set(extra):
            raise ValueError('Matrix overrides a baseline scenario')
        for key, spec in extra.items():
            if key != spec['id'] or not key.startswith('P8'):
                raise ValueError('Invalid matrix scenario identity')
            validate(spec)
        result.update(extra)
    return result


def resolve(name):
    spec = catalogue()[name]
    if spec['status'] != 'implemented':
        raise ValueError('Scenario is deferred: ' + name)
    return validate(spec)


def validate(spec):
    if spec.get('version') != VERSION or spec.get('stage') not in ('staging', 'production'):
        raise ValueError('Unsupported scenario version/environment')
    if type(spec.get('seed')) is not int or spec.get('horizon_seconds') != 300:
        raise ValueError('Explicit seed and 300-second horizon required')
    previous = 0
    ids = set()
    for e in spec['episodes']:
        if e['id'] in ids:
            raise ValueError('Duplicate episode')
        ids.add(e['id'])
        if not all(type(e[k]) in (int, float) and math.isfinite(e[k]) for k in ('start', 'end', 'error_percent', 'delay_ms')):
            raise ValueError('Finite numerical episode parameters required')
        if not previous <= e['start'] < e['end'] <= 300:
            raise ValueError('Episodes must be ordered, disjoint and within horizon')
        if not 0 <= e['error_percent'] <= 100 or not 0 <= e['delay_ms'] <= 5000:
            raise ValueError('Invalid error/delay parameter')
        if e.get('status', 503) not in (429, 500, 502, 503):
            raise ValueError('Unsupported injected HTTP status')
        if e.get('mode', 'request') not in ('request', 'telemetry_missing', 'content'):
            raise ValueError('Unsupported fault mechanism')
        model = e.get('error_model', 'probability')
        if model not in ('probability', 'exact_count'):
            raise ValueError('Unsupported error selection model')
        if model == 'exact_count':
            n, k = e.get('block_size'), e.get('failure_count')
            if (type(n) is not int or type(k) is not int or not 1 <= n <= 10000
                    or not 0 <= k <= n or e['error_percent'] != 100*k/n
                    or e.get('mode', 'request') != 'request'):
                raise ValueError('Invalid exact-count block contract')
        previous = e['end']
    return spec


def lease(spec, identity, start_epoch, start_monotonic):
    validate(spec)
    required = ('trial_id', 'project', 'release_sha', 'image_id', 'environment')
    if identity.get('release') != 'v2' or identity.get('environment') != spec['stage'] or not all(identity.get(k) for k in required):
        raise ValueError('Explicit owned candidate-v2 identity required')
    return dict(version=VERSION, spec=spec, target={k: identity[k] for k in required},
                start_epoch=start_epoch, start_monotonic=start_monotonic,
                boot_id=boot_id(), end_epoch=start_epoch+300,
                scenario=spec['id'], trial_id=identity['trial_id'])


def boot_id():
    path = Path('/proc/sys/kernel/random/boot_id')
    return path.read_text().strip() if path.exists() else 'windows-monotonic'


def matches(value, identity):
    return (value.get('version') == VERSION and identity.get('release') == 'v2'
            and set(value.get('target',{})) == {'trial_id','project','release_sha','image_id','environment'}
            and value['target']['environment'] == value['spec']['stage']
            and all(identity.get(k) == v for k, v in value['target'].items()))


@lru_cache(maxsize=4096)
def failure_positions(seed, episode_id, stream, block_index, block_size, failure_count):
    """Seeded SHA-256 rank selection, independent of Python random versions/order."""
    def rank(position):
        data = json.dumps(['exact-count-v1', seed, episode_id, stream, block_index, position], separators=(',', ':'))
        return hashlib.sha256(data.encode()).digest(), position
    return tuple(sorted(sorted(range(1, block_size+1), key=rank)[:failure_count]))


class Engine:
    def __init__(self, value, identity, emit=lambda row: None, clock=time.monotonic, sleep=time.sleep):
        validate(value['spec'])
        self.value, self.identity, self.emit = value, identity, emit
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.counts = Counter()
        self.instance_id = uuid.uuid4().hex  # integrity only; never seeds selection

    def episode(self, elapsed=None):
        if not matches(self.value, self.identity):
            return None
        if self.value['boot_id'] != boot_id():
            raise ValueError('Host reboot invalidates fault lease')
        elapsed = self.clock()-self.value['start_monotonic'] if elapsed is None else elapsed
        if elapsed < 0:
            raise ValueError('Reversed fault clock')
        return next((e for e in self.value['spec']['episodes'] if e['start'] <= elapsed < e['end']), None)

    def decision(self, route, method, stream='native', elapsed=None, request_id=None):
        e = self.episode(elapsed)
        measured = route.split('?')[0] == '/api/v1/memos' or route.split('?')[0].startswith('/api/v1/memos/')
        if not e or not measured or e.get('mode', 'request') == 'telemetry_missing':
            return None
        # Workload ID only separates the independent sample population. It never
        # gives acceptance/controller traffic a different fault probability.
        stream = 'independent' if stream == 'independent' else 'native'
        exact = e.get('error_model') == 'exact_count'
        with self.lock:
            key = (e['id'], stream, '*' if exact else method)
            self.counts[key] += 1
            ordinal = self.counts[key]
        payload = json.dumps([self.value['spec']['seed'], e['id'], stream, method, ordinal], separators=(',', ':'))
        draw = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], 'big') / 2**64
        block = {}
        if exact:
            size, count = e['block_size'], e['failure_count']
            index, position = (ordinal-1)//size+1, (ordinal-1)%size+1
            positions = failure_positions(self.value['spec']['seed'], e['id'], stream, index, size, count)
            injected = position in positions
            block = dict(error_model='exact_count', block_size=size, requested_failure_count=count,
                         block_index=index, block_position=position, selected_failure_positions=list(positions),
                         engine_instance=self.instance_id, request_id=request_id)
        else:
            injected = e['error_percent'] == 100 or draw < e['error_percent']/100
        result = dict(episode_id=e['id'], environment=self.identity['environment'],
                    stream=stream, method=method, ordinal=ordinal, requested_error_percent=e['error_percent'],
                    injected_error=injected, injected_status=e.get('status',503) if injected else None,
                    configured_delay_ms=e['delay_ms'], mode=e.get('mode','request'),
                    seed=self.value['spec']['seed'], **block)
        if exact:
            # Durable arrival precedes delay/forwarding; missing completions cannot
            # silently disappear from the eligible denominator after interruption.
            self.emit(dict(event='fault_eligible', **result,
                           trial_id=self.identity['trial_id'], project=self.identity['project']))
        return result

    def delay(self, decision):
        if decision and not decision['injected_error'] and decision['configured_delay_ms']:
            self.sleep(decision['configured_delay_ms']/1000)

    def record(self, decision, status, elapsed_ms, delivered):
        if decision is not None:
            self.emit(dict(event='fault_request', **decision, status=status,
                           trial_id=self.identity['trial_id'], project=self.identity['project'],
                           observed_latency_ms=elapsed_ms, response_delivered=delivered))

    def telemetry_missing(self):
        e = self.episode()
        return bool(e and e.get('mode') == 'telemetry_missing')


def summary(rows):
    groups = {}
    for row in rows:
        if row.get('event') != 'fault_request': continue
        key = (row['episode_id'], row['stream'])
        g = groups.setdefault(key, dict(episode_id=key[0], stream=key[1],
            requested_error_percent=row['requested_error_percent'], configured_delay_ms=row['configured_delay_ms'],
            observed_latency_ms_sum=0, requests=0, injected_errors=0, delivered_errors=0))
        if g['requested_error_percent'] != row['requested_error_percent']:
            raise ValueError('Episode has inconsistent requested rate')
        g['requests'] += 1
        g['observed_latency_ms_sum'] += row['observed_latency_ms']
        g['injected_errors'] += bool(row['injected_error'])
        g['delivered_errors'] += bool(row['injected_error'] and row['response_delivered'])
    return [dict(g, realized_error_rate=g['injected_errors']/g['requests'], observed_latency_ms_mean=g['observed_latency_ms_sum']/g['requests']) for g in groups.values()]


def block_summary(rows, spec):
    """Audit exact blocks from arrivals AND completions; no partial-rate claim."""
    arrivals, completions, instances = {}, {}, set()
    episodes = {e['id']: e for e in spec['episodes']}
    for row in rows:
        if row.get('error_model') != 'exact_count':
            continue
        ep = episodes[row['episode_id']]
        expected = failure_positions(spec['seed'], ep['id'], row['stream'], row['block_index'], ep['block_size'], ep['failure_count'])
        if (row['selected_failure_positions'] != list(expected) or row['block_size'] != ep['block_size']
                or row['requested_failure_count'] != ep['failure_count'] or row['seed'] != spec['seed']
                or row['stream'] not in ('independent', 'native')
                or row['block_position'] != (row['ordinal']-1)%ep['block_size']+1
                or row['block_index'] != (row['ordinal']-1)//ep['block_size']+1
                or row['injected_error'] != (row['block_position'] in expected)):
            raise ValueError('Exact-count request differs from declared seed/block')
        instances.add(row['engine_instance'])
        key = (row['episode_id'], row['stream'], row['ordinal'])
        dest = arrivals if row['event'] == 'fault_eligible' else completions
        if key in dest and dest[key] != row:
            raise ValueError('Conflicting exact-count request ordinal')
        dest[key] = row
    if len(instances) > 1:
        raise ValueError('Injector restarted during exact-count exposure; continuity unverified')
    if set(completions)-set(arrivals):
        raise ValueError('Exact-count completion lacks durable eligible arrival')
    for key, row in completions.items():
        if any(row.get(k) != v for k,v in arrivals[key].items() if k != 'event'):
            raise ValueError('Exact-count completion identity differs from arrival')
    for episode_id, stream in {(k[0],k[1]) for k in arrivals}:
        ordinals=sorted(k[2] for k in arrivals if k[:2]==(episode_id,stream))
        if ordinals != list(range(1,len(ordinals)+1)):
            raise ValueError('Missing eligible request evidence')
    groups = {}
    for key, row in arrivals.items():
        group = (row['episode_id'],row['stream'],row['block_index'])
        g = groups.setdefault(group, dict(episode_id=group[0],stream=group[1],block_index=group[2],
            block_size=row['block_size'],requested_failure_count=row['requested_failure_count'],
            selected_failure_positions=row['selected_failure_positions'],actual_eligible_requests=0,
            completed_proxy_requests=0,selected_failures=0,injected_failures=0,delivered_failures=0))
        g['actual_eligible_requests'] += 1
        g['selected_failures'] += bool(row['injected_error'])
        done=completions.get(key)
        g['completed_proxy_requests'] += bool(done)
        injected=bool(done and done['injected_error'] and done['status']==done['injected_status'])
        g['injected_failures'] += injected
        g['delivered_failures'] += bool(injected and done['response_delivered'])
    result=[]
    for g in groups.values():
        complete = g['actual_eligible_requests']==g['block_size']
        result.append(dict(g,partial_block=not complete,
            status='complete' if complete else 'partial',
            completion_evidence_complete=g['completed_proxy_requests']==g['actual_eligible_requests'],
            requested_rate=g['requested_failure_count']/g['block_size'],
            exact_realized_rate=g['injected_failures']/g['block_size'] if complete and g['completed_proxy_requests']==g['block_size'] and g['injected_failures']==g['requested_failure_count'] else None,
            delivered_definition='proxy response write completed; client receipt verified separately'))
    # Explicit zero-exposure records, including episodes bypassed by rollback.
    for ep in spec['episodes']:
        if ep.get('error_model')!='exact_count':continue
        for stream in ('independent','native'):
            if any(g['episode_id']==ep['id'] and g['stream']==stream for g in result):continue
            result.append(dict(episode_id=ep['id'],stream=stream,block_index=1,block_size=ep['block_size'],
                requested_failure_count=ep['failure_count'],actual_eligible_requests=0,
                selected_failure_positions=list(failure_positions(spec['seed'],ep['id'],stream,1,ep['block_size'],ep['failure_count'])),
                selected_failures=0,injected_failures=0,delivered_failures=0,completed_proxy_requests=0,partial_block=True,
                status='not_started',completion_evidence_complete=True,exact_realized_rate=None,
                requested_rate=ep['failure_count']/ep['block_size']))
    return result


def boundaries(value):
    """Predeclared timestamps, distinct from observer delivery timestamps."""
    episodes=value['spec']['episodes']
    for i,e in enumerate(episodes):
        contiguous=i+1<len(episodes) and episodes[i+1]['start']==e['end']
        for event, offset in [('episode_started',e['start']),('episode_ended' if contiguous else 'episode_cleared',e['end'])]:
            yield dict(event=event, episode_id=e['id'], scheduled_epoch=value['start_epoch']+offset,
                       offset_seconds=offset, environment=value['target']['environment'],
                       mode=e.get('mode','request'), requested_error_percent=e['error_percent'],
                       configured_delay_ms=e['delay_ms'])


def watch(path, emit, stop):
    """Observe a declared schedule, never trigger it from treatment decisions."""
    delivered = set()
    while not stop.wait(.05):
        if not Path(path).exists(): continue
        value = json.loads(Path(path).read_text())
        if value.get('version') != VERSION: continue
        for row in boundaries(value):
            key = (row['episode_id'], row['event'])
            if key not in delivered and time.monotonic() >= value['start_monotonic']+row['offset_seconds']:
                emit(row)
                delivered.add(key)


def finalize_evidence(directory):
    directory=Path(directory)
    schedule=directory/'scenario-schedule.json'
    if not schedule.exists():return
    declared=json.loads(schedule.read_text())
    target=declared['target']
    records={}
    for path in [directory/'fault-events.jsonl',*directory.rglob('fault-requests.jsonl')]:
        if not path.exists():continue
        for line in path.read_text().splitlines():
            row=json.loads(line)
            if row.get('event') not in ('fault_request','fault_eligible'):continue
            if row.get('trial_id')!=target['trial_id'] or row.get('project')!=target['project']:
                raise ValueError('Foreign fault evidence')
            key=(row['event'],row['episode_id'],row['stream'],row['ordinal'],row.get('method','GET'))
            clean={k:v for k,v in row.items() if k not in ('timestamp','scenario')}
            if key in records and records[key]!=clean:raise ValueError('Conflicting duplicate fault evidence')
            records[key]=clean
    blocks=block_summary(records.values(),declared['spec'])
    report={'version':VERSION,'groups':summary(records.values()),'blocks':blocks,
            'exact_requests':[r for r in records.values() if r.get('error_model')=='exact_count'],
            'evidence_complete':all(b['completion_evidence_complete'] for b in blocks)}
    (directory/'fault-summary.json').write_text(json.dumps(report,indent=2))
