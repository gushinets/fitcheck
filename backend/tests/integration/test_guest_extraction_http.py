import pytest
from test_guest_sessions_http import profile_http,guest
from test_profile_http import WEB

pytestmark=pytest.mark.integration
TEXT='React frontend developer needed.\nBuild a responsive dashboard using TypeScript and React. Budget $500. Remote work, clear requirements and existing Figma designs.'


def test_guest_extraction_requires_csrf_and_consumes_quota(profile_http):
    a,c,r,_,_=profile_http;value,token=guest(c)
    body={'type':'text','text':TEXT}
    assert c.post('/v1/extractions?mode=guest',json=body,headers={'Origin':WEB}).status_code==403
    headers={'Origin':WEB,'X-CSRF-Token':value['csrfToken']}
    for _ in range(10):
        result=c.post('/v1/extractions?mode=guest',json=body,headers=headers)
        assert result.status_code==200,result.text
    quota=c.get('/v1/quota?mode=guest')
    assert quota.status_code==200,quota.text
    assert quota.json()['operations']['extraction']==dict(limit=10,remaining=0,reserved=0,consumed=10)
    assert quota.json()['remaining']==1 and quota.json()['registrationRequired'] is False
    denied=c.post('/v1/extractions?mode=guest',json=body,headers=headers)
    assert denied.status_code==429


def test_extraction_error_returns_product_slot(profile_http):
    _,c,_,_,_=profile_http;value,_=guest(c)
    bad=c.post('/v1/extractions?mode=guest',json={'type':'text','text':'too short'},headers={'Origin':WEB,'X-CSRF-Token':value['csrfToken']})
    assert bad.status_code==400
    q=c.get('/v1/quota?mode=guest').json()['operations']['extraction']
    assert q==dict(limit=10,remaining=10,reserved=0,consumed=0)
