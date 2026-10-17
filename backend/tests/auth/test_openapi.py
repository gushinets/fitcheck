import json
import subprocess
import sys
from pathlib import Path
from openapi_spec_validator import validate
from fitcheck_backend.api.app import create_app
from fitcheck_backend.config import Settings
from fitcheck_backend.contracts.openapi import export_openapi


def test_export_preserves_live_auth_and_planned_roadmap_without_config(tmp_path,monkeypatch):
    app=create_app(Settings())
    live=app.openapi()
    doc=export_openapi(app)
    validate(live);validate(doc)
    for path,methods in live['paths'].items():
        for method,operation in methods.items():
            if path.startswith('/v1/'):
                assert '422' not in operation['responses']
                assert doc['paths'][path][method]['x-fitcheck-implementation']=='implemented'
                assert doc['paths'][path][method]['x-fitcheck-owner-task'] in {'ANY-645', 'ANY-646', 'ANY-647', 'ANY-649', 'ANY-650', 'ANY-651'}
                assert doc['paths'][path][method]['responses']==operation['responses']
    assert doc['paths']['/v1/profile']['get']['x-fitcheck-implementation']=='implemented'
    assert doc['components']['schemas']['RegistrationCredentials']['properties']['password']['minLength']==15
    assert doc['components']['schemas']['LoginCredentials']['properties']['password']['minLength']==1
    output=tmp_path/'schema.json'
    monkeypatch.setenv('FITCHECK_AUTH_ENABLED','true')
    monkeypatch.setenv('FITCHECK_AUTH_SECRET','invalid-private-secret')
    monkeypatch.setenv('FITCHECK_SMTP_HOST','missing-settings')
    script=Path(__file__).parents[2]/'scripts/export_openapi.py'
    result=subprocess.run([sys.executable,str(script),'--output',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert json.loads(output.read_text())==doc
