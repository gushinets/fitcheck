from pathlib import Path

from dotenv import dotenv_values

from fitcheck_backend.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_production_roles_enable_analytics_and_agreed_daily_policy(monkeypatch):
    for role in ('api', 'worker'):
        with monkeypatch.context() as environment:
            for key, value in dotenv_values(ROOT / 'ops' / 'env' / f'{role}.env.example').items():
                environment.setenv(key, value)
            settings = Settings(_env_file=None, auth_secret='ab' * 32)
        assert settings.env == 'production'
        assert settings.metrics_enabled
        assert settings.metrics_environment == settings.metrics_database_environment == 'production'
        assert settings.guest_demo_limit == 1
        assert settings.account_analysis_daily_limit is None
        assert settings.budget_account_daily_usd is None
        assert settings.budget_deployment_daily_usd is None
        assert settings.account_max_active_jobs == 2


def test_production_website_matches_api_analytics_configuration():
    api = dotenv_values(ROOT / 'ops/env/api.env.example')
    website = dotenv_values(ROOT / 'ops/env/website.env.example')
    origin = 'https://fitcheck.dokploy.gcexp.ru'
    assert api['FITCHECK_AUTH_WEB_BASE_URL'] == website['FITCHECK_WEBSITE_ORIGIN'] == origin
    assert website['ALLOWED_ORIGINS'] == origin
    assert website['METRICS_ENVIRONMENT'] == 'production'
    assert website['METRICS_BACKEND_URL'] == 'https://fitcheck-api.dokploy.gcexp.ru'
    assert website['METRICS_BRIDGE_KEY'] == api['FITCHECK_METRICS_INGEST_KEY']
    assert website['METRICS_COOKIE_SECRET'] != website['METRICS_BRIDGE_KEY']
    assert website['METRICS_ALLOW_LOCAL_HTTP'] == 'false'
