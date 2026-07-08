"""Tests for Themis + internal GraphValidator (SPEC.md §6, §7.2, §19.1)."""

import pytest

from moirai.themis import Themis
from moirai.types import AgentDef

AGENTS = [
    AgentDef(id="agent-a", name="Agent A", command="/bin/true"),
    AgentDef(id="agent-b", name="Agent B", command="/bin/true"),
]


def _wrap(tasks_yaml: str, workflow_id: str = "wf-1") -> str:
    return f"""
workflow:
  id: "{workflow_id}"
  name: "Test workflow"
  version: 1
  tasks:
{tasks_yaml}
"""


def validate(yaml_str: str, agents=AGENTS):
    return Themis().validate(yaml_str, agents)


# ─── Happy path ─────────────────────────────────────────────────────


def test_single_node_workflow_is_valid():
    yaml_str = _wrap(
        """
    - id: "solo"
      agent: "agent-a"
      command: "echo hi"
      deps: []
"""
    )
    result = validate(yaml_str)
    assert result.is_valid, result.errors
    assert result.state_machine.entry_points == ["solo"]
    assert result.state_machine.dependencies == {"solo": []}


def test_diamond_dag_is_valid():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: []
    - id: "b"
      agent: "agent-a"
      command: "echo b"
      deps: ["a"]
    - id: "c"
      agent: "agent-a"
      command: "echo c"
      deps: ["a"]
    - id: "d"
      agent: "agent-a"
      command: "echo d"
      deps: ["b", "c"]
"""
    )
    result = validate(yaml_str)
    assert result.is_valid, result.errors
    sm = result.state_machine
    assert sm.entry_points == ["a"]
    topo_positions = {}
    # Reconstruct a valid order check: every dep must be resolvable before dependent.
    # We don't expose topo_order directly on StateMachine, so just check dependency
    # integrity here instead.
    assert set(sm.tasks) == {"a", "b", "c", "d"}
    assert sm.dependencies["d"] == ["b", "c"]


def test_disconnected_components_both_valid():
    yaml_str = _wrap(
        """
    - id: "a1"
      agent: "agent-a"
      command: "echo a1"
      deps: []
    - id: "a2"
      agent: "agent-a"
      command: "echo a2"
      deps: ["a1"]
    - id: "b1"
      agent: "agent-a"
      command: "echo b1"
      deps: []
    - id: "b2"
      agent: "agent-a"
      command: "echo b2"
      deps: ["b1"]
"""
    )
    result = validate(yaml_str)
    assert result.is_valid, result.errors
    assert set(result.state_machine.entry_points) == {"a1", "b1"}


# ─── Structural failures ────────────────────────────────────────────


def test_empty_tasks_list_is_invalid():
    result = validate(
        """
workflow:
  id: "wf-empty"
  name: "Empty"
  version: 1
  tasks: []
"""
    )
    assert not result.is_valid
    assert any(e.error_code == "MISSING_TASKS" for e in result.errors)


def test_cyclic_graph_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: ["c"]
    - id: "b"
      agent: "agent-a"
      command: "echo b"
      deps: ["a"]
    - id: "c"
      agent: "agent-a"
      command: "echo c"
      deps: ["b"]
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "CYCLE_DETECTED" for e in result.errors)


def test_self_loop_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: ["a"]
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "SELF_LOOP" for e in result.errors)


def test_unknown_dependency_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: ["ghost"]
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "UNKNOWN_DEP" for e in result.errors)


def test_unknown_agent_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "no-such-agent"
      command: "echo a"
      deps: []
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "UNKNOWN_AGENT" for e in result.errors)


def test_duplicate_task_id_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: []
    - id: "a"
      agent: "agent-a"
      command: "echo a again"
      deps: []
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "DUPLICATE_TASK_ID" for e in result.errors)


def test_unknown_input_ref_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo {{ .inputs.missing }}"
      deps: []
      inputs:
        present: "value"
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "UNKNOWN_INPUT_REF" for e in result.errors)


def test_malformed_yaml_is_rejected():
    result = validate("workflow: [this is not, a valid mapping")
    assert not result.is_valid
    assert any(e.error_code == "YAML_PARSE_ERROR" for e in result.errors)


# ─── Loop step opaqueness invariants (§6, §19.1) ────────────────────


def test_loop_with_inner_deps_is_valid():
    yaml_str = _wrap(
        """
    - id: "setup"
      agent: "agent-a"
      command: "echo setup"
      deps: []
    - id: "feature-work"
      type: loop
      max_iterations: 5
      terminate_on: "APPROVED"
      deps: ["setup"]
      steps:
        - id: "implement"
          agent: "agent-a"
          command: "echo implement"
          deps: []
        - id: "review"
          agent: "agent-b"
          command: "echo review"
          deps: ["implement"]
"""
    )
    result = validate(yaml_str)
    assert result.is_valid, result.errors
    sm = result.state_machine
    assert "feature-work" in sm.loop_tasks
    assert sm.loop_tasks["feature-work"].inner_steps[0].id == "implement"


def test_outer_cycle_through_loop_step_is_detected():
    """outer A -> loop L -> outer B, where B (transitively) feeds back into A."""
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: ["b"]
    - id: "loop-l"
      type: loop
      deps: ["a"]
      terminate_on: "DONE"
      steps:
        - id: "inner"
          agent: "agent-a"
          command: "echo inner"
          deps: []
    - id: "b"
      agent: "agent-a"
      command: "echo b"
      deps: ["loop-l"]
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "CYCLE_DETECTED" for e in result.errors)


def test_inner_cycle_does_not_trip_outer_acyclicity():
    """Inner step cycle (x -> y -> x) must NOT be flagged as an outer cycle.

    Themis's own connectivity check on the inner sub-graph will still catch
    the unreachable inner step, since GraphValidator requires the inner
    sub-graph to be connected/reachable from an inner entry point — but the
    key invariant under test is that this never surfaces as CYCLE_DETECTED
    on the *outer* graph.
    """
    yaml_str = _wrap(
        """
    - id: "loop-l"
      type: loop
      deps: []
      terminate_on: "DONE"
      steps:
        - id: "x"
          agent: "agent-a"
          command: "echo x"
          deps: ["y"]
        - id: "y"
          agent: "agent-a"
          command: "echo y"
          deps: ["x"]
"""
    )
    result = validate(yaml_str)
    assert not any(e.error_code == "CYCLE_DETECTED" for e in result.errors)


def test_cross_boundary_dependency_outer_to_inner_is_rejected():
    yaml_str = _wrap(
        """
    - id: "loop-l"
      type: loop
      deps: []
      terminate_on: "DONE"
      steps:
        - id: "inner"
          agent: "agent-a"
          command: "echo inner"
          deps: []
    - id: "b"
      agent: "agent-a"
      command: "echo b"
      deps: ["inner"]
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "UNKNOWN_DEP" for e in result.errors)


def test_cross_boundary_dependency_inner_to_outer_is_rejected():
    yaml_str = _wrap(
        """
    - id: "a"
      agent: "agent-a"
      command: "echo a"
      deps: []
    - id: "loop-l"
      type: loop
      deps: []
      terminate_on: "DONE"
      steps:
        - id: "inner"
          agent: "agent-a"
          command: "echo inner"
          deps: ["a"]
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "CROSS_BOUNDARY_DEP" for e in result.errors)


def test_loop_with_no_steps_is_rejected():
    yaml_str = _wrap(
        """
    - id: "loop-l"
      type: loop
      deps: []
      terminate_on: "DONE"
      steps: []
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "MISSING_LOOP_STEPS" for e in result.errors)


def test_loop_with_non_positive_max_iterations_is_rejected():
    yaml_str = _wrap(
        """
    - id: "loop-l"
      type: loop
      deps: []
      max_iterations: 0
      terminate_on: "DONE"
      steps:
        - id: "inner"
          agent: "agent-a"
          command: "echo inner"
          deps: []
"""
    )
    result = validate(yaml_str)
    assert not result.is_valid
    assert any(e.error_code == "INVALID_MAX_ITERATIONS" for e in result.errors)


def test_loop_counter_controlled_empty_terminate_on_is_valid():
    yaml_str = _wrap(
        """
    - id: "loop-l"
      type: loop
      deps: []
      max_iterations: 3
      terminate_on: ""
      steps:
        - id: "inner"
          agent: "agent-a"
          command: "echo inner"
          deps: []
"""
    )
    result = validate(yaml_str)
    assert result.is_valid, result.errors


def test_inline_agents_are_merged_with_registry():
    yaml_str = """
workflow:
  id: "wf-inline"
  name: "Inline agents"
  version: 1
  agents:
    - id: "inline-agent"
      name: "Inline"
      command: "/bin/true"
  tasks:
    - id: "a"
      agent: "inline-agent"
      command: "echo a"
      deps: []
"""
    result = Themis().validate(yaml_str, known_agents=[])
    assert result.is_valid, result.errors
