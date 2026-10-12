import pytest
from pydantic import ValidationError
from fitcheck_backend.config import Settings


def test_settings_hide_secrets():
    secret = 'ab' * 32
    s = Settings(auth_enabled=True, auth_secret=secret, database_url='postgresql://user:dbsecret@localhost/fitcheck', auth_web_base_url='https://fitcheck.example', smtp_host='smtp.example', smtp_port=465, smtp_username='sender', smtp_password='mailsecret', smtp_from='sender@example.com', smtp_security='smtps')
    assert secret not in repr(s) and 'dbsecret' not in repr(s) and 'mailsecret' not in repr(s)
    assert not Settings().auth_enabled
    with pytest.raises(ValidationError) as exc:
        Settings(auth_enabled=True, auth_secret='sensitive-invalid')
    assert 'sensitive-invalid' not in str(exc.value)


@pytest.mark.parametrize('values', [
    {'smtp_host': 'smtp.example'}, {'smtp_security': 'plaintext'},
    {'env': 'production', 'auth_web_base_url': 'http://example.com'},
    {'trusted_proxy_ips': ['*']}, {'auth_extension_redirect_uris': ['https://*.chromiumapp.org/callback']},
    {'auth_extension_redirect_uris': ['https://abc.chromiumapp.org/callback?next=evil']},
    {'smtp_from': 'sender@example.com\r\nBcc: x@example.com'},
])
def test_unsafe_configuration_rejected(values):
    with pytest.raises(ValidationError):
        Settings(**values)
