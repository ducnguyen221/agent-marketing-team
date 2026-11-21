"""Opt-in delivery projection must not complete a partially delivered campaign."""
import json
import sys
from pathlib import Path

import pytest
from test_register_publish import post  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
import register_publish as RP  # noqa: E402
import md_io  # noqa: E402


def test_unverified_projection_does_not_change_campaign_or_published_state(post):
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Đồng ý bài thử", "fb", "", "") == 0
    with pytest.raises(ValueError, match="ledger"):
        RP.cmd_set(post, "fb", "https://facebook.com/1_2", "1_2", "2_3", "", False,
                   projection_complete=False)
    row = md_io.read_table(md_io.read_fm(post.parent / "campaign.md")[1], "CONTENT")[1][0]
    assert not row.get("facebook")
    assert row["status"] == "in_production"
    assert not row["published"]
    data = json.loads((post / "publish.json").read_text(encoding="utf-8"))
    assert next(p for p in data["posts"] if p["channel"] == "facebook")["publish"]["status"] == "not_published"
    assert not data.get("published_at")


def test_completion_cannot_be_asserted_by_opt_in_caller_without_proof(post):
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Đồng ý bài thử", "fb", "", "") == 0
    with pytest.raises(ValueError, match="ledger proof"):
        RP.cmd_set(post, "fb", "https://facebook.com/1_2", "1_2", "2_3", "", False,
                   projection_complete=True)
    data = json.loads((post / "publish.json").read_text(encoding="utf-8"))
    assert next(p for p in data["posts"] if p["channel"] == "facebook")["publish"]["status"] == "not_published"


def test_partial_projection_rejects_unverified_result(post):
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Đồng ý bài thử", "fb", "", "") == 0
    with pytest.raises(ValueError, match="verify"):
        RP.cmd_set(post, "fb", "https://facebook.com/1_2", "1_2", "2_3", "", True,
                   projection_complete=False)
    data = json.loads((post / "publish.json").read_text(encoding="utf-8"))
    assert next(p for p in data["posts"] if p["channel"] == "facebook")["publish"]["status"] == "not_published"




def _fixture_projection_ledger(occurrence="initial", state="published", ledger_cls=None):
    """Synthetic memory only; no station or human approval is established."""
    from delivery_ledger import DeliveryLedger
    ledger = (ledger_cls or DeliveryLedger).synthetic_memory()
    key = {"station_id": "station", "channel_id": "channel", "campaign_id": "campaign",
           "content_id": "content", "post_id": "post-yt", "platform": "youtube",
           "account_id": "account", "occurrence_key": occurrence}
    payload = {**key, "text": "demo", "artifacts": []}
    def proof(scope):
        return {"gate": scope["gate"], "scope": scope, "by": "fixture",
                "quote": "fixture approval", "source_digest": "a" * 64}
    scopes = []
    for gate in ("g1", "g2"):
        scope = {k: key[k] for k in ("station_id", "channel_id", "campaign_id", "content_id", "post_id")}
        scope["post_id"] = "*" if gate == "g1" else key["post_id"]
        scope["gate"] = gate
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=proof)
        scopes.append((scope, 1))
    intent = ledger.prepare_fixture(key, payload, "channel/campaign/content", "postiz", 1, scopes=scopes)
    attempt = ledger.claim(intent, 1, verifier=proof)
    if state == "published":
        ledger.resolve(intent, attempt, state, remote_job_id="job", platform_post_id="vid",
                       platform_url="https://example.invalid/video/vid", evidence_kind="provider_confirmed",
                       published_at="2026-11-16T12:00:00Z")
    else:
        ledger.resolve(intent, attempt, state, remote_job_id="job")
    doc = {"post_id": "content", "campaign_id": "campaign", "channel_id": "channel",
           "posts": [{"post_id": "post-yt", "channel": "youtube", "post_format": "youtube_video",
                      "publish": {"status": "not_published", "plan": ""}}]}
    return ledger, intent, doc


def test_fixture_projection_uses_ledger_receipt_without_mutating_source():
    ledger, intent, doc = _fixture_projection_ledger()
    try:
        assert hasattr(RP, "project_delivery_fixture"), "fixture projection not implemented"
        projected = RP.project_delivery_fixture(ledger, intent, doc)
        assert projected["posts"][0]["publish"]["platform_id"] == "vid"
        assert projected["posts"][0]["publish"]["link"] == "https://example.invalid/video/vid"
        assert doc["posts"][0]["publish"]["status"] == "not_published"
        assert not projected.get("published_at")  # target success is not campaign completion
    finally:
        ledger.close()


@pytest.mark.parametrize("occurrence,state", [("repost-1", "published"), ("initial", "scheduled")])
def test_fixture_projection_rejects_repost_and_unpublished(occurrence, state):
    ledger, intent, doc = _fixture_projection_ledger(occurrence, state)
    try:
        with pytest.raises(ValueError):
            RP.project_delivery_fixture(ledger, intent, doc)
    finally:
        ledger.close()


def test_fixture_projection_rejects_mismatched_source():
    ledger, intent, doc = _fixture_projection_ledger()
    try:
        doc["campaign_id"] = "another-campaign"
        with pytest.raises(ValueError):
            RP.project_delivery_fixture(ledger, intent, doc)
    finally:
        ledger.close()


def test_fixture_projection_does_not_overwrite_existing_primary():
    ledger, intent, doc = _fixture_projection_ledger()
    try:
        doc["posts"][0]["publish"] = {"status": "published", "link": "https://example.invalid/existing",
                                      "platform_id": "old", "plan": ""}
        with pytest.raises(ValueError):
            RP.project_delivery_fixture(ledger, intent, doc)
        assert doc["posts"][0]["publish"]["platform_id"] == "old"
    finally:
        ledger.close()


def test_fixture_projection_rejects_disk_ledger_without_opening_files(tmp_path):
    class UntrustedLedger:
        _memory_uri = None
    with pytest.raises(ValueError):
        RP.project_delivery_fixture(UntrustedLedger(), "intent", {})
    assert list(tmp_path.iterdir()) == []


def test_fixture_projection_rejects_conflicting_existing_published_time():
    ledger, intent, doc = _fixture_projection_ledger()
    try:
        doc["posts"][0]["publish"] = {"status": "published", "link": "https://example.invalid/video/vid",
                                      "platform_id": "vid", "at": "2025-01-01T00:00:00Z"}
        with pytest.raises(ValueError):
            RP.project_delivery_fixture(ledger, intent, doc)
    finally:
        ledger.close()


def test_fixture_projection_accepts_package_imported_ledger():
    from scripts.lib.delivery_ledger import DeliveryLedger as PackageLedger
    ledger, intent, doc = _fixture_projection_ledger(ledger_cls=PackageLedger)
    try:
        assert RP.project_delivery_fixture(ledger, intent, doc)["posts"][0]["publish"]["platform_id"] == "vid"
    finally:
        ledger.close()


def test_fixture_projection_rejects_ledger_subclass():
    from delivery_ledger import DeliveryLedger
    class ForgedLedger(DeliveryLedger):
        pass
    ledger, intent, doc = _fixture_projection_ledger(ledger_cls=ForgedLedger)
    try:
        with pytest.raises(ValueError, match="synthetic memory ledger"):
            RP.project_delivery_fixture(ledger, intent, doc)
    finally:
        ledger.close()


def _batch_projection_fixture(states=("published", "scheduled")):
    from delivery_ledger import DeliveryLedger
    ledger = DeliveryLedger.synthetic_memory()
    targets = [{"post_id": "post-yt", "platform": "youtube", "account_id": "video"},
               {"post_id": "post-fb", "platform": "facebook", "account_id": "page"}]
    intents = []
    for target, state in zip(targets, states):
        key = {"station_id": "station", "channel_id": "channel", "campaign_id": "campaign",
               "content_id": "content", **target, "occurrence_key": "initial"}
        payload = {**key, "text": "demo", "artifacts": [], "required_targets": targets}
        def proof(scope):
            return {"gate": scope["gate"], "scope": scope, "by": "fixture", "quote": "test",
                    "source_digest": "a" * 64}
        scopes = []
        for gate in ("g1", "g2"):
            scope = {k: key[k] for k in ("station_id", "channel_id", "campaign_id", "content_id", "post_id")}
            scope["post_id"] = "*" if gate == "g1" else key["post_id"]
            scope["gate"] = gate
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=proof)
            scopes.append((scope, 1))
        intent = ledger.prepare_fixture(key, payload, "channel/campaign/content", "postiz", 1, scopes=scopes)
        attempt = ledger.claim(intent, 1, verifier=proof)
        if state == "published":
            ledger.resolve(intent, attempt, state, platform_post_id=f"platform-{target['platform']}",
                           platform_url=f"https://example.invalid/{target['platform']}",
                           comment_id="comment-1" if target["platform"] == "facebook" else None,
                           evidence_kind="provider_confirmed", published_at="2026-11-16T12:00:00Z")
        else:
            ledger.resolve(intent, attempt, state, remote_job_id=f"job-{target['platform']}",
                           provider_instance_id="fixture-provider", integration_id="fixture-integration")
        intents.append(intent)
    doc = {"post_id": "content", "campaign_id": "campaign", "channel_id": "channel",
           "posts": [{"post_id": "post-yt", "channel": "youtube", "post_format": "youtube_video",
                      "publish": {"status": "not_published", "plan": ""}},
                     {"post_id": "post-fb", "channel": "facebook", "post_format": "facebook_post",
                      "publish": {"status": "not_published", "plan": ""}}]}
    return ledger, intents, doc


def test_fixture_batch_projects_published_target_without_completing_scheduled_target():
    ledger, intents, doc = _batch_projection_fixture()
    try:
        assert hasattr(RP, "project_delivery_batch_fixture"), "fixture batch projection missing"
        result = RP.project_delivery_batch_fixture(ledger, intents, doc)
        assert result["complete"] is False
        assert result["document"]["posts"][0]["publish"]["status"] == "published"
        assert result["document"]["posts"][1]["publish"]["status"] == "not_published"
        assert not result["document"].get("published_at")
        assert doc["posts"][0]["publish"]["status"] == "not_published"
    finally:
        ledger.close()


def test_fixture_batch_completion_requires_all_targets_and_real_publication_times():
    ledger, intents, doc = _batch_projection_fixture(("published", "published"))
    try:
        result = RP.project_delivery_batch_fixture(ledger, intents, doc)
        assert result["complete"] is True
        assert result["completed_at"] == "2026-11-16T12:00:00Z"
        assert all(item["publish"]["status"] == "published" for item in result["document"]["posts"])
        assert not result["document"].get("published_at")  # campaign writer remains closed
    finally:
        ledger.close()


def test_fixture_batch_missing_target_or_unknown_never_completes():
    ledger, intents, doc = _batch_projection_fixture(("published", "unknown"))
    try:
        assert RP.project_delivery_batch_fixture(ledger, intents, doc)["complete"] is False
        result = RP.project_delivery_batch_fixture(ledger, intents[:1], doc)
        assert result["complete"] is False
        assert result["pending_targets"] == [{"post_id": "post-fb", "platform": "facebook", "account_id": "page"}]
    finally:
        ledger.close()


def test_fixture_batch_rejects_duplicate_input_without_mutating_document():
    ledger, intents, doc = _batch_projection_fixture()
    try:
        with pytest.raises(ValueError):
            RP.project_delivery_batch_fixture(ledger, [intents[0], intents[0]], doc)
        assert doc["posts"][0]["publish"]["status"] == "not_published"
    finally:
        ledger.close()


def test_fixture_projection_rejects_snapshot_tampered_without_digest_change():
    ledger, intent, doc = _fixture_projection_ledger()
    try:
        with ledger._connect() as connection:
            snapshot = json.loads(connection.execute("SELECT snapshot_json FROM fixture_snapshots WHERE intent_id=?", (intent,)).fetchone()[0])
            snapshot["text"] = "altered without approval"
            connection.execute("UPDATE fixture_snapshots SET snapshot_json=? WHERE intent_id=?", (json.dumps(snapshot), intent))
        with pytest.raises(ValueError):
            RP.project_delivery_fixture(ledger, intent, doc)
    finally:
        ledger.close()


def test_fixture_batch_rejects_changed_required_targets_without_digest_change():
    ledger, intents, doc = _batch_projection_fixture()
    try:
        with ledger._connect() as connection:
            snapshot = json.loads(connection.execute("SELECT snapshot_json FROM fixture_snapshots WHERE intent_id=?", (intents[0],)).fetchone()[0])
            snapshot["required_targets"] = snapshot["required_targets"][:1]
            connection.execute("UPDATE fixture_snapshots SET snapshot_json=? WHERE intent_id=?", (json.dumps(snapshot), intents[0]))
        with pytest.raises(ValueError):
            RP.project_delivery_batch_fixture(ledger, intents[:1], doc)
    finally:
        ledger.close()


def test_fixture_batch_rejects_inconsistent_approved_target_sets():
    from delivery_contract import canonical_snapshot
    ledger, intents, doc = _batch_projection_fixture(("published", "published"))
    try:
        with ledger._connect() as connection:
            snapshot = json.loads(connection.execute("SELECT snapshot_json FROM fixture_snapshots WHERE intent_id=?", (intents[1],)).fetchone()[0])
            snapshot["required_targets"] = snapshot["required_targets"][1:]
            encoded, digest = canonical_snapshot(snapshot)
            connection.execute("UPDATE fixture_snapshots SET snapshot_json=?,payload_digest=? WHERE intent_id=?", (encoded.decode("utf-8"), digest, intents[1]))
            connection.execute("UPDATE intents SET payload_digest=? WHERE intent_id=?", (digest, intents[1]))
        with pytest.raises(ValueError, match="target sets differ"):
            RP.project_delivery_batch_fixture(ledger, intents, doc)
    finally:
        ledger.close()


def test_fixture_batch_rejects_repost_without_overwriting_primary():
    ledger, intent, doc = _fixture_projection_ledger("repost-1")
    try:
        with pytest.raises(ValueError):
            RP.project_delivery_batch_fixture(ledger, [intent], doc)
        assert doc["posts"][0]["publish"]["status"] == "not_published"
    finally:
        ledger.close()


def test_fixture_batch_becomes_complete_only_after_readback_of_pending_target():
    ledger, intents, doc = _batch_projection_fixture()
    try:
        assert RP.project_delivery_batch_fixture(ledger, intents, doc)["complete"] is False
        evidence = {"state": "published", "platform": "facebook", "account_id": "page",
                    "provider_instance_id": "fixture-provider", "integration_id": "fixture-integration",
                    "remote_job_id": "job-facebook", "remote_post_id": None,
                    "platform_post_id": "page-7", "platform_url": "https://example.invalid/page-7",
                    "comment_id": "comment-7", "published_at": "2026-11-16T13:00:00Z",
                    "evidence_kind": "provider_confirmed"}
        assert ledger.reconcile(intents[1], "scheduled", verifier=lambda _row: evidence) == "published"
        result = RP.project_delivery_batch_fixture(ledger, intents, doc)
        assert result["complete"] is True
        assert result["completed_at"] == "2026-11-16T13:00:00Z"
        assert result["document"]["posts"][1]["publish"]["platform_id"] == "page-7"
    finally:
        ledger.close()


def _dispatch_batch_fixture():
    """Synthetic proof and in-memory providers: no filesystem, network or human approval."""
    from delivery_contract import canonical_snapshot
    from delivery_ledger import DeliveryLedger
    from postiz_adapter import FakePostiz
    from publish_dispatch import dispatch_synthetic

    ledger = DeliveryLedger.synthetic_memory()
    targets = [{"post_id": "post-yt", "platform": "youtube", "account_id": "video"},
               {"post_id": "post-fb", "platform": "facebook", "account_id": "page"}]
    work = []
    for target in targets:
        key = {"station_id": "station", "channel_id": "channel", "campaign_id": "campaign",
               "content_id": "content", **target, "occurrence_key": "initial"}
        payload = {**key, "text": "test", "artifacts": [], "required_targets": targets,
                   "mode": "scheduled", "scheduled_at": "2026-11-18T03:00:00Z",
                   "timezone": "Asia/Ho_Chi_Minh", "privacy": "public",
                   "post_format": "facebook_post" if target["platform"] == "facebook" else "youtube_video"}
        digest = canonical_snapshot(payload)[1]
        def proof(scope, digest=digest):
            return {"gate": scope["gate"], "scope": scope, "by": "fixture", "quote": "fixture",
                    "source_digest": digest if scope["gate"] == "g2" else "a" * 64}
        scopes = []
        for gate in ("g1", "g2"):
            scope = {name: key[name] for name in ("station_id", "channel_id", "campaign_id", "content_id", "post_id")}
            scope["post_id"] = "*" if gate == "g1" else key["post_id"]
            scope["gate"] = gate
            ledger.bind_scope(scope, 1)
            ledger.bind_scope_proof(scope, 1, verifier=proof)
            scopes.append((scope, 1))
        intent = ledger.prepare_fixture(key, payload, "channel/campaign/content", "postiz", 1, scopes=scopes)
        provider = FakePostiz()
        result = dispatch_synthetic(ledger, intent, payload, provider, verifier=proof)
        work.append((target, intent, provider, result.remote_job_id))
    doc = {"post_id": "content", "campaign_id": "campaign", "channel_id": "channel",
           "posts": [{"post_id": "post-yt", "channel": "youtube", "post_format": "youtube_video",
                      "publish": {"status": "not_published", "plan": ""}},
                     {"post_id": "post-fb", "channel": "facebook", "post_format": "facebook_post",
                      "publish": {"status": "not_published", "plan": ""}}]}
    return ledger, work, doc


def test_synthetic_batch_dispatch_poll_projection_completes_after_both_targets():
    from publish_dispatch import poll_synthetic
    ledger, work, doc = _dispatch_batch_fixture()
    try:
        intents = [w[1] for w in work]
        for target, intent, provider, job in work:
            provider.publish(job, platform_post_id=f"post-{target['platform']}",
                             platform_url=f"https://example.invalid/{target['platform']}",
                             comment_id="comment" if target["platform"] == "facebook" else None,
                             published_at="2026-11-16T12:00:00Z")
            polled = poll_synthetic(ledger, intent, provider, clock=lambda: 0.0, sleep=lambda _: None)
            assert (polled.state, polled.reason) == ("published", "confirmed")
        result = RP.project_delivery_batch_fixture(ledger, intents, doc)
        assert result["complete"] is True
        assert all(item["publish"]["status"] == "published" for item in result["document"]["posts"])
        assert all(provider.submission_count == 1 for _, _, provider, _ in work)
        assert all(item["publish"]["status"] == "not_published" for item in doc["posts"])
    finally:
        ledger.close()


@pytest.mark.parametrize("published_at,comment_id", [(None, "comment"), ("2026-11-16T12:00:00Z", None)])
def test_synthetic_batch_incomplete_facebook_evidence_stays_sync_pending(published_at, comment_id):
    from publish_dispatch import poll_synthetic
    ledger, work, doc = _dispatch_batch_fixture()
    try:
        target, intent, provider, job = work[1]
        provider.publish(job, platform_post_id="post-facebook", platform_url="https://example.invalid/facebook",
                         published_at=published_at, comment_id=comment_id)
        polled = poll_synthetic(ledger, intent, provider, clock=lambda: 0.0, sleep=lambda _: None)
        assert (polled.state, polled.reason) == ("published", "sync_pending")
        result = RP.project_delivery_batch_fixture(ledger, [w[1] for w in work], doc)
        assert result["complete"] is False
        assert target in result["sync_pending_targets"]
        assert result["document"]["posts"][1]["publish"]["status"] == "not_published"
        assert provider.submission_count == 1
    finally:
        ledger.close()
