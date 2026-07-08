"""Tests for template loading and instantiation (SPEC.md §7.7)."""

import pytest
import yaml

from moirai import templates
from moirai.themis import Themis
from moirai.types import AgentDef

_TEMPLATE_TEXT = """\
name: "greet"
description: "Simple greeting template for tests"
version: 1

parameters:
  - name: target
    description: "Who to greet"
    required: true
  - name: greeting
    description: "Greeting word"
    default: "Hello"

workflow:
  id: "{{ .target | slugify }}-greet"
  name: "Greet {{ .target }}"
  version: 1
  tasks:
    - id: "greet"
      agent: "script-runner"
      command: "echo {{ .greeting }}, {{ .target }}!"
      deps: []
"""


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    # Every test in this file must be hermetic against whatever real
    # ~/.moirai/templates a dev machine happens to have.
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _write_template(base_dir, filename="greet.yaml", text=_TEMPLATE_TEXT):
    templates_dir = base_dir / ".moirai" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    path = templates_dir / filename
    path.write_text(text)
    return path


# ─── Substitution ───────────────────────────────────────────────────


def test_plain_substitution_and_default_param(tmp_path):
    _write_template(tmp_path)
    template = templates.load_template("greet", project_dir=str(tmp_path))

    yaml_text = templates.instantiate(template, {"target": "World"})

    assert 'name: Greet World' in yaml_text
    assert "echo Hello, World!" in yaml_text


def test_slugify_filter_lowercases_and_collapses_non_alnum(tmp_path):
    _write_template(tmp_path)
    template = templates.load_template("greet", project_dir=str(tmp_path))

    yaml_text = templates.instantiate(template, {"target": "Ada Lovelace!! 2.0"})

    assert "id: ada-lovelace-2-0-greet" in yaml_text


def test_explicit_param_overrides_default(tmp_path):
    _write_template(tmp_path)
    template = templates.load_template("greet", project_dir=str(tmp_path))

    yaml_text = templates.instantiate(template, {"target": "World", "greeting": "Yo"})

    assert "echo Yo, World!" in yaml_text


def test_param_value_with_double_quote_is_escaped(tmp_path):
    _write_template(tmp_path)
    template = templates.load_template("greet", project_dir=str(tmp_path))

    yaml_text = templates.instantiate(template, {"target": 'the "World"'})

    doc = yaml.safe_load(yaml_text)
    assert doc["workflow"]["name"] == 'Greet the "World"'


def test_missing_required_parameter_is_rejected(tmp_path):
    _write_template(tmp_path)
    template = templates.load_template("greet", project_dir=str(tmp_path))

    with pytest.raises(templates.TemplateError, match="target"):
        templates.instantiate(template, {})


def test_instantiated_yaml_is_valid_per_themis(tmp_path):
    _write_template(tmp_path)
    template = templates.load_template("greet", project_dir=str(tmp_path))
    yaml_text = templates.instantiate(template, {"target": "World"})

    known_agents = [AgentDef(id="script-runner", name="Script Runner", command="/bin/bash")]
    result = Themis().validate(yaml_text, known_agents)

    assert result.is_valid, result.errors


# ─── Lookup / precedence ────────────────────────────────────────────


def test_load_template_not_found_raises(tmp_path):
    with pytest.raises(templates.TemplateError):
        templates.load_template("does-not-exist", project_dir=str(tmp_path))


def test_project_template_takes_precedence_over_user_template(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))
    _write_template(home_dir, text=_TEMPLATE_TEXT.replace("Simple greeting", "User-level greeting"))

    project_dir = tmp_path / "project"
    _write_template(project_dir, text=_TEMPLATE_TEXT.replace("Simple greeting", "Project-level greeting"))

    template = templates.load_template("greet", project_dir=str(project_dir))
    assert template.description == "Project-level greeting template for tests"


def test_user_template_used_when_no_project_override(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))
    _write_template(home_dir, text=_TEMPLATE_TEXT.replace("Simple greeting", "User-level greeting"))

    template = templates.load_template("greet", project_dir=str(tmp_path / "project"))
    assert template.description == "User-level greeting template for tests"


def test_builtin_dev_workflow_template_loads(tmp_path):
    template = templates.load_template("dev-workflow")
    names = {p.name for p in template.parameters}
    assert names == {"project", "prompt", "max_loop_attempts"}


# ─── list_templates ─────────────────────────────────────────────────


def test_list_templates_includes_builtin_and_project(tmp_path):
    _write_template(tmp_path, filename="greet.yaml")

    found = templates.list_templates(project_dir=str(tmp_path))
    names = {t.name for t in found}

    assert "greet" in names
    assert "dev-workflow" in names  # built-in


def test_list_templates_dedupes_by_name_with_project_precedence(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))
    _write_template(home_dir, text=_TEMPLATE_TEXT.replace("Simple greeting", "User-level greeting"))

    project_dir = tmp_path / "project"
    _write_template(project_dir, text=_TEMPLATE_TEXT.replace("Simple greeting", "Project-level greeting"))

    found = templates.list_templates(project_dir=str(project_dir))
    matches = [t for t in found if t.name == "greet"]

    assert len(matches) == 1
    assert matches[0].description == "Project-level greeting template for tests"


def test_list_templates_skips_non_template_yaml_files(tmp_path):
    # moirai/defaults/agents.yaml has no top-level 'workflow:' key and must
    # not be mistaken for a template when scanning the built-in directory.
    found = templates.list_templates()
    assert all(t.name != "agents" for t in found)
