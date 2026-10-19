"""Disposable Docker smoke test. No host database or deployment credentials used.

Run from any directory: python3 ops/smoke.py. Requires Docker Compose v2+.
Always removes only its own randomly named project and volumes on exit.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = 'fitcheck-smoke-' + secrets.token_hex(5)
    with tempfile.TemporaryDirectory(prefix='fitcheck-smoke-') as temporary:
        directory = Path(temporary)
        password, token = secrets.token_hex(24), secrets.token_hex(32)
        def write(name, value):
            path = directory / name
            path.write_text(value)
            path.chmod(0o600)
            return str(path)
        common = 'FITCHECK_ENV=production\nFITCHECK_DATABASE_URL=postgresql+psycopg://fitcheck:' + password + '@postgres:5432/fitcheck\n'
        env = dict(os.environ, FITCHECK_POSTGRES_PASSWORD=password,
            FITCHECK_RELEASE=project, FITCHECK_WEBSITE_PORT='0',
            FITCHECK_API_ENV_FILE=write('api.env', common +
                'FITCHECK_HOST=0.0.0.0\nFITCHECK_AUTH_ENABLED=true\nFITCHECK_JOBS_ENABLED=true\nFITCHECK_GUEST_ENABLED=true\n'
                'FITCHECK_AUTH_SECRET=' + secrets.token_hex(32) + '\nFITCHECK_OPS_TOKEN=' + token + '\n'
                'FITCHECK_AUTH_WEB_BASE_URL=https://smoke.example.com\nFITCHECK_ALLOWED_ORIGINS=["https://smoke.example.com"]\n'),
            FITCHECK_WORKER_ENV_FILE=write('worker.env', common + 'OPEN_AI_KEY=smoke-unused-no-provider-calls\n'),
            FITCHECK_WEBSITE_ENV_FILE=write('website.env', 'FITCHECK_BACKEND_URL=http://api:8000\nFITCHECK_WEBSITE_ORIGIN=https://smoke.example.com\n'),
            FITCHECK_OPS_TOKEN_FILE=write('ops_token', token),
            FITCHECK_PG_SERVICE_FILE=write('pg_service.conf',
                ''.join(f'[{name}]\nhost=postgres\nport=5432\nuser=fitcheck\npassword={password}\ndbname=fitcheck\n\n' for name in ('fitcheck','fitcheck_restore'))))
        Path(env['FITCHECK_OPS_TOKEN_FILE']).chmod(0o644)
        # Keep backup scheduling out of a deterministic smoke run.
        override = write('compose.json', json.dumps({'services': {'backup': {
            'entrypoint': ['sleep','infinity'], 'init': True, 'stop_grace_period': '2s'}}}))
        command = ['docker','compose','-p',project,'-f',str(ROOT/'compose.yaml'),
                   '-f',str(ROOT/'compose.prod.yaml'),'-f',override,'--profile','operations']
        def run(*args, input=None, okay=True, timeout=900):
            result = subprocess.run(command + list(args), cwd=ROOT, env=env, input=input,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            if okay and result.returncode:
                # Never echo interpolated config, secret-bearing arguments or DB errors.
                raise RuntimeError('Compose command failed: ' + ' '.join(args[:3]) + '\n' +
                    result.stderr.replace(password,'[redacted]').replace(token,'[redacted]')[-12000:])
            return result
        def sql(value):
            return run('exec','-T','postgres','psql','-U','fitcheck','-d','fitcheck',
                       '-v','ON_ERROR_STOP=1','-At', input=value).stdout.strip()
        try:
            print('Building and starting isolated stack', flush=True)
            run('up','--build','-d','--wait','--wait-timeout','180',timeout=1200)
            run('exec','-T','prometheus','promtool','check','config','/etc/prometheus/prometheus.yml')
            run('exec','-T','prometheus','promtool','check','rules','/etc/prometheus/alerts.yml')
            address = run('port','website','3000').stdout.strip()
            with urllib.request.urlopen('http://' + address + '/',timeout=15) as response:
                assert response.status == 200
            # Read metrics inside the network; the token is supplied over stdin.
            metrics = run('exec','-T','api','/app/.venv/bin/python','-c',
                'import sys,urllib.request; r=urllib.request.Request("http://127.0.0.1:8000/internal/operations/metrics",headers={"Authorization":"Bearer "+sys.stdin.read()}); print(urllib.request.urlopen(r).read().decode())',input=token).stdout
            assert 'fitcheck_database_up 1' in metrics
            run('exec','-T','worker','/app/.venv/bin/python','-c',
                'import urllib.request; assert b"fitcheck_worker_healthy 1" in urllib.request.urlopen("http://127.0.0.1:9109/metrics").read()')
            owner = str(uuid.uuid4())
            sql(f"INSERT INTO owners(id,kind,created_at) VALUES ('{owner}','user',now());")
            before = sql('SELECT count(*) FROM owners;')
            result = run('exec','-T','backup','sh','/ops/backup.sh','backup')
            archive = json.loads(result.stdout)['archive']
            # Verify actual rows inside the restored DB, in addition to schema checks.
            verify = (ROOT/'ops/backup/verify.sql').read_text() + f"\nDO $$ BEGIN IF (SELECT count(*) FROM owners WHERE id='{owner}')<>1 THEN RAISE EXCEPTION 'Restored row missing'; END IF; END $$;\n"
            run('exec','-T','backup','sh','-c','cat > /tmp/verify-smoke.sql', input=verify)
            run('exec','-T','-e','FITCHECK_RESTORE_VERIFY_SQL=/tmp/verify-smoke.sql','backup','sh','/ops/backup.sh','restore-check',archive)
            assert before == sql('SELECT count(*) FROM owners;')
            assert sql("SELECT count(*) FROM pg_database WHERE datname LIKE 'fitcheck_restore_check_%';") == '0'
            # A corrupt archive must fail without advancing the restore marker.
            marker = run('exec','-T','backup','cat','/state/restore.timestamp').stdout
            run('exec','-T','backup','sh','-c','printf broken >> "/backups/$1"','sh',archive)
            failed = run('exec','-T','backup','sh','/ops/backup.sh','restore-check',archive,okay=False)
            assert failed.returncode and 'checksum' in failed.stderr
            assert marker == run('exec','-T','backup','cat','/state/restore.timestamp').stdout
            run('exec','-T','api','/app/.venv/bin/python','-m','fitcheck_backend.operations','cleanup','--dry-run')
            run('restart','worker')
            for attempt in range(30):
                probe = run('exec','-T','worker','/app/.venv/bin/python','-m','fitcheck_backend.worker.health',okay=False)
                if probe.returncode == 0: break
                time.sleep(1)
            else: raise AssertionError('Worker did not recover after restart')
            assert before == sql('SELECT count(*) FROM owners;')
            print('PASS: readiness, website, metrics, rules, backup, restored rows, corruption rejection, cleanup dry-run, worker restart',flush=True)
        finally:
            run('down','--volumes','--remove-orphans','--timeout','5',timeout=90)


if __name__ == '__main__':
    main()
