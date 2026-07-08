"""Template workflows — parameterized YAML so common flows don't need Clotho
regeneration each run (SPEC.md §7.7).

Templates are plain YAML files with a `name`/`description`/`version`/
`parameters` header and a `workflow:` body. The body is *not* valid YAML on
its own — placeholders like `{{ .prompt }}` and `{{ .project | slugify }}`
parse as YAML flow-mapping syntax and blow up `yaml.safe_load` — so
substitution happens on the raw text before the body is ever parsed. Only
plain string substitution is implemented (no real Go template engine),
which is sufficient for the `{{ .param }}` / `{{ .param | filter }}` subset
actually used by dev-workflow.yaml.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# Body starts at the first top-level (unindented) `workflow:` line. Everything
# before that is the header (name/description/version/parameters), which
# never contains placeholders and can be parsed as-is.
_HEADER_BODY_SPLIT_RE = re.compile(r"(?m)^workflow:[ \t]*$")

# `{{ .param }}` or `{{ .param | filter }}`.
_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*\|\s*(?P<filter>[A-Za-z_][A-Za-z0-9_]*))?\s*\}\}"
)


class TemplateError(Exception):
    """Raised for any template lookup, parse, or instantiation failure."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


_FILTERS = {"slugify": _slugify}


@dataclass
class TemplateParam:
    name: str
    description: str = ""
    required: bool = False
    default: Optional[Any] = None


@dataclass
class TemplateDef:
    """A loaded (but not yet instantiated) template."""

    name: str
    description: str
    version: int
    parameters: list[TemplateParam]
    source_path: str
    raw_text: str = field(repr=False)


def _builtin_templates_dir() -> Path:
    return Path(__file__).parent / "defaults"


def _search_dirs(project_dir: Optional[str]) -> list[Path]:
    """Directories to search, in lookup precedence order (§7.7 storage locations).

    Precedence: project-specific > user-local > built-in — i.e. the most
    specific scope wins, matching the usual convention for layered config
    (git config's system < global < local, but inverted since we search
    most-specific-first rather than merging). The SPEC lists the three
    locations but doesn't state precedence, so this is a deliberate choice
    made here, not something copied from the spec text.
    """
    dirs = []
    if project_dir is not None:
        dirs.append(Path(project_dir) / ".moirai" / "templates")
    dirs.append(Path.home() / ".moirai" / "templates")
    dirs.append(_builtin_templates_dir())
    return dirs


def find_template_file(name: str, project_dir: Optional[str] = None) -> Path:
    dirs = _search_dirs(project_dir)
    for base in dirs:
        candidate = base / f"{name}.yaml"
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(d) for d in dirs)
    raise TemplateError(f"Template '{name}' not found (searched: {searched})")


def _split_header_body(raw_text: str, template_name: str) -> tuple[str, str]:
    match = _HEADER_BODY_SPLIT_RE.search(raw_text)
    if not match:
        raise TemplateError(
            f"Template '{template_name}' has no top-level 'workflow:' key"
        )
    return raw_text[: match.start()], raw_text[match.start() :]


def _parse_header(header_text: str, template_name: str) -> dict:
    try:
        header = yaml.safe_load(header_text) or {}
    except yaml.YAMLError as exc:
        raise TemplateError(
            f"Template '{template_name}' header is invalid YAML: {exc}"
        ) from exc
    if not isinstance(header, dict):
        raise TemplateError(f"Template '{template_name}' header must be a YAML mapping")
    return header


def _parse_params(header: dict, template_name: str) -> list[TemplateParam]:
    raw_params = header.get("parameters") or []
    if not isinstance(raw_params, list):
        raise TemplateError(f"Template '{template_name}' 'parameters' must be a list")
    params = []
    for i, raw_param in enumerate(raw_params):
        if not isinstance(raw_param, dict) or "name" not in raw_param:
            raise TemplateError(
                f"Template '{template_name}' parameters[{i}] must be a mapping with a 'name'"
            )
        params.append(
            TemplateParam(
                name=raw_param["name"],
                description=raw_param.get("description", ""),
                required=bool(raw_param.get("required", False)),
                default=raw_param.get("default"),
            )
        )
    return params


def _template_from_file(path: Path) -> TemplateDef:
    raw_text = path.read_text()
    header_text, _ = _split_header_body(raw_text, path.stem)
    header = _parse_header(header_text, path.stem)
    return TemplateDef(
        name=header.get("name", path.stem),
        description=header.get("description", ""),
        version=header.get("version", 1),
        parameters=_parse_params(header, path.stem),
        source_path=str(path),
        raw_text=raw_text,
    )


def load_template(name: str, project_dir: Optional[str] = None) -> TemplateDef:
    path = find_template_file(name, project_dir)
    return _template_from_file(path)


def list_templates(project_dir: Optional[str] = None) -> list[TemplateDef]:
    """All available templates, deduped by name.

    Iterates least-specific to most-specific so a later (more specific)
    directory overwrites an earlier one for the same template name —
    consistent with `find_template_file`'s precedence order.
    """
    by_name: dict[str, TemplateDef] = {}
    for base in reversed(_search_dirs(project_dir)):
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.yaml")):
            try:
                template = _template_from_file(path)
            except TemplateError:
                continue  # not a template file (e.g. defaults/agents.yaml) — skip
            by_name[template.name] = template
    return sorted(by_name.values(), key=lambda t: t.name)


def _resolve_params(template: TemplateDef, params: dict[str, str]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    missing = []
    for p in template.parameters:
        if p.name in params:
            resolved[p.name] = params[p.name]
        elif p.default is not None:
            resolved[p.name] = p.default
        elif p.required:
            missing.append(p.name)
        else:
            resolved[p.name] = ""
    if missing:
        raise TemplateError(
            f"Template '{template.name}' missing required parameter(s): {', '.join(missing)}"
        )
    return resolved


def _yaml_dquote_escape(value: str) -> str:
    """Escape a value for embedding inside a YAML double-quoted scalar.

    Most placeholders in the templates this system ships (dev-workflow.yaml)
    sit inside `"..."` in the raw template text (e.g. `"{{ .prompt }}"`), so
    this is applied unconditionally to every substituted value rather than
    trying to detect quoting context. A value with none of these characters
    passes through unchanged, so it's also safe for the rare unquoted
    placeholder (e.g. `max_iterations: {{ .max_loop_attempts }}`), as long as
    the substituted value itself contains none of these characters — true for
    the numeric default and for any sane override. Without this escaping, a
    prompt containing a `"` (e.g. `Fix the "TODO" in main.py`) would break the
    surrounding YAML string.
    """
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return value.replace("\t", "\\t")


def _substitute(text: str, resolved: dict[str, Any], template_name: str) -> str:
    def repl(match: re.Match) -> str:
        name = match.group("name")
        filt = match.group("filter")
        if name not in resolved:
            raise TemplateError(
                f"Template '{template_name}' references unknown parameter '{name}'"
            )
        value = str(resolved[name])
        if filt:
            fn = _FILTERS.get(filt)
            if fn is None:
                raise TemplateError(
                    f"Template '{template_name}' uses unknown filter '{filt}'"
                )
            value = fn(value)
        return _yaml_dquote_escape(value)

    return _PLACEHOLDER_RE.sub(repl, text)


def instantiate(template: TemplateDef, params: dict[str, str]) -> str:
    """Substitute parameters and return the instantiated `workflow:` YAML
    document (as text), ready to hand to Themis.validate().
    """
    resolved = _resolve_params(template, params)
    substituted = _substitute(template.raw_text, resolved, template.name)
    _, body_text = _split_header_body(substituted, template.name)
    try:
        body = yaml.safe_load(body_text)
    except yaml.YAMLError as exc:
        raise TemplateError(
            f"Template '{template.name}' produced invalid YAML after substitution: {exc}"
        ) from exc
    if not isinstance(body, dict) or "workflow" not in body:
        raise TemplateError(
            f"Template '{template.name}' body must contain a top-level 'workflow' key"
        )
    return yaml.safe_dump({"workflow": body["workflow"]}, sort_keys=False)
