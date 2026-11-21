"""LinkedIn native request previews and response interpretation, no network."""
import importlib
import sys

import pytest


def direct(monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setitem(sys.modules, 'scripts.lib.postiz_payload', None)
    try:
        return importlib.import_module('scripts.social.channels.linkedin.direct')
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith('scripts.social.channels'):
            pytest.fail('LinkedIn direct request builder not implemented')
        raise


@pytest.mark.parametrize(('media_kind', 'media_urn'), [
    (None, None), ('image', 'urn:li:image:fixture-image'), ('video', 'urn:li:video:fixture-video'),
])
def test_native_text_image_video_preview_does_not_depend_on_postiz(monkeypatch, media_kind, media_urn):
    result = direct(monkeypatch).preview_post(
        author='urn:li:organization:12345', text='Xin chào', api_version='202611',
        media_kind=media_kind, media_urn=media_urn)
    assert result['preview_only'] is True
    assert result['request']['path'] == '/rest/posts'
    assert result['request']['body']['author'] == 'urn:li:organization:12345'
    assert result['request']['body']['commentary'] == 'Xin chào'
    assert 'integration' not in str(result['request']['body'])
    if media_kind:
        assert result['request']['body']['content']['media']['id'] == media_urn
    else:
        assert 'content' not in result['request']['body']
    assert 'not_authorized' in result['warnings']


def test_plaintext_escapes_linkedin_little_reserved_characters():
    result = direct().preview_post(author='urn:li:person:fixture-member', text='Hello @Joe #topic [x] *bold*',
                                   api_version='202611')
    assert result['request']['body']['commentary'] == r'Hello \@Joe \#topic \[x\] \*bold\*'
    assert 'mentions_and_hashtags_as_plaintext' in result['warnings']


@pytest.mark.parametrize(('author', 'kind', 'urn'), [
    ('urn:li:share:123', None, None), ('urn:li:organization:12345', 'image', 'urn:li:video:fixture-video'),
    ('urn:li:organization:12345', 'video', 'urn:li:image:fixture-image'),
    ('urn:li:organization:12345', None, 'urn:li:image:fixture-image'),
    ('urn:li:organization:12345', 'image', None),
])
def test_reject_mismatched_author_or_media(author, kind, urn):
    with pytest.raises(ValueError):
        direct().preview_post(author=author, text='Text', api_version='202611', media_kind=kind, media_urn=urn)


@pytest.mark.parametrize('text', ['', '   ', '{{pending}}', 'bad\x00text', 'bad\ud800text'])
def test_reject_empty_placeholder_and_invalid_text(text):
    with pytest.raises(ValueError):
        direct().preview_post(author='urn:li:person:fixture-member', text=text, api_version='202611')


@pytest.mark.parametrize('headers', [[], [('x-restli-id', 'bad')],
    [('x-restli-id', 'urn:li:share:123'), ('X-RestLi-Id', 'urn:li:share:456')]])
def test_create_without_unique_valid_receipt_stays_unknown(headers):
    assert direct().interpret_create(201, headers)['state'] == 'unknown'


def test_valid_create_receipt_is_accepted_without_claiming_readback():
    result = direct().interpret_create(201, [('X-RestLi-Id', 'urn:li:share:123')])
    assert result == {'state': 'accepted', 'post_urn': 'urn:li:share:123', 'readback': 'unverified'}


@pytest.mark.parametrize('status', [None, 200, 202, 400, 401, 403, 429, 500])
def test_non_201_create_result_remains_unknown(status):
    assert direct().interpret_create(status, [('x-restli-id', 'urn:li:share:123')])['state'] == 'unknown'


def test_linkedin_native_preview_uses_matching_synthetic_marketing_anchor(monkeypatch):
    result = direct(monkeypatch).preview_marketing_anchor(
        source='# Fixture\n\n## post:linkedin_post\nBài LinkedIn giả\n\n## post:facebook_post\nBài Facebook\n',
        anchor='post:linkedin_post', author='urn:li:person:fixture-member', api_version='202611')
    assert result['request']['body']['commentary'].strip() == 'Bài LinkedIn giả'
    assert result['source_anchor'] == 'post:linkedin_post'


@pytest.mark.parametrize('source', [
    '## post:linkedin_post\nText\n### image_prompt\nInternal\n',
    '## post:linkedin_post\nText <!-- internal -->\n',
    '## post:linkedin_post\n> Internal instructions\nText\n',
])
def test_native_anchor_rejects_ambiguous_instructions(source):
    with pytest.raises(ValueError):
        direct().preview_marketing_anchor(source=source, anchor='post:linkedin_post',
                                          author='urn:li:person:fixture-member', api_version='202611')


def test_windows_linebreaks_and_emoji_joiner_are_preserved():
    result = direct().preview_post(author='urn:li:person:fixture-member', text='Dòng 1\r\n👩\u200d💻',
                                   api_version='202611')
    assert result['request']['body']['commentary'] == 'Dòng 1\n👩\u200d💻'


def test_api_version_requires_ascii_digits():
    with pytest.raises(ValueError):
        direct().preview_post(author='urn:li:person:fixture-member', text='Text', api_version='２０２６１１')


def test_all_little_reserved_characters_are_escaped():
    text = r'\|{}@[]()<>#*_~'
    result = direct().preview_post(author='urn:li:person:fixture-member', text=text, api_version='202611')
    assert result['request']['body']['commentary'] == ''.join('\\' + char for char in text)


def test_invisible_only_content_is_rejected():
    with pytest.raises(ValueError):
        direct().preview_post(author='urn:li:person:fixture-member', text='\u200d \u200d', api_version='202611')


def test_markdown_reference_definition_never_enters_native_commentary():
    source = '## post:linkedin_post\nPublic text\n\n[draft-note]: https://fixture.invalid/internal\n'
    with pytest.raises(ValueError):
        direct().preview_marketing_anchor(source=source, anchor='post:linkedin_post',
                                          author='urn:li:person:fixture-member', api_version='202611')


def test_linkedin_readback_matches_native_id_author_and_public_visibility():
    receipt = {'state': 'accepted', 'post_urn': 'urn:li:share:123', 'readback': 'unverified'}
    body = {'id': 'urn:li:share:123', 'author': 'urn:li:person:fixture-member',
            'lifecycleState': 'PUBLISHED', 'visibility': 'PUBLIC'}
    observed = direct().observe_post(receipt, 200, body, expected_author='urn:li:person:fixture-member')
    assert observed['readback'] == 'provider_reports_published'
    assert observed['previously_reported_published'] is True
    assert receipt['readback'] == 'unverified'


@pytest.mark.parametrize(('status', 'body'), [
    (403, {}), (200, {'id': 'urn:li:share:999', 'author': 'urn:li:person:fixture-member',
                      'lifecycleState': 'PUBLISHED', 'visibility': 'PUBLIC'}),
    (200, {'id': 'urn:li:share:123', 'author': 'urn:li:person:other',
           'lifecycleState': 'PUBLISHED', 'visibility': 'PUBLIC'}),
    (200, {'id': 'urn:li:share:123', 'author': 'urn:li:person:fixture-member',
           'lifecycleState': 'PUBLISH_REQUESTED', 'visibility': 'PUBLIC'}),
])
def test_failed_or_mismatched_readback_does_not_erase_receipt(status, body):
    receipt = {'state': 'accepted', 'post_urn': 'urn:li:share:123', 'readback': 'unverified'}
    observed = direct().observe_post(receipt, status, body, expected_author='urn:li:person:fixture-member')
    assert observed == {**receipt, 'previously_reported_published': False}


def test_repeated_readbacks_keep_history_but_do_not_claim_403_is_public():
    receipt = {'state': 'accepted', 'post_urn': 'urn:li:share:123', 'readback': 'unverified'}
    body = {'id': 'urn:li:share:123', 'author': 'urn:li:person:fixture-member',
            'lifecycleState': 'PUBLISHED', 'visibility': 'PUBLIC'}
    first = direct().observe_post(receipt, 200, body, expected_author='urn:li:person:fixture-member')
    second = direct().observe_post(first, 200, body, expected_author='urn:li:person:fixture-member')
    assert second == first
    third = direct().observe_post(second, 403, {}, expected_author='urn:li:person:fixture-member')
    assert third['state'] == 'accepted'
    assert third['post_urn'] == 'urn:li:share:123'
    assert third['readback'] == 'unverified'
    assert third['previously_reported_published'] is True
