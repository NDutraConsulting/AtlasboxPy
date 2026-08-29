import subprocess
import sys

from validator_gateway.cli import main

EXPECTED_FILES = [
    "controllers/__init__.py",
    "controllers/example_controller.py",
    "validator_gateways/__init__.py",
    "validator_gateways/example_gateway.py",
]


def test_help_lists_init_subcommand():
    # Exercises the actual installed console script (P11-T1's acceptance is
    # specifically about `validator-gateway --help`, not just main()).
    result = subprocess.run(
        ["validator-gateway", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "init" in result.stdout


def test_fresh_init_creates_all_expected_files(tmp_path, capsys):
    exit_code = main(["init", "--path", str(tmp_path)])
    assert exit_code == 0
    for name in EXPECTED_FILES:
        assert (tmp_path / name).exists()
    out = capsys.readouterr().out
    assert "Created in" in out


def test_generated_gateway_imports_cleanly(tmp_path, monkeypatch):
    main(["init", "--path", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", "from validator_gateways.example_gateway import gateway"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_init_again_without_force_does_not_overwrite(tmp_path, capsys):
    main(["init", "--path", str(tmp_path)])
    marker = "# hand-edited by a developer\n"
    controller_path = tmp_path / "controllers/example_controller.py"
    controller_path.write_text(marker + controller_path.read_text())

    exit_code = main(["init", "--path", str(tmp_path)])
    assert exit_code != 0
    assert controller_path.read_text().startswith(marker)
    err = capsys.readouterr().err
    assert "already exist" in err


def test_init_with_force_overwrites(tmp_path):
    main(["init", "--path", str(tmp_path)])
    controller_path = tmp_path / "controllers/example_controller.py"
    controller_path.write_text("# hand-edited by a developer\n" + controller_path.read_text())

    exit_code = main(["init", "--path", str(tmp_path), "--force"])
    assert exit_code == 0
    assert not controller_path.read_text().startswith("# hand-edited")


def test_init_respects_custom_path(tmp_path):
    target = tmp_path / "some" / "nested" / "project"
    target.mkdir(parents=True)
    exit_code = main(["init", "--path", str(target)])
    assert exit_code == 0
    for name in EXPECTED_FILES:
        assert (target / name).exists()
    # Nothing was written outside the target directory.
    assert not (tmp_path / "controllers").exists()
