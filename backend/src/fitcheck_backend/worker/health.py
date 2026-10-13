import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4


class WorkerHealth:
    def __init__(self,path,*,clock=time.time,max_age=45):
        self.path,self.clock,self.max_age = Path(path),clock,max_age
        self.boot_id = str(uuid4())

    def mark(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(pid=os.getpid(),at=self.clock(),bootId=self.boot_id,maxAge=self.max_age)))
        temporary.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


def healthy(path,*,now=None):
    try:
        value = json.loads(Path(path).read_text())
        age = (time.time() if now is None else now) - value['at']
        max_age = value.get('maxAge',45)
        if not math.isfinite(age) or not math.isfinite(max_age) or not 0 <= age <= max_age or max_age <= 0:
            return False
        if type(value['pid']) is not int or value['pid'] <= 0: return False
        os.kill(value['pid'],0)
        return True
    except (OSError,ValueError,TypeError,KeyError):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if healthy(os.environ.get('FITCHECK_WORKER_HEALTH_PATH','/tmp/fitcheck-worker-health.json')) else 1)
