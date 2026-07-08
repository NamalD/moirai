"""Themis — deterministic YAML validation + state machine generation.

GraphValidator (SPEC.md §6) is folded in as the internal
``Themis._graph_validator`` method rather than existing as a separate
component/file, per the v5 design decision.

See docs/architecture/initial-build/SPEC.md §5, §6, §7.2 for the
authoritative schema and validation rules.
"""

import re
from typing import Any, Optional

import yaml

from moirai.types import (
    AgentDef,
    LoopDef,
    StateMachine,
    TaskDef,
    ValidationError,
    ValidationResult,
)

_INPUT_REF_RE = re.compile(r"\{\{\s*\.inputs\.([A-Za-z0-9_]+)\s*\}\}")


class Themis:
    """Deterministic YAML validator and state machine generator."""

    def validate(
        self, yaml_artifact: str, known_agents: list[AgentDef]
    ) -> ValidationResult:
        errors: list[ValidationError] = []

        raw = self._parse_yaml(yaml_artifact, errors)
        if raw is None:
            return ValidationResult(state_machine=None, errors=errors, is_valid=False)

        wf = raw.get("workflow") if isinstance(raw, dict) else None
        if not isinstance(wf, dict):
            errors.append(
                ValidationError(
                    field="workflow",
                    message="Missing or invalid top-level 'workflow' key",
                    error_code="MISSING_WORKFLOW",
                )
            )
            return ValidationResult(state_machine=None, errors=errors, is_valid=False)

        self._validate_required_workflow_fields(wf, errors)

        # Agents may be declared inline (SPEC §5 schema) or resolved purely
        # from the external registry passed as `known_agents` — the actual
        # dev-workflow.yaml template in this repo has no embedded `agents:`
        # key at all and relies entirely on the registry, so an inline
        # `agents:` list is treated as optional/supplemental rather than
        # required, despite the schema table marking it required.
        agent_map: dict[str, AgentDef] = {a.id: a for a in known_agents}
        for raw_agent in wf.get("agents") or []:
            agent_def = self._parse_agent(raw_agent, errors)
            if agent_def is not None:
                agent_map[agent_def.id] = agent_def

        tasks: dict[str, TaskDef] = {}
        loop_tasks: dict[str, LoopDef] = {}
        raw_tasks = wf.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            errors.append(
                ValidationError(
                    field="workflow.tasks",
                    message="'workflow.tasks' must be a non-empty list",
                    error_code="MISSING_TASKS",
                )
            )
        else:
            for i, raw_task in enumerate(raw_tasks):
                field_prefix = f"workflow.tasks[{i}]"
                if not isinstance(raw_task, dict):
                    errors.append(
                        ValidationError(
                            field=field_prefix,
                            message="Task entry must be a mapping",
                            error_code="INVALID_TASK",
                        )
                    )
                    continue
                if raw_task.get("type") == "loop":
                    loop_def = self._parse_loop(raw_task, field_prefix, errors)
                    if loop_def is not None:
                        if loop_def.id in tasks or loop_def.id in loop_tasks:
                            errors.append(
                                ValidationError(
                                    field=f"{field_prefix}.id",
                                    message=f"Duplicate task id '{loop_def.id}'",
                                    error_code="DUPLICATE_TASK_ID",
                                    task_id=loop_def.id,
                                )
                            )
                        else:
                            loop_tasks[loop_def.id] = loop_def
                else:
                    task_def = self._parse_task(raw_task, field_prefix, errors)
                    if task_def is not None:
                        if task_def.id in tasks or task_def.id in loop_tasks:
                            errors.append(
                                ValidationError(
                                    field=f"{field_prefix}.id",
                                    message=f"Duplicate task id '{task_def.id}'",
                                    error_code="DUPLICATE_TASK_ID",
                                    task_id=task_def.id,
                                )
                            )
                        else:
                            tasks[task_def.id] = task_def

        if errors:
            return ValidationResult(state_machine=None, errors=errors, is_valid=False)

        self._validate_input_refs(tasks, loop_tasks, errors)

        state_machine, graph_errors = self._graph_validator(
            tasks=tasks,
            loop_tasks=loop_tasks,
            agent_map=agent_map,
            workflow_id=wf["id"],
            workflow_version=wf["version"],
        )
        errors.extend(graph_errors)

        if errors:
            return ValidationResult(state_machine=None, errors=errors, is_valid=False)

        return ValidationResult(state_machine=state_machine, errors=[], is_valid=True)

    # ─── YAML parsing & schema validation ──────────────────────────

    def _parse_yaml(
        self, yaml_artifact: str, errors: list[ValidationError]
    ) -> Optional[dict]:
        try:
            raw = yaml.safe_load(yaml_artifact)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            errors.append(
                ValidationError(
                    field="root",
                    message=f"YAML parse error: {exc}",
                    error_code="YAML_PARSE_ERROR",
                    yaml_line=(mark.line + 1) if mark is not None else None,
                )
            )
            return None
        if raw is None:
            errors.append(
                ValidationError(
                    field="root",
                    message="YAML document is empty",
                    error_code="EMPTY_DOCUMENT",
                )
            )
            return None
        return raw

    def _validate_required_workflow_fields(
        self, wf: dict, errors: list[ValidationError]
    ) -> None:
        for key, expected_type in (("id", str), ("name", str), ("version", int)):
            if key not in wf:
                errors.append(
                    ValidationError(
                        field=f"workflow.{key}",
                        message=f"'workflow.{key}' is required",
                        error_code="MISSING_FIELD",
                    )
                )
            elif not isinstance(wf[key], expected_type):
                errors.append(
                    ValidationError(
                        field=f"workflow.{key}",
                        message=f"'workflow.{key}' must be of type {expected_type.__name__}",
                        error_code="INVALID_FIELD_TYPE",
                    )
                )

    def _parse_agent(
        self, raw_agent: Any, errors: list[ValidationError]
    ) -> Optional[AgentDef]:
        if not isinstance(raw_agent, dict):
            errors.append(
                ValidationError(
                    field="workflow.agents[]",
                    message="Agent entry must be a mapping",
                    error_code="INVALID_AGENT",
                )
            )
            return None
        for key in ("id", "name", "command"):
            if key not in raw_agent:
                errors.append(
                    ValidationError(
                        field=f"workflow.agents[].{key}",
                        message=f"Agent '{key}' is required",
                        error_code="MISSING_FIELD",
                    )
                )
        if any(e.error_code == "MISSING_FIELD" for e in errors[-3:]):
            return None
        return AgentDef(
            id=raw_agent["id"], name=raw_agent["name"], command=raw_agent["command"]
        )

    def _parse_task(
        self, raw_task: dict, field_prefix: str, errors: list[ValidationError]
    ) -> Optional[TaskDef]:
        required_ok = True
        for key in ("id", "agent", "command"):
            if key not in raw_task:
                errors.append(
                    ValidationError(
                        field=f"{field_prefix}.{key}",
                        message=f"'{key}' is required",
                        error_code="MISSING_FIELD",
                    )
                )
                required_ok = False
        if not required_ok:
            return None

        command = raw_task["command"]
        if not isinstance(command, str) or not command.strip():
            errors.append(
                ValidationError(
                    field=f"{field_prefix}.command",
                    message="'command' must be a non-empty string",
                    error_code="INVALID_COMMAND",
                    task_id=raw_task.get("id"),
                )
            )
            return None

        deps = raw_task.get("deps", raw_task.get("depends_on", []))
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            errors.append(
                ValidationError(
                    field=f"{field_prefix}.deps",
                    message="'deps' must be a list of task id strings",
                    error_code="INVALID_DEPS",
                    task_id=raw_task.get("id"),
                )
            )
            return None

        return TaskDef(
            id=raw_task["id"],
            agent=raw_task["agent"],
            command=command,
            type=raw_task.get("type", "agent"),
            deps=list(deps),
            timeout=raw_task.get("timeout", 3600),
            max_retries=raw_task.get("max_retries", 3),
            inputs=dict(raw_task.get("inputs", {}) or {}),
        )

    def _parse_loop(
        self, raw_loop: dict, field_prefix: str, errors: list[ValidationError]
    ) -> Optional[LoopDef]:
        if "id" not in raw_loop:
            errors.append(
                ValidationError(
                    field=f"{field_prefix}.id",
                    message="'id' is required",
                    error_code="MISSING_FIELD",
                )
            )
            return None

        raw_steps = raw_loop.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            errors.append(
                ValidationError(
                    field=f"{field_prefix}.steps",
                    message="loop 'steps' must be a non-empty list",
                    error_code="MISSING_LOOP_STEPS",
                    task_id=raw_loop.get("id"),
                )
            )
            return None

        inner_steps: list[TaskDef] = []
        seen_ids: set[str] = set()
        for j, raw_step in enumerate(raw_steps):
            step_prefix = f"{field_prefix}.steps[{j}]"
            if not isinstance(raw_step, dict):
                errors.append(
                    ValidationError(
                        field=step_prefix,
                        message="Inner step entry must be a mapping",
                        error_code="INVALID_TASK",
                    )
                )
                continue
            step_def = self._parse_task(raw_step, step_prefix, errors)
            if step_def is not None:
                if step_def.id in seen_ids:
                    errors.append(
                        ValidationError(
                            field=f"{step_prefix}.id",
                            message=f"Duplicate inner step id '{step_def.id}'",
                            error_code="DUPLICATE_TASK_ID",
                            task_id=step_def.id,
                        )
                    )
                else:
                    seen_ids.add(step_def.id)
                    inner_steps.append(step_def)

        max_iterations = raw_loop.get("max_iterations", 5)
        if not isinstance(max_iterations, int) or max_iterations < 1:
            errors.append(
                ValidationError(
                    field=f"{field_prefix}.max_iterations",
                    message="'max_iterations' must be a positive integer",
                    error_code="INVALID_MAX_ITERATIONS",
                    task_id=raw_loop.get("id"),
                )
            )

        deps = raw_loop.get("deps", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            errors.append(
                ValidationError(
                    field=f"{field_prefix}.deps",
                    message="'deps' must be a list of task id strings",
                    error_code="INVALID_DEPS",
                    task_id=raw_loop.get("id"),
                )
            )
            deps = []

        return LoopDef(
            id=raw_loop["id"],
            max_iterations=max_iterations if isinstance(max_iterations, int) else 5,
            terminate_on=raw_loop.get("terminate_on", ""),
            deps=list(deps),
            inner_steps=inner_steps,
            loop_timeout=raw_loop.get("loop_timeout"),
            max_concurrent_inner=raw_loop.get("max_concurrent_inner", 1),
        )

    def _validate_input_refs(
        self,
        tasks: dict[str, TaskDef],
        loop_tasks: dict[str, LoopDef],
        errors: list[ValidationError],
    ) -> None:
        def check(task: TaskDef, field: str) -> None:
            for ref in _INPUT_REF_RE.findall(task.command):
                if ref not in task.inputs:
                    errors.append(
                        ValidationError(
                            field=field,
                            message=(
                                f"command references '{{{{ .inputs.{ref} }}}}' "
                                f"but no matching key in 'inputs'"
                            ),
                            error_code="UNKNOWN_INPUT_REF",
                            task_id=task.id,
                        )
                    )

        for task_id, task in tasks.items():
            check(task, f"tasks.{task_id}.command")
        for loop_id, loop_def in loop_tasks.items():
            for step in loop_def.inner_steps:
                check(step, f"tasks.{loop_id}.steps.{step.id}.command")

    # ─── GraphValidator — deterministic structural validation (§6) ──

    def _graph_validator(
        self,
        tasks: dict[str, TaskDef],
        loop_tasks: dict[str, LoopDef],
        agent_map: dict[str, AgentDef],
        workflow_id: str,
        workflow_version: int,
    ) -> tuple[Optional[StateMachine], list[ValidationError]]:
        errors: list[ValidationError] = []
        all_ids = set(tasks) | set(loop_tasks)

        # Outer dependency map — loop steps are opaque single nodes; their
        # inner_steps are never included here, so outer acyclicity checks
        # cannot see (or be tripped up by) inner-loop structure.
        dependencies: dict[str, list[str]] = {}
        for task_id, task in tasks.items():
            dependencies[task_id] = list(task.deps)
        for loop_id, loop_def in loop_tasks.items():
            dependencies[loop_id] = list(loop_def.deps)

        # Task reference validity (outer) + self-loop + duplicate-dep checks.
        for task_id, deps in dependencies.items():
            if task_id in deps:
                errors.append(
                    ValidationError(
                        field=f"tasks.{task_id}.deps",
                        message=f"Task '{task_id}' cannot depend on itself",
                        error_code="SELF_LOOP",
                        task_id=task_id,
                    )
                )
            if len(deps) != len(set(deps)):
                errors.append(
                    ValidationError(
                        field=f"tasks.{task_id}.deps",
                        message=f"Task '{task_id}' has duplicate entries in 'deps'",
                        error_code="DUPLICATE_DEP",
                        task_id=task_id,
                    )
                )
            for dep in deps:
                if dep not in all_ids:
                    errors.append(
                        ValidationError(
                            field=f"tasks.{task_id}.deps",
                            message=f"Task '{task_id}' depends on unknown task '{dep}'",
                            error_code="UNKNOWN_DEP",
                            task_id=task_id,
                        )
                    )

        # Agent reference validity (outer tasks + loop inner steps).
        for task_id, task in tasks.items():
            if task.agent not in agent_map:
                errors.append(
                    ValidationError(
                        field=f"tasks.{task_id}.agent",
                        message=f"Task '{task_id}' references unknown agent '{task.agent}'",
                        error_code="UNKNOWN_AGENT",
                        task_id=task_id,
                    )
                )
        for loop_id, loop_def in loop_tasks.items():
            for step in loop_def.inner_steps:
                if step.agent not in agent_map:
                    errors.append(
                        ValidationError(
                            field=f"tasks.{loop_id}.steps.{step.id}.agent",
                            message=f"Inner step '{step.id}' references unknown agent '{step.agent}'",
                            error_code="UNKNOWN_AGENT",
                            task_id=step.id,
                        )
                    )

        # Loop step inner validation: scoping, connectivity.
        for loop_id, loop_def in loop_tasks.items():
            inner_ids = {s.id for s in loop_def.inner_steps}
            for step in loop_def.inner_steps:
                for dep in step.deps:
                    if dep not in inner_ids:
                        errors.append(
                            ValidationError(
                                field=f"tasks.{loop_id}.steps.{step.id}.deps",
                                message=(
                                    f"Inner step '{step.id}' depends on '{dep}', which is "
                                    f"not an inner step of loop '{loop_id}' "
                                    f"(cross-boundary dependencies are not allowed)"
                                ),
                                error_code="CROSS_BOUNDARY_DEP",
                                task_id=step.id,
                            )
                        )
            inner_errors = self._check_connectivity(
                node_ids=inner_ids,
                deps_of={s.id: s.deps for s in loop_def.inner_steps},
                scope=f"tasks.{loop_id}.steps",
            )
            errors.extend(inner_errors)

        if errors:
            return None, errors

        # Outer acyclicity (DFS, three-color) + topological order.
        cycle_errors, topo_order = self._detect_cycle_and_topo_sort(
            all_ids, dependencies
        )
        errors.extend(cycle_errors)
        if errors:
            return None, errors

        # Entry points + orphan / single-root check (outer graph).
        entry_points = [tid for tid in all_ids if not dependencies[tid]]
        connectivity_errors = self._check_connectivity(
            node_ids=all_ids, deps_of=dependencies, scope="workflow"
        )
        errors.extend(connectivity_errors)
        if errors:
            return None, errors

        state_machine = StateMachine(
            workflow_id=workflow_id,
            version=workflow_version,
            tasks=tasks,
            loop_tasks=loop_tasks,
            dependencies=dependencies,
            entry_points=entry_points,
        )
        return state_machine, []

    def _check_connectivity(
        self,
        node_ids: set[str],
        deps_of: dict[str, list[str]],
        scope: str,
    ) -> list[ValidationError]:
        """Every node must be reachable from some zero-dependency entry point."""
        errors: list[ValidationError] = []
        if not node_ids:
            return errors

        entry_points = [nid for nid in node_ids if not deps_of.get(nid)]
        if not entry_points:
            errors.append(
                ValidationError(
                    field=scope,
                    message=f"No entry point found in '{scope}' (every node has a dependency)",
                    error_code="NO_ENTRY_POINT",
                )
            )
            return errors

        # dependents[x] = nodes that depend on x, i.e. forward edges.
        dependents: dict[str, list[str]] = {nid: [] for nid in node_ids}
        for nid, deps in deps_of.items():
            for dep in deps:
                if dep in dependents:
                    dependents[dep].append(nid)

        reached: set[str] = set()
        stack = list(entry_points)
        while stack:
            current = stack.pop()
            if current in reached:
                continue
            reached.add(current)
            stack.extend(dependents.get(current, []))

        for nid in node_ids:
            if nid not in reached:
                errors.append(
                    ValidationError(
                        field=scope,
                        message=f"Task '{nid}' is not reachable from any entry point (orphan)",
                        error_code="ORPHAN_TASK",
                        task_id=nid,
                    )
                )
        return errors

    def _detect_cycle_and_topo_sort(
        self, node_ids: set[str], deps_of: dict[str, list[str]]
    ) -> tuple[list[ValidationError], list[str]]:
        """DFS-based cycle detection (back-edge check) + topological sort."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in node_ids}
        topo_order: list[str] = []
        errors: list[ValidationError] = []
        path: list[str] = []

        def visit(node: str) -> bool:
            color[node] = GRAY
            path.append(node)
            for dep in deps_of.get(node, []):
                if dep not in color:
                    continue  # unknown dep already reported elsewhere
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    errors.append(
                        ValidationError(
                            field="workflow.tasks",
                            message=f"Cycle detected: {' -> '.join(cycle)}",
                            error_code="CYCLE_DETECTED",
                        )
                    )
                    path.pop()
                    color[node] = BLACK
                    return False
                if color[dep] == WHITE:
                    if not visit(dep):
                        path.pop()
                        color[node] = BLACK
                        return False
            path.pop()
            color[node] = BLACK
            topo_order.append(node)
            return True

        for node in node_ids:
            if color[node] == WHITE:
                if not visit(node):
                    break

        return errors, topo_order
