import io
from fitcheck_backend.metrics.__main__ import main


def test_invalid_options_are_safe_and_do_not_open_database(capsys):
    assert main(['report','--start','bad','--end','bad','--environment','test','--population','visitor'])==2
    assert 'Traceback' not in capsys.readouterr().err


def test_cleanup_defaults_to_dry_run(monkeypatch,capsys):
    import fitcheck_backend.metrics.__main__ as cli
    from fitcheck_backend.metrics.retention import MaintenanceResult
    calls=[]
    class Engine:
        def dispose(self): pass
    monkeypatch.setattr(cli,'create_engine',lambda settings:Engine())
    monkeypatch.setattr(cli,'cleanup_metrics',lambda engine,**kw:calls.append(kw) or MaintenanceResult())
    assert main(['cleanup'])==0
    assert calls[-1]['dry_run'] is True
    assert main(['cleanup','--execute'])==0
    assert calls[-1]['dry_run'] is False


def test_database_scope_is_independent_and_cli_forwards_only_database_scope(monkeypatch,capsys):
    import fitcheck_backend.metrics.__main__ as cli
    from fitcheck_backend.config import Settings
    from fitcheck_backend.metrics.report_types import MetricReport
    settings=Settings(metrics_environment='test',metrics_database_environment='development')
    assert settings.metrics_environment != settings.metrics_database_environment
    assert Settings(metrics_environment='test').metrics_database_environment is None
    calls=[]
    class Engine:
        def dispose(self): pass
    class Service:
        def __init__(self,engine,**kwargs): calls.append(kwargs)
        def build(self,options): return MetricReport(options=options,rows=[])
    monkeypatch.setattr(cli,'Settings',lambda:settings)
    monkeypatch.setattr(cli,'create_engine',lambda settings:Engine())
    monkeypatch.setattr(cli,'MetricReportService',Service)
    assert main(['report','--start','2026-01-01T00:00:00Z','--end','2026-01-02T00:00:00Z','--environment','test','--population','all'])==0
    assert calls==[{'backend_database_environment':'development'}]
    assert main(['backfill','--environment','test'])==2
