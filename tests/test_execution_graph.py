"""Tests for ExecutionGraph DAG construction and cycle detection."""
from __future__ import annotations

import pytest

from loom.brain_harness.hand_plan import AtomicTask, ExecutionGraph


def make_task(tid, depends_on=None, priority=0):
    return AtomicTask(
        task_id=tid,
        hand_id=f"hand-{tid}",
        task=f"task {tid}",
        depends_on=depends_on or [],
        priority=priority,
    )


class TestExecutionGraph:
    def test_empty_graph(self):
        g = ExecutionGraph.build([], "sha256:abc")
        assert g.tasks == ()
        assert g.roots == frozenset()

    def test_single_task_is_root(self):
        t = make_task("a")
        g = ExecutionGraph.build([t], "sha256:abc")
        assert "a" in g.roots
        assert g.adjacency["a"] == frozenset()

    def test_chain_dependency(self):
        # a -> b -> c
        a, b, c = make_task("a"), make_task("b", ["a"]), make_task("c", ["b"])
        g = ExecutionGraph.build([a, b, c], "sha256:abc")
        assert g.roots == frozenset({"a"})
        assert "b" in g.adjacency["a"]
        assert "c" in g.adjacency["b"]
        assert g.reverse_adjacency["b"] == frozenset({"a"})

    def test_parallel_tasks_both_roots(self):
        a, b = make_task("a"), make_task("b")
        g = ExecutionGraph.build([a, b], "sha256:abc")
        assert g.roots == frozenset({"a", "b"})

    def test_cycle_raises_value_error(self):
        a = make_task("a", ["b"])
        b = make_task("b", ["a"])
        with pytest.raises(ValueError, match="cycle"):
            ExecutionGraph.build([a, b], "sha256:abc")

    def test_self_loop_raises_value_error(self):
        a = make_task("a", ["a"])
        with pytest.raises(ValueError, match="cycle"):
            ExecutionGraph.build([a], "sha256:abc")

    def test_tasks_are_immutable_tuple(self):
        t = make_task("a")
        g = ExecutionGraph.build([t], "sha256:abc")
        assert isinstance(g.tasks, tuple)

    def test_projection_content_id_stored(self):
        t = make_task("a")
        g = ExecutionGraph.build([t], "sha256:deadbeef1234")
        assert g.projection_content_id == "sha256:deadbeef1234"
