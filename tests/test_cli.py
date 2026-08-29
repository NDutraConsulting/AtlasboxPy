import subprocess
import sys
from pathlib import Path

from validator_gateway.cli import main

# Resolve the console script relative to the running interpreter, not via
# shell PATH lookup — `subprocess.run(["validator-gateway", ...])` only
# finds it when the venv is "activated" (its bin/ on PATH). Tests must pass
# under a plain `python -m pytest` invocation too, where it isn't.
_CLI_SCRIPT = str(Path(sys.executable).parent / "validator-gateway")

EXPECTED_FILES = [
    "controllers/__init__.py",
    "controllers/example_controller.py",
    "validator_gateways/__init__.py",
    "validator_gateways/example_gateway.py",
]


def test_help_lists_init_subcommand():
    # Exercises the actual installed console script (P11-T1's acceptance is
    # specifically about `validator-gateway --help`, not just main()).
    result = subprocess.run([_CLI_SCRIPT, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "init" in result.stdout
    assert "add-feature" in result.stdout


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


ADD_FEATURE_SHARED_FILES = [
    "controllers/__init__.py",
    "validator_gateways/__init__.py",
    "validator_gateways/classifying_validator_gateway.py",
    "validator_gateways/source_json.py",
]


def test_add_feature_creates_controller_gateway_and_shared_base(tmp_path, capsys):
    exit_code = main(["add-feature", "invoice", "--path", str(tmp_path)])
    assert exit_code == 0
    assert (tmp_path / "controllers/invoice_controller.py").exists()
    assert (tmp_path / "validator_gateways/invoice_validator_gateway.py").exists()
    for name in ADD_FEATURE_SHARED_FILES:
        assert (tmp_path / name).exists()
    assert "Created in" in capsys.readouterr().out


def test_add_feature_generated_gateway_imports_and_classifies_correctly(tmp_path, monkeypatch):
    main(["add-feature", "invoice", "--path", str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio\n"
            "from validator_gateways.invoice_validator_gateway import InvoiceValidatorGateway\n"
            "from validator_gateways.source_json import SourceJson\n"
            "gateway = InvoiceValidatorGateway(\n"
            "    source_json=SourceJson(\n"
            "        url='/api/invoices/1', method='GET', caller_type='api_route'\n"
            "    )\n"
            ")\n"
            "async def main():\n"
            "    ok = await gateway.handle(gateway.controller.get_invoice, '1')\n"
            "    assert ok.status == 'success', ok\n"
            "    err = await gateway.handle(gateway.controller.get_invoice, '2')\n"
            "    assert err.status == 'error', err\n"
            "    assert err.error.code == 'not_found', err\n"
            "asyncio.run(main())\n",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_add_feature_reuses_shared_base_across_multiple_features(tmp_path):
    main(["add-feature", "invoice", "--path", str(tmp_path)])
    base_path = tmp_path / "validator_gateways/classifying_validator_gateway.py"
    before = base_path.read_text()

    exit_code = main(["add-feature", "payment", "--path", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "controllers/payment_controller.py").exists()
    assert (tmp_path / "validator_gateways/payment_validator_gateway.py").exists()
    assert base_path.read_text() == before  # untouched by the second call
    # The first feature's own files are also untouched.
    assert (tmp_path / "controllers/invoice_controller.py").exists()


def test_add_feature_again_without_force_does_not_overwrite(tmp_path, capsys):
    main(["add-feature", "invoice", "--path", str(tmp_path)])
    marker = "# hand-edited by a developer\n"
    controller_path = tmp_path / "controllers/invoice_controller.py"
    controller_path.write_text(marker + controller_path.read_text())

    exit_code = main(["add-feature", "invoice", "--path", str(tmp_path)])
    assert exit_code != 0
    assert controller_path.read_text().startswith(marker)
    assert "already exist" in capsys.readouterr().err


def test_add_feature_rejects_non_snake_case_name(tmp_path):
    exit_code = main(["add-feature", "Invoice-Item", "--path", str(tmp_path)])
    assert exit_code != 0
    assert not (tmp_path / "controllers").exists()
