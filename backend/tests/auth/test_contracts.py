import pytest
from pydantic import ValidationError
from fitcheck_backend.contracts.resources import RegistrationCredentials, LoginCredentials, PasswordConfirmation, PasswordResetConfirm, normalize_email


def test_password_policy_preserves_unicode_and_whitespace():
    for n in [15, 128]:
        value = ' ' + 'я' * (n - 2) + ' '
        assert RegistrationCredentials(email=' A@Example.com ', password=value).password == value
        assert PasswordResetConfirm(token='abc', password=value).password == value
    for n in [14, 129]:
        with pytest.raises(ValidationError):
            RegistrationCredentials(email='a@example.com', password='x' * n)
    assert LoginCredentials(email='a@example.com', password=' x ').password == ' x '
    assert PasswordConfirmation(password='x').password == 'x'
    assert RegistrationCredentials(email=' A@Example.com ', password='x' * 15).email == 'a@example.com'


@pytest.mark.parametrize('value', ['bad', 'a@', '@example.com', 'a\nb@example.com', 'a@example.com\r\nBcc: evil@example.com'])
def test_invalid_email(value):
    with pytest.raises(ValueError):
        normalize_email(value)


def test_password_schema_is_write_only():
    assert RegistrationCredentials.model_json_schema()['properties']['password']['writeOnly']
    with pytest.raises(ValidationError):
        LoginCredentials(email='a@example.com', password='x', ownerId='forged')


def test_extension_opaque_state_is_echoed_exactly():
    from fitcheck_backend.contracts.resources import ExtensionAuthorize, ExtensionCode
    value = ' state with whitespace '
    request = ExtensionAuthorize(redirectUri='https://'+'a'*32+'.chromiumapp.org/callback',
        codeChallenge='a'*43,codeChallengeMethod='S256',state=value)
    assert request.state == value
    assert ExtensionCode(code='a'*43,state=value,expiresIn=120).model_dump()['state'] == value
