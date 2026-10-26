import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import SecretStr
from fitcheck_backend.metrics.identity_proof import verify_visitor_proof

NOW = datetime(2026,10,23,tzinfo=UTC)
MS = int(NOW.timestamp()*1000)
SETTINGS = SimpleNamespace(metrics_configured=True,metrics_environment='test',metrics_ingest_key=SecretStr('bridge-secret'))
PATH = '/v1/auth/register'


def proof(**changes):
    data=dict(v=1,environment='test',visitorId=str(uuid4()),cookieIssuedAt=MS-1000,
              issuedAt=MS,expiresAt=MS+120000,requestId=str(uuid4()),method='POST',path=PATH)
    data.update(changes)
    encoded=base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode().rstrip('=')
    mac=hmac.new(b'bridge-secret',('fitcheck:metrics:identity:v1:'+encoded).encode(),hashlib.sha256).digest()
    return encoded+'.'+base64.urlsafe_b64encode(mac).decode().rstrip('='),data


def test_valid_context_and_purpose_binding():
    token,data=proof()
    context=verify_visitor_proof(token,SETTINGS,method='POST',path=PATH,now=NOW)
    assert str(context.visitor_id)==data['visitorId'] and context.received_at==NOW
    assert verify_visitor_proof(token,SETTINGS,method='GET',path=PATH,now=NOW) is None
    assert verify_visitor_proof(token,SETTINGS,method='POST',path='/v1/auth/login',now=NOW) is None


@pytest.mark.parametrize('changes',[{'environment':'production'},{'issuedAt':MS+1},{'expiresAt':MS},
    {'expiresAt':MS+120001},{'cookieIssuedAt':MS+1},{'cookieIssuedAt':MS-180*86400000},
    {'visitorId':str(uuid4())+'x'},{'visitorId':'00000000-0000-0000-0000-000000000000'},
    {'accountId':str(uuid4())},{'v':True}])
def test_invalid_context_is_unknown(changes):
    token,_=proof(**changes)
    assert verify_visitor_proof(token,SETTINGS,method='POST',path=PATH,now=NOW) is None


def test_bad_signature_and_bounded_input():
    token,_=proof()
    for value in [None,'',token+'x',token.replace('.', '.x',1),'x'*2049]:
        assert verify_visitor_proof(value,SETTINGS,method='POST',path=PATH,now=NOW) is None
