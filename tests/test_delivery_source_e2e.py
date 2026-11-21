"""Source-backed delivery acceptance, using a test-owned local station only.

The witness, campaign, text, account and provider are synthetic fixtures. This
is not a real user approval, a Postiz integration, or evidence of publication.
"""
import json
import socket
import sys
from pathlib import Path

import pytest
from test_register_publish import post  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import approval_gate as AG  # noqa: E402
import md_io  # noqa: E402
import post_paths as PP  # noqa: E402
import register_publish as RP  # noqa: E402
from delivery_contract import canonical_snapshot  # noqa: E402
from delivery_ledger import DeliveryLedger  # noqa: E402
from postiz_adapter import FakePostiz  # noqa: E402
from publish_dispatch import dispatch_fake  # noqa: E402


@pytest.mark.xfail(strict=True, raises=ValueError,
                   reason="dispatch_fake cố ý tắt (publish_dispatch.py) cho tới khi chứng minh được cách ly khỏi placeholder đám mây và dữ liệu người dùng; bật lại thì gỡ xfail")
def test_approved_source_is_dispatched_once_to_fake_provider(post, tmp_path, monkeypatch):
    """An approved source should reach the fake, without requiring real I/O.

    Regression: an implementation that refuses every source-backed dispatcher
    invocation cannot satisfy the approved offline contract. FakePostiz never
    sends to a network; all approvals belong exclusively to this test fixture.
    """
    def no_network(*args, **kwargs):
        raise AssertionError("network is forbidden in this fixture")

    monkeypatch.setattr(socket, "socket", no_network)
    campaign = post.parent
    fm, body = md_io.read_fm(campaign / "campaign.md")
    # The web publication is a pre-existing, synthetic fixture prerequisite;
    # this test does not claim to publish or independently verify that page.
    web_url = "https://example.invalid/blog/fixture"
    body = md_io.upsert_row(body, "CONTENT", "content_id", {
        "content_id": "AST-001", "folder": post.name, "g1": "", "web": web_url,
    }, them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(campaign / "campaign.md", fm, body)
    assert AG.open_gate(campaign, "g1", ["AST-001"], by="TEST FIXTURE",
                        quote="Duyệt đề tài giả", via="fixture") == ["AST-001"]
    assert RP.cmd_init(post) == 0
    PP.p(post, "gates").write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")
    assert RP.cmd_qa(post) == 0
    assert RP.cmd_approve(post, "TEST FIXTURE", "Duyệt bài giả", "fb", "", "") == 0

    key = {"station_id": "fixture-station", "channel_id": "kenh-b",
           "campaign_id": "CMP-2609-x", "content_id": "AST-001",
           "post_id": "AST-001-fb", "platform": "facebook", "account_id": "fixture-page",
           "occurrence_key": "initial"}
    first_comment = PP.p(post, "fb_comment").read_text(encoding="utf-8").replace(
        "{{BLOG_URL}}", web_url).strip()
    assert "{{" not in first_comment and web_url in first_comment
    payload = {**key, "text": "B", "post_format": "facebook_post",
               "first_comment": first_comment, "links": {"web": web_url},
               "depends_on": [{"kind": "web_url", "post_id": "AST-001-web", "url": web_url}],
               "artifacts": [], "mode": "scheduled",
               "scheduled_at": "2026-11-20T02:00:00Z", "timezone": "Asia/Ho_Chi_Minh",
               "privacy": "public"}
    g1 = {k: key[k] for k in ("station_id", "channel_id", "campaign_id", "content_id")}
    g1.update(post_id="*", gate="g1")
    g2 = {**g1, "post_id": key["post_id"], "gate": "g2"}
    RP.bind_delivery_payload(post, station_root=post.parents[2], scope=g2, payload=payload,
                             by="TEST FIXTURE", quote="Duyệt bản xem trước giả")
    AG.verify_delivery_payload(campaign, g2, payload)
    verifier = lambda scope: AG.read_delivery_gate_proof(campaign, scope)
    ledger = DeliveryLedger(tmp_path / "ledger.sqlite3")
    for scope in (g1, g2):
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=verifier)
    _, digest = canonical_snapshot(payload)
    intent = ledger.prepare(key, digest, "postiz", 1, scopes=[(g1, 1), (g2, 1)])
    fake = FakePostiz()

    result = dispatch_fake(campaign, post.parents[2], ledger, intent, payload, fake)

    assert result.state == "scheduled"
    assert ledger.get(intent)["state"] == "scheduled"
    assert fake.submission_count == 1

