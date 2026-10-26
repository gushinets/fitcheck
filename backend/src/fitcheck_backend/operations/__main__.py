import argparse
from datetime import datetime, timezone
import json
import sys
from ..config import Settings
from ..storage.database import create_engine
from .retention import cleanup


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('command',choices=['cleanup'])
    parser.add_argument('--limit',type=int,default=100)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--execute',action='store_true')
    modes.add_argument('--dry-run',action='store_true')
    engine = None
    try:
        args = parser.parse_args(argv)
        engine = create_engine(Settings())
        print(json.dumps(cleanup(engine,now=datetime.now(timezone.utc),execute=args.execute,limit=args.limit),sort_keys=True))
        return 0
    except Exception:
        print('Maintenance failed; check database access and retry. No credentials are logged.',file=sys.stderr)
        return 1
    finally:
        if engine is not None: engine.dispose()


if __name__=='__main__': raise SystemExit(main())
