"""run.py without Node.js: say so, don't print a build failure nobody reads."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "run.py"


def _load_run(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("run_launcher", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(mod, "FRONTEND_DIR", tmp_path / "frontend")
    monkeypatch.delenv("RUNNING_IN_DOCKER", raising=False)
    return mod


def test_missing_node_prints_clear_message_and_does_not_try_to_build(monkeypatch, tmp_path, capsys):
    mod = _load_run(monkeypatch, tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))

    mod.ensure_frontend_built()

    out = capsys.readouterr().out
    assert "FALTA NODE.JS" in out
    assert "nodejs.org" in out
    assert calls == []


def test_with_node_it_builds(monkeypatch, tmp_path, capsys):
    mod = _load_run(monkeypatch, tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: "C:/node/npm.cmd")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: calls.append(cmd))

    mod.ensure_frontend_built()

    assert "npm install" in calls and "npm run build" in calls
    assert "FALTA NODE.JS" not in capsys.readouterr().out


def test_already_built_frontend_skips_everything(monkeypatch, tmp_path, capsys):
    mod = _load_run(monkeypatch, tmp_path)
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    mod.ensure_frontend_built()

    assert capsys.readouterr().out == ""
