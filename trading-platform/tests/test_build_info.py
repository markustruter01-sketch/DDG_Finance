import asyncio

import core.build_info as bi
from core import scheduler


def test_stamp_is_used_when_git_is_unavailable(tmp_path, monkeypatch):
    (tmp_path / "BUILD_COMMIT").write_text("abc1234def5678\n")
    monkeypatch.setattr(bi, "_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(bi.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    assert bi.current_commit() == "abc1234"


def test_no_stamp_no_git_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(bi.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    assert bi.current_commit() == bi.UNKNOWN


def test_unknown_never_raises_a_deploy_alert(monkeypatch):
    sent = []
    monkeypatch.setattr(scheduler, "_is_published_deployment", lambda: True)
    monkeypatch.setattr(bi, "current_commit", lambda: bi.UNKNOWN)
    import notifications.discord as discord
    monkeypatch.setattr(discord, "alert_critical", lambda **k: sent.append(k))
    asyncio.run(scheduler._deploy_hash_check())
    assert sent == []
