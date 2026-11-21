"""A revocation must affect only the explicitly identified delivery intent."""
import sqlite3
import sys
import json
import os
import subprocess
from types import SimpleNamespace
from datetime import datetime
from pathlib import Path

import pytest
from test_register_publish import post  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "pipeline"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import approval_gate as AG  # noqa: E402
from delivery_ledger import DeliveryLedger  # noqa: E402
import md_io  # noqa: E402
import event_log as EV  # noqa: E402
import register_publish as RP  # noqa: E402


def _intent(ledger):
    key = {"station_id": "st", "channel_id": "channel", "campaign_id": "campaign",
           "content_id": "content", "post_id": "post", "platform": "facebook",
           "account_id": "page", "occurrence_key": "initial"}
    base = {name: key[name] for name in ("station_id", "channel_id", "campaign_id", "content_id")}
    scopes = [({**base, "post_id": "*", "gate": "g1"}, 1),
              ({**base, "post_id": "post", "gate": "g2"}, 1)]
    for scope, generation in scopes:
        ledger.bind_scope(scope, generation)
    return ledger.prepare(key, "digest", "legacy", 1, scopes=scopes), key


def test_revocation_rejects_wrong_campaign_without_changing_intent(tmp_path):
    ledger = DeliveryLedger(tmp_path / "ledger.sqlite3")
    intent, key = _intent(ledger)
    assert hasattr(AG, "revoke_delivery_intent"), "opt-in revocation entrypoint is missing"
    with pytest.raises(ValueError):
        AG.revoke_delivery_intent(ledger, intent, 1, scope={**key, "campaign_id": "other"},
                                  gate="g2", by="Duc", quote="Thu hồi bài này")
    assert ledger.get(intent)["state"] == "prepared"


def test_revocation_keeps_human_quote_and_blocks_claim(tmp_path):
    ledger = DeliveryLedger(tmp_path / "ledger.sqlite3")
    intent, key = _intent(ledger)
    assert hasattr(AG, "revoke_delivery_intent"), "opt-in revocation entrypoint is missing"
    assert AG.revoke_delivery_intent(ledger, intent, 1, scope=key, gate="g2", by="Duc",
                                     quote="Thu hồi bài này") == "cancelled"
    with pytest.raises(ValueError):
        ledger.claim(intent, 1)
    with sqlite3.connect(ledger.path) as con:
        row = con.execute("SELECT actor, quote, gate FROM events WHERE kind='revoke'").fetchone()
    assert row == ("Duc", "Thu hồi bài này", "g2")


def _scope(gate, post_id="*"):
    return {"station_id": "st", "channel_id": "kenh-b", "campaign_id": "CMP-2609-x",
            "content_id": "AST-001", "post_id": post_id, "gate": gate}


def _set_qa(post, status):
    path = post / "publish.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    next(p for p in data["posts"] if p["post_id"] == "AST-001-fb")["quality_check"] = status
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _g1(post):
    campaign = post.parent
    fm, body = md_io.read_fm(campaign / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "g1": "2026-11-16"},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(campaign / "campaign.md", fm, body)
    return campaign


def test_g1_date_without_human_event_is_not_delivery_approval(post):
    campaign = _g1(post)
    assert hasattr(AG, "read_delivery_gate_proof"), "source approval reader missing"
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(campaign, _scope("g1"))


def test_automatic_g1_event_is_not_human_delivery_approval(post):
    campaign = _g1(post)
    EV.write(campaign, "g1_approved", post="AST-001", by="tự động", via="autonomy",
             note="autonomy=full — không có cổng người")
    assert hasattr(AG, "read_delivery_gate_proof"), "source approval reader missing"
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(campaign, _scope("g1"))


def test_g1_proof_requires_matching_human_event(post):
    campaign = _g1(post)
    EV.write(campaign, "g1_approved", post="AST-001", by="Duc", via="phiên",
             note="Duyệt đề tài này", at=datetime.fromisoformat("2026-11-16T10:00:00+07:00"))
    proof = AG.read_delivery_gate_proof(campaign, _scope("g1"))
    assert proof["by"] == "Duc" and proof["quote"] == "Duyệt đề tài này"
    assert len(proof["source_digest"]) == 64


def test_g3_date_without_human_event_is_not_delivery_approval(post):
    campaign = post.parent
    fm, body = md_io.read_fm(campaign / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "g3": "2026-11-16"},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(campaign / "campaign.md", fm, body)
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(campaign, _scope("g3"))


def test_g2_proof_is_bound_to_the_exact_post_and_review(post):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt bài Facebook", "fb", "", "") == 0
    _set_qa(post, "passed")
    assert hasattr(AG, "read_delivery_gate_proof"), "source approval reader missing"
    proof = AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-fb"))
    assert proof["gate"] == "g2" and proof["by"] == "Duc"
    assert proof["quote"] == "Duyệt bài Facebook" and len(proof["source_digest"]) == 64
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-yt"))


def test_g2_failed_qa_cannot_be_used_without_a_recorded_override(post):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt bài Facebook", "fb", "", "") == 0
    path = post / "publish.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    next(p for p in data["posts"] if p["post_id"] == "AST-001-fb")["quality_check"] = "failed"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-fb"))


@pytest.mark.parametrize("qa", ["", "pending", None, "unknown"])
def test_g2_missing_or_pending_qa_is_not_delivery_approval(post, qa):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt bài Facebook", "fb", "", "") == 0
    path = post / "publish.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    next(p for p in data["posts"] if p["post_id"] == "AST-001-fb")["quality_check"] = qa
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-fb"))


@pytest.mark.parametrize("note,allowed", [
    ("Duyệt [override-qa: đã kiểm tra]", True),
    ("Duyệt [override-qa: ]", False),
    ("Duyệt [override-qa:", False),
])
def test_failed_qa_requires_nonempty_recorded_override(post, note, allowed):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", note, "fb", "", "") == 0
    _set_qa(post, "failed")
    if allowed:
        assert AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-fb"))["quote"] == note
    else:
        with pytest.raises(ValueError):
            AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-fb"))


def test_claim_fails_if_source_approval_changes_after_binding(post, tmp_path):
    campaign = _g1(post)
    fm, body = md_io.read_fm(campaign / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(campaign / "campaign.md", fm, body)
    EV.write(campaign, "g1_approved", post="AST-001", by="Duc", via="phiên",
             note="Duyệt đề tài này", at=datetime.fromisoformat("2026-11-16T10:00:00+07:00"))
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt bài Facebook", "fb", "", "") == 0
    _set_qa(post, "passed")
    ledger = DeliveryLedger(tmp_path / "ledger.sqlite3")
    g1, g2 = _scope("g1"), _scope("g2", "AST-001-fb")
    verifier = lambda scope: AG.read_delivery_gate_proof(campaign, scope)
    ledger.bind_scope(g1, 1)
    ledger.bind_scope(g2, 1)
    ledger.bind_scope_proof(g1, 1, verifier=verifier)
    ledger.bind_scope_proof(g2, 1, verifier=verifier)
    key = {name: g2[name] for name in ("station_id", "channel_id", "campaign_id", "content_id", "post_id")}
    key.update(platform="facebook", account_id="page", occurrence_key="initial")
    intent = ledger.prepare(key, "digest", "legacy", 1, scopes=[(g1, 1), (g2, 1)])
    path = post / "publish.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    next(p for p in data["posts"] if p["post_id"] == "AST-001-fb")["review"]["note"] = "Đã đổi"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        ledger.claim(intent, 1, verifier=verifier)
    assert ledger.get(intent)["state"] == "prepared"


def test_unchanged_source_proofs_allow_ledger_claim_without_dispatch(post, tmp_path):
    campaign = _g1(post)
    fm, body = md_io.read_fm(campaign / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(campaign / "campaign.md", fm, body)
    EV.write(campaign, "g1_approved", post="AST-001", by="Duc", via="phiên",
             note="Duyệt đề tài này", at=datetime.fromisoformat("2026-11-16T10:00:00+07:00"))
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt bài Facebook", "fb", "", "") == 0
    _set_qa(post, "passed")
    ledger = DeliveryLedger(tmp_path / "ledger.sqlite3")
    g1, g2 = _scope("g1"), _scope("g2", "AST-001-fb")
    verifier = lambda scope: AG.read_delivery_gate_proof(campaign, scope)
    for scope in (g1, g2):
        ledger.bind_scope(scope, 1)
        ledger.bind_scope_proof(scope, 1, verifier=verifier)
    key = {name: g2[name] for name in ("station_id", "channel_id", "campaign_id", "content_id", "post_id")}
    key.update(platform="facebook", account_id="page", occurrence_key="initial")
    intent = ledger.prepare(key, "digest", "legacy", 1, scopes=[(g1, 1), (g2, 1)])
    attempt = ledger.claim(intent, 1, verifier=verifier)
    assert attempt and ledger.get(intent)["state"] == "submitting"


def _payload():
    return {"station_id": "st", "channel_id": "kenh-b", "campaign_id": "CMP-2609-x",
            "content_id": "AST-001", "post_id": "AST-001-fb", "platform": "facebook",
            "account_id": "page1", "text": "Bài kiểm thử", "artifacts": [],
            "timezone": "Asia/Ho_Chi_Minh", "scheduled_at": "2026-11-20T02:00:00Z",
            "privacy": "public", "occurrence_key": "initial"}


def test_payload_preview_requires_an_explicit_occurrence_key():
    payload = _payload()
    del payload["occurrence_key"]
    with pytest.raises(ValueError):
        AG.delivery_payload_digest(_scope("g2", "AST-001-fb"), payload)


def test_g2_reader_rejects_junction_folder_even_when_target_inside_campaign(post):
    alias = post.parent / "junction-post"
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(post)],
                       check=True, capture_output=True)
    else:
        alias.symlink_to(post, target_is_directory=True)
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": alias.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt G2", "fb", "", "") == 0
    _set_qa(post, "passed")
    with pytest.raises(ValueError):
        AG.read_delivery_gate_proof(post.parent, _scope("g2", "AST-001-fb"))


@pytest.mark.parametrize("attributes", [0x1000, 0x40000, 0x400000, 0x400])
def test_local_path_metadata_rejects_offline_or_reparse_without_read(tmp_path, monkeypatch, attributes):
    path = tmp_path / "publish.json"
    path.write_text("fixture", encoding="utf-8")
    original = Path.lstat

    def fake_lstat(self):
        info = original(self)
        if self == path:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=attributes)
        return info

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(ValueError):
        AG.check_delivery_local_path(path, file=True)


def test_payload_binding_changes_on_account_or_content(post):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt G2", "fb", "", "") == 0
    _set_qa(post, "passed")
    assert hasattr(RP, "bind_delivery_payload"), "payload binding writer missing"
    binding = RP.bind_delivery_payload(post, station_root=post.parents[2], scope=_scope("g2", "AST-001-fb"),
                                       payload=_payload(), by="Duc", quote="Duyệt bản xem trước")
    assert binding["payload_digest"] and binding["event_id"]
    assert AG.verify_delivery_payload(post.parent, _scope("g2", "AST-001-fb"), _payload())
    for changed in ({**_payload(), "account_id": "page2"}, {**_payload(), "text": "Đã đổi"},
                    {**_payload(), "scheduled_at": "2026-11-21T02:00:00Z"},
                    {**_payload(), "privacy": "private"},
                    {**_payload(), "occurrence_key": "repost-1"},
                    {**_payload(), "artifacts": [{"id": "other", "sha256": "a" * 64}]}):
        with pytest.raises(ValueError):
            AG.verify_delivery_payload(post.parent, _scope("g2", "AST-001-fb"), changed)


def test_delivery_lock_refuses_competing_owner_without_removing_its_lock(tmp_path):
    assert hasattr(AG, "delivery_source_lock"), "delivery lock missing"
    with AG.delivery_source_lock(tmp_path):
        with pytest.raises((FileExistsError, ValueError)):
            with AG.delivery_source_lock(tmp_path):
                pass
        assert (tmp_path / "logs" / "publishing" / "source.lock").exists()
    assert not (tmp_path / "logs" / "publishing" / "source.lock").exists()


def test_delivery_lock_rejects_logs_junction_before_creating_external_directory(tmp_path):
    station = tmp_path / "station"
    outside = tmp_path / "outside"
    station.mkdir()
    outside.mkdir()
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(station / "logs"), str(outside)],
                       check=True, capture_output=True)
    else:
        (station / "logs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        with AG.delivery_source_lock(station):
            pass
    assert not (outside / "publishing").exists()


def test_delivery_lock_rejects_internal_junction_without_creating_lock(tmp_path):
    station = tmp_path / "station"
    target = station / "actual-logs"
    target.mkdir(parents=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(station / "logs"), str(target)],
                       check=True, capture_output=True)
    else:
        (station / "logs").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        with AG.delivery_source_lock(station):
            pass
    assert not (target / "publishing").exists()


@pytest.mark.parametrize("attributes", [0x1000, 0x40000, 0x400000])
def test_delivery_lock_rejects_offline_parent_before_creating_directory(tmp_path, monkeypatch, attributes):
    logs = tmp_path / "logs"
    logs.mkdir()
    original = Path.lstat

    def fake_lstat(self):
        info = original(self)
        if self == logs:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=attributes)
        return info

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(ValueError):
        with AG.delivery_source_lock(tmp_path):
            pass
    assert not (logs / "publishing").exists()


def test_payload_binding_cannot_write_duplicate_post_outside_source_folder(post):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt G2", "fb", "", "") == 0
    _set_qa(post, "passed")
    other = post.parent / "other"
    other.mkdir()
    (other / "publish.json").write_bytes((post / "publish.json").read_bytes())
    with pytest.raises(ValueError):
        RP.bind_delivery_payload(other, station_root=post.parents[2], scope=_scope("g2", "AST-001-fb"),
                                 payload=_payload(), by="Duc", quote="Duyệt bản xem trước")
    assert "delivery_binding" not in (other / "publish.json").read_text(encoding="utf-8")


def test_preview_binding_requires_new_explicit_words_and_keeps_prior_event(post):
    fm, body = md_io.read_fm(post.parent / "campaign.md")
    body = md_io.upsert_row(body, "CONTENT", "content_id",
                            {"content_id": "AST-001", "folder": post.name},
                            them_cot=True, chi_cap_nhat=True)
    md_io.write_fm(post.parent / "campaign.md", fm, body)
    assert RP.cmd_init(post) == 0
    assert RP.cmd_approve(post, "Duc", "Duyệt G2", "fb", "", "") == 0
    _set_qa(post, "passed")
    with pytest.raises(ValueError):
        RP.bind_delivery_payload(post, station_root=post.parents[2], scope=_scope("g2", "AST-001-fb"),
                                 payload=_payload(), by="Duc", quote=" ")
    first = RP.bind_delivery_payload(post, station_root=post.parents[2], scope=_scope("g2", "AST-001-fb"),
                                     payload=_payload(), by="Duc", quote="Duyệt bản một")
    revised = {**_payload(), "text": "Bản hai"}
    second = RP.bind_delivery_payload(post, station_root=post.parents[2], scope=_scope("g2", "AST-001-fb"),
                                      payload=revised, by="Duc", quote="Duyệt bản hai")
    data = json.loads((post / "publish.json").read_text(encoding="utf-8"))
    review = next(p for p in data["posts"] if p["post_id"] == "AST-001-fb")["review"]
    assert first["event_id"] != second["event_id"]
    assert review["delivery_binding_history"][-1] == first
    assert review["delivery_binding"] == second
    with pytest.raises(ValueError):
        AG.verify_delivery_payload(post.parent, _scope("g2", "AST-001-fb"), _payload())
