"""Supplementary staging samples; never contribute to production reliability."""
import json
import threading
import time
import urllib.request
from measurement_records import request_record
from measure_trial import now, sample, read


class StagingObserver:
    def __init__(self, config, directory):
        self.config, self.directory = config, directory
        self.stop = threading.Event()
        self.threads = [threading.Thread(target=self.run, args=(kind,), daemon=True) for kind in ('workload','observations')]

    def start(self):
        for t in self.threads: t.start()

    def run(self, kind):
        try:
            credential = read(self.config['credential_file'])
            ordinal = 0
            with (self.directory / ('staging-'+kind+'.jsonl')).open('x') as stream:
                while not self.stop.is_set():
                    start, stamp = time.monotonic(), now()
                    if kind == 'observations':
                        row = sample(self.config)
                    else:
                        ordinal += 1
                        request_id = 'staging-' + str(ordinal)
                        with (self.directory/'staging-workload-starts.jsonl').open('a') as starts:
                            starts.write(json.dumps(dict(request_id=request_id,request_started_at=stamp))+'\n')
                        status = valid = matches = failure = None
                        try:
                            req = urllib.request.Request(self.config['production_url']+'/api/v1/'+credential['sentinel_name'],
                                headers={'Authorization':'Bearer '+credential['token'],'X-Experiment-Stream':'independent','X-Experiment-Request':request_id})
                            with urllib.request.urlopen(req, timeout=3) as response:
                                status=response.status; body=json.load(response)
                                valid=isinstance(body,dict); matches=body.get('content')==credential['sentinel_content'] if valid else None
                        except Exception as exc:
                            failure=exc; status=getattr(exc,'code',status)
                        row=request_record(stamp,now(),time.monotonic()-start,status,valid,matches,failure)
                        row['request_id']=request_id
                    stream.write(json.dumps(row)+'\n'); stream.flush()
                    self.stop.wait(max(0,(1 if kind=='workload' else 2)-(time.monotonic()-start)))
        except Exception as exc:
            (self.directory/('staging-'+kind+'-error.json')).write_text(json.dumps({'measurement_error':True,'error_type':type(exc).__name__}))

    def close(self):
        self.stop.set()
        for t in self.threads: t.join(timeout=20)
        if any(t.is_alive() for t in self.threads):
            raise RuntimeError('Staging observer unresolved')
