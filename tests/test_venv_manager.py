"""
Tests for VenvManager resilience: pip invoked via the venv's interpreter, venv
health checks with ensurepip repair / recreation, readable launch errors, and
the configurable pip timeout.
"""

import subprocess
import sys
from unittest.mock import patch

import pytest

import mantyx.config as config_module
from mantyx.config import init_settings
from mantyx.core.venv_manager import VenvManager, _run_streaming


@pytest.fixture
def settings(tmp_path):
    """Point the settings singleton at an isolated temp base directory."""
    settings = init_settings(base_dir=tmp_path / "mantyx_base", pip_timeout_seconds=123)
    settings.ensure_directories()
    yield settings
    config_module._settings = None


def _make_moved_venv(settings, name="demo"):
    """Fake a venv that was moved after creation.

    bin/python still works (it just execs the test interpreter, like the real
    symlink to the system Python), but bin/pip's shebang points at the venv's
    old location, which no longer exists.
    """
    bin_dir = settings.venvs_dir / name / "bin"
    bin_dir.mkdir(parents=True)

    python = bin_dir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)

    pip = bin_dir / "pip"
    pip.write_text("#!/old/mantyx_data/venvs/demo/bin/python\nimport pip\n")
    pip.chmod(0o755)
    return bin_dir


def test_install_requirements_works_when_pip_shebang_is_stale(settings, tmp_path):
    """A venv whose bin/pip has a dead shebang still installs requirements,
    because pip is run as `bin/python -m pip`."""
    bin_dir = _make_moved_venv(settings)

    # Sanity check: this is exactly the incident's failure mode.
    with pytest.raises(FileNotFoundError):
        subprocess.run([str(bin_dir / "pip"), "--version"], check=False)

    # `pip` is already installed in the test interpreter, so this resolves
    # offline without modifying anything.
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("--no-index\npip\n")

    logs: list[str] = []
    output = VenvManager().install_requirements("demo", requirements, on_log=logs.append)

    assert "Requirement already satisfied: pip" in output
    assert "Dependencies installed successfully." in logs


def test_pip_is_never_invoked_via_bin_pip(settings, tmp_path):
    """Venv creation and installs all run pip as `<venv>/bin/python -m pip`."""
    manager = VenvManager()
    python = str(manager.get_python_executable("demo"))
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n")

    commands: list[list[str]] = []

    def fake_run(cmd, on_log, timeout=None):
        commands.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            (settings.venvs_dir / "demo" / "bin").mkdir(parents=True)
        return ""

    with patch("mantyx.core.venv_manager._run_streaming", side_effect=fake_run):
        manager.install_requirements("demo", requirements)

    pip_commands = [c for c in commands if c[1:3] == ["-m", "pip"]]
    assert pip_commands == [
        [python, "-m", "pip", "install", "--upgrade", "pip"],
        [python, "-m", "pip", "install", "-r", str(requirements)],
    ]
    assert not any(c[0].endswith("/pip") for c in commands)


def test_unhealthy_venv_is_repaired_with_ensurepip(settings):
    """If pip is broken but the interpreter works, ensurepip repairs the venv
    in place instead of rebuilding it."""
    _make_moved_venv(settings)
    manager = VenvManager()
    logs: list[str] = []

    with (
        patch.object(manager, "is_healthy", side_effect=[False, True]),
        patch("mantyx.core.venv_manager._run_streaming", return_value="") as mock_run,
        patch.object(manager, "remove") as mock_remove,
        patch.object(manager, "create") as mock_create,
    ):
        manager.ensure_healthy("demo", on_log=logs.append)

    python = str(manager.get_python_executable("demo"))
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == [python, "-m", "ensurepip", "--upgrade"]
    mock_remove.assert_not_called()
    mock_create.assert_not_called()
    assert any("attempting repair with ensurepip" in line for line in logs)
    assert any("Repaired virtual environment for demo with ensurepip" in line for line in logs)


def test_venv_still_unhealthy_after_ensurepip_is_recreated(settings):
    """If ensurepip doesn't fix it, the venv is deleted and recreated."""
    _make_moved_venv(settings)
    manager = VenvManager()
    logs: list[str] = []

    with (
        patch.object(manager, "is_healthy", return_value=False),
        patch("mantyx.core.venv_manager._run_streaming", return_value=""),
        patch.object(manager, "create") as mock_create,
    ):
        manager.ensure_healthy("demo", on_log=logs.append)

    assert not manager.get_venv_path("demo").exists()
    mock_create.assert_called_once()
    assert any("rebuilding virtual environment for demo" in line for line in logs)


def test_venv_with_broken_python_symlink_is_recreated(settings, tmp_path):
    """A venv whose bin/python symlink target is gone (e.g. after an OS Python
    upgrade) skips ensurepip, is recreated, and then gets its requirements."""
    bin_dir = settings.venvs_dir / "demo" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to("/usr/bin/python3.0-long-gone")
    stale_marker = settings.venvs_dir / "demo" / "stale.txt"
    stale_marker.write_text("old venv contents")

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n")

    manager = VenvManager()
    python = str(manager.get_python_executable("demo"))
    commands: list[list[str]] = []
    logs: list[str] = []

    def fake_run(cmd, on_log, timeout=None):
        commands.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            bin_dir.mkdir(parents=True)
        return ""

    with patch("mantyx.core.venv_manager._run_streaming", side_effect=fake_run):
        manager.install_requirements("demo", requirements, on_log=logs.append)

    assert not stale_marker.exists()
    assert [sys.executable, "-m", "venv", str(manager.get_venv_path("demo"))] in commands
    assert not any("ensurepip" in c for c in commands)
    assert commands[-1] == [python, "-m", "pip", "install", "-r", str(requirements)]
    assert any("rebuilding virtual environment for demo" in line for line in logs)


def test_launch_oserror_becomes_readable_runtime_error(settings, tmp_path):
    """An OSError launching pip surfaces as an actionable RuntimeError, not a
    bare "[Errno 2] ..."."""
    manager = VenvManager()
    python = str(manager.get_python_executable("demo"))
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n")

    with (
        patch.object(manager, "ensure_healthy"),
        patch(
            "mantyx.core.venv_manager.subprocess.Popen",
            side_effect=FileNotFoundError(2, "No such file or directory", python),
        ),
        pytest.raises(RuntimeError) as exc_info,
    ):
        manager.install_requirements("demo", requirements)

    message = str(exc_info.value)
    assert message == (
        f"Could not run pip for app demo's environment "
        f"(No such file or directory: {python}); the environment may need rebuilding"
    )
    assert "[Errno" not in message


def test_pip_installs_use_configured_timeout(settings, tmp_path):
    """pip install calls honor settings.pip_timeout_seconds."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests\n")
    manager = VenvManager()

    with (
        patch.object(manager, "ensure_healthy"),
        patch("mantyx.core.venv_manager._run_streaming", return_value="") as mock_run,
    ):
        manager.install_requirements("demo", requirements)

    assert mock_run.call_args.kwargs["timeout"] == 123


def test_run_streaming_enforces_timeout_while_output_is_streaming():
    """The timeout fires even while the process holds stdout open."""
    cmd = [sys.executable, "-c", "import time; print('working', flush=True); time.sleep(30)"]
    lines: list[str] = []

    with pytest.raises(subprocess.TimeoutExpired):
        _run_streaming(cmd, lines.append, timeout=1)

    assert lines == ["working"]
