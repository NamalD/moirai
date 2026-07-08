"""Tests for the CLI surface (SPEC.md §7.8).

These drive `moirai.cli.main()` in-process (no subprocess) against real
Themis/Lachesis/SubprocessProcessManager -- the same "no fakes" approach as
tests/test_integration_full_pipeline.py -- but against a trivial
script-based test template rather than the real claude-dev/dev-workflow
one, to keep the suite fast and avoid spawning real Claude Code sessions.
"""

import pytest

from moirai import cli

_TRIVIAL_TEMPLATE = """\
name: "trivial-echo"
description: "Trivial script-based template for CLI tests"
version: 1

parameters:
  - name: project
    description: "Project directory path"
    required: true
  - name: message
    description: "Message to write to the marker file"
    default: "hi"

workflow:
  id: "{{ .project | slugify }}-trivial"
  name: "Trivial echo for {{ .project }}"
  version: 1
  tasks:
    - id: "touch-marker"
      agent: "script-runner"
      command: "echo {{ .message }} > marker.txt"
      deps: []
"""


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    # Hermetic against whatever real ~/.moirai config a dev machine has.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MOIRAI_AGENTS_CONFIG", raising=False)


def _project_with_template(tmp_path, text=_TRIVIAL_TEMPLATE, filename="trivial-echo.yaml"):
    project_dir = tmp_path / "project"
    templates_dir = project_dir / ".moirai" / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / filename).write_text(text)
    return project_dir


# ─── run --template (end-to-end against real components) ────────────


def test_run_template_executes_and_reports_success(tmp_path, capsys):
    project_dir = _project_with_template(tmp_path)

    exit_code = cli.main(["run", "--template", "trivial-echo", "--project", str(project_dir)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "success" in out
    assert "touch-marker: COMPLETED" in out
    assert (project_dir / "marker.txt").read_text().strip() == "hi"


def test_run_template_passes_param_override(tmp_path):
    project_dir = _project_with_template(tmp_path)

    exit_code = cli.main(
        [
            "run",
            "--template",
            "trivial-echo",
            "--project",
            str(project_dir),
            "--param",
            "message=custom",
        ]
    )

    assert exit_code == 0
    assert (project_dir / "marker.txt").read_text().strip() == "custom"


def test_run_template_missing_required_param_is_rejected(tmp_path, capsys):
    # trivial-echo declares "project" as required but is instantiated with
    # a template that additionally requires an undeclared-by-CLI param.
    template_text = _TRIVIAL_TEMPLATE.replace(
        "  - name: message\n    description: \"Message to write to the marker file\"\n    default: \"hi\"\n",
        "  - name: required_thing\n    description: \"no default\"\n    required: true\n",
    )
    project_dir = _project_with_template(tmp_path, text=template_text)

    exit_code = cli.main(["run", "--template", "trivial-echo", "--project", str(project_dir)])

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "required_thing" in err


def test_run_review_flag_validates_without_executing(tmp_path, capsys):
    project_dir = _project_with_template(tmp_path)

    exit_code = cli.main(
        ["run", "--template", "trivial-echo", "--project", str(project_dir), "--review"]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "touch-marker" in out
    assert "agent=script-runner" in out
    assert not (project_dir / "marker.txt").exists()


def test_run_yaml_bypasses_template_substitution(tmp_path, capsys):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    yaml_path = tmp_path / "wf.yaml"
    yaml_path.write_text(
        f"""
workflow:
  id: "raw-yaml-wf"
  name: "Raw YAML workflow"
  version: 1
  tasks:
    - id: "write"
      agent: "script-runner"
      command: "echo raw > marker.txt"
      deps: []
"""
    )

    exit_code = cli.main(["run", "--yaml", str(yaml_path), "--project", str(project_dir)])

    assert exit_code == 0
    assert (project_dir / "marker.txt").read_text().strip() == "raw"


def test_run_builtin_dev_workflow_template_validates(tmp_path, capsys):
    # Regression test for the bug fixed in 3c62b3d: the built-in
    # dev-workflow.yaml has an *unquoted* placeholder
    # (`max_iterations: {{ .max_loop_attempts }}`) alongside its quoted
    # ones, and a "review" command that must match the real hermes CLI.
    # --review exercises the full instantiate -> Themis.validate path
    # against the real built-in template and agent registry without
    # spawning claude/hermes.
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    exit_code = cli.main(
        [
            "run",
            "--template",
            "dev-workflow",
            "--project",
            str(project_dir),
            "--param",
            "prompt=say hi",
            "--review",
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "implement" in out
    assert "review-loop" in out


def test_run_requires_template_yaml_or_prompt(capsys):
    exit_code = cli.main(["run"])
    assert exit_code == 2
    assert "required" in capsys.readouterr().err


def test_run_template_and_yaml_together_is_rejected(tmp_path, capsys):
    exit_code = cli.main(
        ["run", "--template", "x", "--yaml", str(tmp_path / "y.yaml"), "--project", str(tmp_path)]
    )
    assert exit_code == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_run_adhoc_prompt_without_template_or_yaml_is_not_implemented():
    with pytest.raises(NotImplementedError):
        cli.main(["run", "--prompt", "do something"])


# ─── list templates ───────────────────────────────────────────────────


def test_list_templates_prints_name_and_description(tmp_path, capsys):
    project_dir = _project_with_template(tmp_path)

    exit_code = cli.main(["list", "templates", "--project", str(project_dir)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "trivial-echo: Trivial script-based template for CLI tests" in out
    assert "dev-workflow:" in out


# ─── out-of-scope stubs ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "jobs"],
        ["status", "wf-1"],
        ["cancel", "wf-1"],
        ["update", "wf-1", "--prompt", "x"],
        ["create", "template", "foo", "--file", "x.yaml"],
    ],
)
def test_unimplemented_commands_raise_not_implemented_error(argv):
    with pytest.raises(NotImplementedError):
        cli.main(argv)


def test_dump_config_raises_not_implemented_error():
    with pytest.raises(NotImplementedError):
        cli.main(["--dump-config"])


def test_no_command_prints_help(capsys):
    exit_code = cli.main([])
    assert exit_code == 2
    assert "usage: moirai" in capsys.readouterr().out
