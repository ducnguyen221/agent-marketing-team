"""Postiz response translation must never imply publication from scheduling."""

from importlib.util import find_spec

import pytest


def test_scheduled_result_keeps_job_id_separate_from_publication():
    assert find_spec('scripts.lib.postiz_adapter') is not None
    from scripts.lib.postiz_adapter import normalize_fake_response

    result = normalize_fake_response({'state': 'scheduled', 'job_id': 'job-demo'})
    assert result.state == 'scheduled'
    assert result.remote_job_id == 'job-demo'
    assert result.platform_post_id is None
    assert result.platform_url is None


def test_fake_published_result_preserves_both_opaque_identifiers():
    from scripts.lib.postiz_adapter import normalize_fake_response

    result = normalize_fake_response({
        'state': 'published', 'job_id': 'job-123',
        'platform_post_id': '123_456', 'platform_url': 'https://example.invalid/post/1',
    })
    assert result.remote_job_id == 'job-123'
    assert result.platform_post_id == '123_456'
    assert result.platform_url == 'https://example.invalid/post/1'


@pytest.mark.parametrize('raw', [
    {}, {'state': 'scheduled'}, {'state': 'published', 'job_id': 'job'},
    {'state': 'published', 'platform_post_id': 123, 'platform_url': 'https://example.invalid/p'},
    {'state': 'published', 'platform_post_id': 'p', 'platform_url': 'http://example.invalid/p'},
    {'state': 'done', 'job_id': 'j'},
    {'state': ['scheduled'], 'job_id': 'j'},
    {'state': 'published', 'platform_post_id': 'p', 'platform_url': 'https://user:secret@example.invalid/'},
    {'state': 'published', 'platform_post_id': 'p', 'platform_url': 'https://facebook.com/post/1'},
])
def test_uncertain_or_invalid_fake_result_is_never_treated_as_success(raw):
    from scripts.lib.postiz_adapter import normalize_fake_response

    assert normalize_fake_response(raw).state == 'unknown'


def test_synthetic_scheduled_job_can_be_observed_without_creating_another_job():
    from scripts.lib.postiz_adapter import FakePostiz

    fake = FakePostiz()
    submitted = fake.submit('intent-a', scheduled=True)
    assert submitted.state == 'scheduled'
    assert fake.get_delivery(submitted.remote_job_id) == submitted
    assert fake.submission_count == 1
    fake.publish(submitted.remote_job_id, platform_post_id='page_123',
                 platform_url='https://example.invalid/page/123')
    published = fake.get_delivery(submitted.remote_job_id)
    assert published.remote_job_id == submitted.remote_job_id
    assert published.platform_post_id == 'page_123'
    assert fake.submission_count == 1


def test_unknown_synthetic_job_is_not_silently_treated_as_new():
    from scripts.lib.postiz_adapter import FakePostiz

    fake = FakePostiz()
    assert fake.get_delivery('missing').state == 'unknown'
    assert fake.submission_count == 0


def test_malformed_url_is_unknown_without_raising():
    from scripts.lib.postiz_adapter import normalize_fake_response

    result = normalize_fake_response({'state': 'published', 'platform_post_id': 'x',
                                      'platform_url': 'https://[bad'})
    assert result.state == 'unknown'


@pytest.mark.parametrize('status', [400, 429, 500, None])
def test_error_without_proof_of_no_side_effect_is_unknown(status):
    from scripts.lib.postiz_adapter import classify_fake_failure

    assert classify_fake_failure(status).state == 'unknown'


def test_fake_provider_can_mark_definite_rejection_only_with_explicit_evidence():
    from scripts.lib.postiz_adapter import classify_fake_failure

    result = classify_fake_failure(400, definite_no_side_effect=True)
    assert result.state == 'failed'


def test_reconcile_reads_existing_job_without_submitting_a_second_time():
    from scripts.lib.postiz_adapter import FakePostiz, reconcile_fake

    fake = FakePostiz()
    accepted = fake.submit('intent-one', scheduled=True)
    fake.publish(accepted.remote_job_id, platform_post_id='page_77',
                 platform_url='https://example.invalid/page/77')
    candidate = reconcile_fake(fake, accepted.remote_job_id, expected_instance_id=fake.instance_id)
    assert candidate.state == 'published'
    assert candidate.platform_post_id == 'page_77'
    assert fake.submission_count == 1


def test_reconcile_without_known_job_cannot_guess_or_submit():
    from scripts.lib.postiz_adapter import FakePostiz, reconcile_fake

    fake = FakePostiz()
    assert reconcile_fake(fake, None, expected_instance_id=fake.instance_id).state == 'unknown'
    assert fake.submission_count == 0


def test_reconcile_refuses_non_fake_provider():
    from scripts.lib.postiz_adapter import reconcile_fake

    with pytest.raises(TypeError):
        reconcile_fake(object(), 'job', expected_instance_id='fake')


def test_cancelled_fake_job_cannot_later_be_published():
    from scripts.lib.postiz_adapter import FakePostiz

    fake = FakePostiz()
    job = fake.submit('intent-cancel', scheduled=True)
    assert fake.cancel(job.remote_job_id).state == 'cancelled'
    with pytest.raises(ValueError):
        fake.publish(job.remote_job_id, platform_post_id='page_9',
                     platform_url='https://example.invalid/page/9')
    assert fake.get_delivery(job.remote_job_id).state == 'cancelled'


def test_cancellation_of_unknown_fake_job_does_not_create_a_job():
    from scripts.lib.postiz_adapter import FakePostiz

    fake = FakePostiz()
    assert fake.cancel('missing').state == 'unknown'
    assert fake.submission_count == 0


def test_reconciliation_rejects_same_job_id_from_different_fake_instance():
    from scripts.lib.postiz_adapter import FakePostiz, reconcile_fake

    first, second = FakePostiz(), FakePostiz()
    original = first.submit('intent-one', scheduled=True)
    collision = second.submit('unrelated', scheduled=True)
    assert original.remote_job_id == collision.remote_job_id
    assert first.instance_id != second.instance_id
    assert reconcile_fake(second, original.remote_job_id,
                          expected_instance_id=first.instance_id).state == 'unknown'


def test_reconcile_supports_both_module_names_without_accepting_subclasses():
    from postiz_adapter import FakePostiz as TopFake, reconcile_fake as top_reconcile
    from scripts.lib.postiz_adapter import FakePostiz as PackageFake, reconcile_fake as package_reconcile
    top, package = TopFake(), PackageFake()
    top_job = top.submit('intent-top', scheduled=True)
    package_job = package.submit('intent-package', scheduled=True)
    assert top_reconcile(package, package_job.remote_job_id,
                         expected_instance_id=package.instance_id).state == 'scheduled'
    assert package_reconcile(top, top_job.remote_job_id,
                             expected_instance_id=top.instance_id).state == 'scheduled'
    class NetworkLike(PackageFake):
        def get_delivery(self, *args):
            raise AssertionError('subclass must not be called')
    with pytest.raises(TypeError):
        top_reconcile(NetworkLike(), package_job.remote_job_id, expected_instance_id=package.instance_id)


def test_fresh_package_import_does_not_need_pythonpath():
    """Fresh interpreter must load the package without pytest sys.path changes."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    program = ('from scripts.lib.postiz_adapter import FakePostiz, reconcile_fake; '
               'f=FakePostiz(); job=f.submit("fixture", scheduled=True); '
               'assert reconcile_fake(f, job.remote_job_id, expected_instance_id=f.instance_id).state == "scheduled"')
    result = subprocess.run([sys.executable, '-c', program], cwd=root, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_fresh_top_level_adapter_import_still_works_without_pythonpath():
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    program = ('import sys; sys.path.insert(0, "scripts/lib"); '
               'from postiz_adapter import FakePostiz; '
               'assert FakePostiz().submission_count == 0')
    result = subprocess.run([sys.executable, '-c', program], cwd=root, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('overrides', [
    {'published_at': 'not-rfc3339'}, {'published_at': '2026-11-18T03:00:00'},
    {'published_at': '2026-99-18T03:00:00Z'}, {'comment_id': ''},
    {'comment_id': 'comment\nnext'}, {'comment_id': 3},
])
def test_invalid_publication_metadata_never_produces_published_fixture(overrides):
    from postiz_adapter import normalize_fake_response
    raw={'state':'published','job_id':'job', 'platform_post_id':'page_91',
         'platform_url':'https://example.invalid/page/91', **overrides}
    assert normalize_fake_response(raw).state == 'unknown'
