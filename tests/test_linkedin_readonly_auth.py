"""Synthetic tests for a read-only LinkedIn identity check."""
from scripts.social.channels.linkedin import direct
import pytest


def test_userinfo_matching_person_is_not_publish_authorization():
    assert hasattr(direct, 'interpret_userinfo')
    result = direct.interpret_userinfo(200, {'sub': 'member123'}, expected_author='urn:li:person:member123')
    assert result == {'identity': 'match', 'app_binding_verified': False, 'publish_authorized': False}


@pytest.mark.parametrize(('status', 'body', 'expected'), [
    (200, {'sub': 'other'}, 'mismatch'),
    (200, {'sub': ' '}, 'unknown'),
    (200, {}, 'unknown'),
    (403, {'sub': 'member123'}, 'unknown'),
    (302, {'sub': 'member123'}, 'unknown'),
])
def test_userinfo_unverified_cases(status, body, expected):
    result = direct.interpret_userinfo(status, body, expected_author='urn:li:person:member123')
    assert result == {'identity': expected, 'app_binding_verified': False, 'publish_authorized': False}


def test_organization_cannot_use_person_probe():
    with pytest.raises(ValueError):
        direct.interpret_userinfo(200, {'sub': 'member123'}, expected_author='urn:li:organization:123')


def test_transport_is_read_only_fixed_host_and_does_not_return_profile(monkeypatch):
    from scripts.social.channels.linkedin import readonly_auth

    requests = []

    class Response:
        status = 200

        def read(self, size):
            return b'{"sub":"member123","name":"private"}'

    class Connection:
        def __init__(self, host, timeout):
            requests.append((host, timeout))

        def request(self, method, path, headers):
            requests.append((method, path, headers))

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    result = readonly_auth.check_userinfo('test-token', 'urn:li:person:member123')
    assert result == {'identity': 'match', 'app_binding_verified': False, 'publish_authorized': False}
    assert requests[0] == ('api.linkedin.com', 10)
    assert requests[1][0:2] == ('GET', '/v2/userinfo')
    assert 'private' not in str(result) and 'test-token' not in str(result)


def test_invalid_organization_never_opens_network(monkeypatch):
    from scripts.social.channels.linkedin import readonly_auth
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError):
        readonly_auth.check_userinfo('test-token', 'urn:li:organization:123')


@pytest.mark.parametrize('status', [302, 401, 403, 500])
def test_http_errors_never_follow_redirect_or_read_response(monkeypatch, status):
    from scripts.social.channels.linkedin import readonly_auth

    class Response:
        def read(self, size):
            pytest.fail('must not read non-200 response')

    response = Response()
    response.status = status

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return response

        def close(self):
            pass

    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    assert readonly_auth.check_userinfo('test-token', 'urn:li:person:member123')['identity'] == 'unknown'


@pytest.mark.parametrize('body', [b'{"sub":"member123","sub":"other"}', b'x' * 65537,
                                 b'not-json', b'{"sub":"member123","extra":NaN}'],
                         ids=['duplicate', 'oversize', 'malformed', 'nan'])
def test_untrusted_response_is_unknown(monkeypatch, body):
    from scripts.social.channels.linkedin import readonly_auth

    class Response:
        status = 200

        def read(self, size):
            return body

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    assert readonly_auth.check_userinfo('test-token', 'urn:li:person:member123')['identity'] == 'unknown'


def test_bad_credential_is_rejected_before_network(monkeypatch):
    from scripts.social.channels.linkedin import readonly_auth
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', lambda *a, **kw: pytest.fail('network'))
    with pytest.raises(ValueError, match='invalid credential'):
        readonly_auth.check_userinfo('bad\r\nheader', 'urn:li:person:member123')


def test_transport_error_does_not_expose_credential(monkeypatch):
    from scripts.social.channels.linkedin import readonly_auth
    def fail(*args, **kwargs):
        raise OSError('test-token private message')
    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', fail)
    result = readonly_auth.check_userinfo('test-token', 'urn:li:person:member123')
    assert result == {'identity': 'unknown', 'app_binding_verified': False, 'publish_authorized': False}


def test_close_error_is_sanitized(monkeypatch):
    from scripts.social.channels.linkedin import readonly_auth

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            raise OSError('private failure')

        def close(self):
            raise OSError('private failure')

    monkeypatch.setattr(readonly_auth.http.client, 'HTTPSConnection', Connection)
    result = readonly_auth.check_userinfo('test-token', 'urn:li:person:member123')
    assert result['identity'] == 'unknown'
