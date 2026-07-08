"""Moirai CLI — argparse-based command surface (SPEC.md §7.8).

Out of scope for Phase 6 (left as NotImplementedError stubs, matching the
precedent set by Lachesis's old Phase-3 loop_tasks guard — reject clearly
up front rather than inventing behavior for something that isn't built yet):

- `run --prompt` with no `--template`/`--yaml` (ad-hoc generation needs
  Clotho, which is still stubbed until Phase 8).
- `status`, `cancel`, `list jobs` (need durable cross-process persistence;
  the MVP only has MemoryBackend, which is in-process and non-durable —
  file-based persistence is post-MVP, SPEC.md §18).
- `create template`, `update`, `--dump-config` (need moirai/config.py,
  which doesn't exist yet).
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

import yaml

from moirai.atropos import Atropos
from moirai.lachesis import Lachesis
from moirai.persistence import MemoryBackend
from moirai.process_manager import SubprocessProcessManager
from moirai.templates import TemplateError, instantiate, list_templates, load_template
from moirai.themis import Themis
from moirai.time_provider import SystemTimeProvider
from moirai.types import AgentDef, ExecutionLog, StateMachine

_BUILTIN_AGENTS_PATH = Path(__file__).parent / "defaults" / "agents.yaml"


class StderrHumanNotifier:
    """Prints intervention requests to stderr.

    Not a real notification channel — there is no decision-file poll loop
    here (that's out of scope for the MVP CLI); a human watching the CLI's
    stderr is the only consumer. poll_decision() always returns None (no
    decision ever arrives), which Lachesis never calls in the code paths
    this CLI exercises.
    """

    def __init__(self) -> None:
        self._count = 0

    def request_intervention(
        self,
        workflow_id: str,
        task_id: Optional[str],
        reason: str,
        logs: Optional[str] = None,
    ) -> str:
        self._count += 1
        request_id = f"cli-req-{self._count}"
        message = f"[HUMAN INTERVENTION REQUIRED] workflow={workflow_id} task={task_id} reason={reason}"
        if logs:
            message += f" logs={logs}"
        print(message, file=sys.stderr)
        return request_id

    def poll_decision(self, request_id: str, timeout_seconds: float = 86400.0):
        return None

    def cancel_request(self, request_id: str) -> None:
        pass


# ─── Agent registry loading (SPEC.md §8) ─────────────────────────────


def _resolve_agents_config_path() -> Path:
    env_path = os.environ.get("MOIRAI_AGENTS_CONFIG")
    if env_path:
        return Path(env_path)
    user_path = Path.home() / ".moirai" / "agents.yaml"
    if user_path.is_file():
        return user_path
    return _BUILTIN_AGENTS_PATH


def load_agent_registry(project_dir: str) -> dict[str, AgentDef]:
    """Load the agent registry and resolve each agent's `{{project}}`
    work_dir placeholder against the target project directory.

    This is a distinct, simpler placeholder syntax from templates.py's
    Go-style `{{ .param }}` — agents.yaml uses a bare `{{project}}` token,
    so a plain string replace is all that's needed.
    """
    path = _resolve_agents_config_path()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    agents: dict[str, AgentDef] = {}
    for raw_agent in raw.get("agents") or []:
        work_dir = raw_agent.get("work_dir")
        if work_dir:
            work_dir = work_dir.replace("{{project}}", project_dir)
        agents[raw_agent["id"]] = AgentDef(
            id=raw_agent["id"],
            name=raw_agent.get("name", raw_agent["id"]),
            command=raw_agent["command"],
            work_dir=work_dir,
            max_concurrent_tasks=raw_agent.get("max_concurrent_tasks", 1),
            tags=list(raw_agent.get("tags") or []),
        )
    return agents


# ─── run ──────────────────────────────────────────────────────────────


def _parse_param_args(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise TemplateError(f"--param must be in key=value form, got: {pair!r}")
        key, _, value = pair.partition("=")
        params[key] = value
    return params


def cmd_run(args: argparse.Namespace) -> int:
    if args.template and args.yaml:
        print("error: --template and --yaml are mutually exclusive", file=sys.stderr)
        return 2

    if args.yaml:
        try:
            with open(args.yaml) as f:
                yaml_text = f.read()
        except OSError as exc:
            print(f"error: could not read --yaml file: {exc}", file=sys.stderr)
            return 2
    elif args.template:
        try:
            params = _parse_param_args(args.param)
            params.setdefault("project", args.project)
            if args.prompt is not None:
                params.setdefault("prompt", args.prompt)
            template = load_template(args.template, project_dir=args.project)
            yaml_text = instantiate(template, params)
        except (TemplateError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    elif args.prompt:
        raise NotImplementedError(
            "ad-hoc `moirai run --prompt` (no --template/--yaml) requires Clotho "
            "to generate a YAML workflow from a natural-language prompt; Clotho "
            "is stubbed until Phase 8 (SPEC.md §7.1)"
        )
    else:
        print("error: one of --template, --yaml, or --prompt is required", file=sys.stderr)
        return 2

    return _validate_and_execute(yaml_text, project_dir=args.project, review=args.review)


def _validate_and_execute(yaml_text: str, project_dir: str, review: bool) -> int:
    agents = load_agent_registry(project_dir)

    validation = Themis().validate(yaml_text, list(agents.values()))
    if not validation.is_valid:
        print("Workflow validation failed:", file=sys.stderr)
        for err in validation.errors:
            print(f"  [{err.error_code}] {err.field}: {err.message}", file=sys.stderr)
        return 1

    sm = validation.state_machine
    if review:
        _print_review(sm)
        return 0

    return _execute(sm, agents, project_dir)


def _print_review(sm: StateMachine) -> None:
    print(f"Workflow: {sm.workflow_id} (v{sm.version})")
    print(f"Entry points: {', '.join(sm.entry_points) or '(none)'}")
    print()
    print("Tasks:")
    for task_id, task in sm.tasks.items():
        deps = ", ".join(sm.dependencies.get(task_id, [])) or "(none)"
        print(f"  - {task_id}  agent={task.agent}  deps=[{deps}]")
        print(f"      command: {task.command}")
    if sm.loop_tasks:
        print()
        print("Loop steps:")
        for task_id, loop_def in sm.loop_tasks.items():
            deps = ", ".join(sm.dependencies.get(task_id, [])) or "(none)"
            print(
                f"  - {task_id}  deps=[{deps}]  max_iterations={loop_def.max_iterations}"
                f"  terminate_on={loop_def.terminate_on!r}"
            )
            for step in loop_def.inner_steps:
                step_deps = ", ".join(step.deps) or "(none)"
                print(f"      * {step.id}  agent={step.agent}  deps=[{step_deps}]")


def _execute(sm: StateMachine, agents: dict[str, AgentDef], project_dir: str) -> int:
    persistence = MemoryBackend()
    process_manager = SubprocessProcessManager()
    time_provider = SystemTimeProvider()
    human_notifier = StderrHumanNotifier()
    atropos = Atropos(
        workflow_id=sm.workflow_id,
        process_manager=process_manager,
        human_notifier=human_notifier,
        time_provider=time_provider,
    )
    lachesis = Lachesis(
        state_machine=sm,
        persistence=persistence,
        process_manager=process_manager,
        atropos=atropos,
        human_notifier=human_notifier,
        time_provider=time_provider,
        agents=agents,
        default_work_dir=project_dir,
    )
    lachesis.install_signal_handlers()
    log = lachesis.run()
    _print_execution_result(log)
    return 0 if log.outcome == "success" else 1


def _print_execution_result(log: ExecutionLog) -> None:
    print(f"\nWorkflow {log.workflow_id}: {log.outcome}")
    for task_id, state in log.tasks.items():
        line = f"  - {task_id}: {state.status.name}"
        if state.error_message:
            line += f"  ({state.error_message})"
        print(line)


# ─── list templates / list jobs ──────────────────────────────────────


def cmd_list_templates(args: argparse.Namespace) -> int:
    templates = list_templates(project_dir=args.project)
    if not templates:
        print("No templates found.")
        return 0
    for template in templates:
        print(f"{template.name}: {template.description}")
    return 0


def cmd_list_jobs(args: argparse.Namespace) -> int:
    raise NotImplementedError(
        "`moirai list jobs` requires durable cross-process persistence to see "
        "workflows started by other invocations; the MVP only has MemoryBackend "
        "(in-process, non-durable) — file-based persistence is post-MVP (SPEC.md §18)"
    )


# ─── status / cancel / update / create template / --dump-config ─────


def cmd_status(args: argparse.Namespace) -> int:
    raise NotImplementedError(
        "`moirai status` requires durable cross-process persistence to look up a "
        "workflow started by another invocation — file-based persistence is "
        "post-MVP (SPEC.md §18)"
    )


def cmd_cancel(args: argparse.Namespace) -> int:
    raise NotImplementedError(
        "`moirai cancel` requires durable cross-process persistence to find and "
        "signal a running workflow's Lachesis instance from a separate CLI "
        "invocation — file-based persistence is post-MVP (SPEC.md §18)"
    )


def cmd_create_template(args: argparse.Namespace) -> int:
    raise NotImplementedError(
        "`moirai create template` needs moirai/config.py (template registration, "
        "storage path resolution), which doesn't exist yet"
    )


def cmd_update(args: argparse.Namespace) -> int:
    raise NotImplementedError(
        "`moirai update` (mid-flight YAML change) is explicitly future work per "
        "SPEC.md §7.8's command table"
    )


# ─── argument parsing ─────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moirai", description="Turn a natural-language prompt into a validated task DAG."
    )
    parser.add_argument(
        "--dump-config", action="store_true", help="Print resolved configuration and exit"
    )
    subparsers = parser.add_subparsers(dest="command")

    run_p = subparsers.add_parser("run", help="Run a workflow")
    run_p.add_argument("--template", help="Name of a template workflow to use")
    run_p.add_argument("--yaml", help="Path to a pre-existing YAML workflow file")
    run_p.add_argument("--prompt", help="Natural-language prompt describing the workflow")
    run_p.add_argument("--project", default=".", help="Target project directory")
    run_p.add_argument(
        "--param", action="append", default=[], metavar="KEY=VALUE", help="Template parameter"
    )
    run_p.add_argument(
        "--review", action="store_true", help="Show the parsed workflow and exit without executing"
    )
    run_p.add_argument("--verbose", action="store_true")
    run_p.add_argument("--debug", action="store_true")
    run_p.set_defaults(func=cmd_run)

    list_p = subparsers.add_parser("list", help="List templates or jobs")
    list_sub = list_p.add_subparsers(dest="target", required=True)
    list_templates_p = list_sub.add_parser("templates", help="List available templates")
    list_templates_p.add_argument("--project", default=".", help="Target project directory")
    list_templates_p.set_defaults(func=cmd_list_templates)
    list_jobs_p = list_sub.add_parser("jobs", help="List running/completed workflows")
    list_jobs_p.set_defaults(func=cmd_list_jobs)

    create_p = subparsers.add_parser("create", help="Create a template")
    create_sub = create_p.add_subparsers(dest="target", required=True)
    create_template_p = create_sub.add_parser("template", help="Register a new template")
    create_template_p.add_argument("name")
    create_template_p.add_argument("--file", help="Path to an existing YAML file")
    create_template_p.add_argument("--from-workflow", help="Save an executed workflow as a template")
    create_template_p.set_defaults(func=cmd_create_template)

    status_p = subparsers.add_parser("status", help="View state machine for a workflow")
    status_p.add_argument("workflow_id")
    status_p.set_defaults(func=cmd_status)

    cancel_p = subparsers.add_parser("cancel", help="Cancel a running workflow")
    cancel_p.add_argument("workflow_id")
    cancel_p.set_defaults(func=cmd_cancel)

    update_p = subparsers.add_parser("update", help="Trigger a mid-flight YAML change")
    update_p.add_argument("workflow_id")
    update_p.add_argument("--prompt")
    update_p.set_defaults(func=cmd_update)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dump_config:
        raise NotImplementedError(
            "--dump-config needs moirai/config.py (resolved configuration loading), "
            "which doesn't exist yet"
        )

    if not getattr(args, "command", None):
        parser.print_help()
        return 2

    return args.func(args)
