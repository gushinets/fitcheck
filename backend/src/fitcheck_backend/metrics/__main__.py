"""Operator CLI. Never print settings, SQL exceptions or raw validation inputs."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from ..config import Settings
from ..storage.database import create_engine
from .backfill import backfill_metrics
from .retention import cleanup_metrics, valid_limit
from .report import MetricReportService
from .report_types import ReportOptions, serializable
from .csv_export import write_csv


def parser():
    result = argparse.ArgumentParser(prog='python -m fitcheck_backend.metrics')
    commands = result.add_subparsers(dest='command', required=True)
    report = commands.add_parser('report')
    for flag in ('start', 'end', 'environment', 'population'):
        report.add_argument('--'+flag, required=True)
    report.add_argument('--timezone', default='Europe/Moscow')
    report.add_argument('--format', choices=('json', 'csv'), default='json')
    report.add_argument('--output', type=Path)
    backfill = commands.add_parser('backfill')
    backfill.add_argument('--environment', required=True, choices=('development', 'production', 'test'))
    backfill.add_argument('--limit', type=int, default=1000)
    cleanup = commands.add_parser('cleanup')
    cleanup.add_argument('--limit', type=int, default=1000)
    mode = cleanup.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute', action='store_true')
    return result


def main(argv=None):
    engine = None
    try:
        args = parser().parse_args(argv)
        if args.command == 'report':
            try:
                options = ReportOptions(start=datetime.fromisoformat(args.start), end=datetime.fromisoformat(args.end),
                    timezone=args.timezone, environment=args.environment, population=args.population)
                if options.end > datetime.now(timezone.utc):
                    raise ValueError()
            except ValueError:
                print('Invalid report dates, timezone, environment or population (maximum 366 days; no future end).', file=sys.stderr)
                return 2
        else:
            valid_limit(args.limit)
        settings = Settings()
        if args.command == 'backfill' and settings.metrics_database_environment != args.environment:
            print('Backfill requires the configured database environment to match --environment.', file=sys.stderr)
            return 2
        engine = create_engine(settings)
        if args.command == 'report':
            report = MetricReportService(engine, backend_database_environment=settings.metrics_database_environment).build(options)
            def render(stream):
                if args.format == 'csv':
                    write_csv(report, stream)
                else:
                    json.dump(report.to_json(), stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
                    stream.write('\n')
            if args.output:
                with args.output.open('w', encoding='utf-8', newline='') as stream:
                    render(stream)
            else:
                render(sys.stdout)
        elif args.command == 'backfill':
            print(json.dumps(serializable(asdict(backfill_metrics(engine, environment=args.environment, limit=args.limit))), sort_keys=True))
        else:
            print(json.dumps(asdict(cleanup_metrics(engine, now=datetime.now(timezone.utc), dry_run=not args.execute, limit=args.limit)), sort_keys=True))
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except Exception:
        print('Metrics command failed; check configuration, database access, report range and output path.', file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
