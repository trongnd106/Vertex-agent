"""Tests for ``src.graph.channels`` — channel-based state management."""

import operator

import pytest

from src.graph.channels import (
    BinaryOperatorAggregate,
    EphemeralValue,
    LastValue,
    NamedBarrierValue,
    Topic,
    channel_for_field,
)


# ── LastValue ─────────────────────────────────────────────────────────


class TestLastValue:
    def test_initial_value_is_none(self):
        ch = LastValue()
        assert ch.value is None

    def test_initial_value_custom(self):
        ch = LastValue(initial=42)
        assert ch.value == 42

    def test_single_update(self):
        ch = LastValue()
        ch.update(["hello"])
        assert ch.value == "hello"

    def test_overwrite(self):
        ch = LastValue()
        ch.update(["first"])
        ch.update(["second"])
        assert ch.value == "second"

    def test_update_no_change(self):
        ch = LastValue(initial="same")
        assert ch.update(["same"]) is False  # No version bump

    def test_update_with_change(self):
        ch = LastValue(initial="old")
        assert ch.update(["new"]) is True  # Version bumped

    def test_empty_update(self):
        ch = LastValue(initial="val")
        assert ch.update([]) is False
        assert ch.value == "val"

    def test_multiple_updates_raises(self):
        ch = LastValue()
        with pytest.raises(ValueError, match="at most 1 update"):
            ch.update(["a", "b"])

    def test_checkpoint_roundtrip(self):
        ch = LastValue()
        ch.update(["stored"])
        snap = ch.checkpoint()
        ch2 = LastValue()
        ch2.from_checkpoint(snap)
        assert ch2.value == "stored"

    def test_reset(self):
        ch = LastValue(initial=0)
        ch.update([1])
        ch.reset()
        assert ch.value == 0

    def test_version_increases(self):
        ch = LastValue()
        v1 = ch._version
        ch.update(["a"])
        assert ch._version > v1


# ── BinaryOperatorAggregate ───────────────────────────────────────────


class TestBinaryOperatorAggregate:
    def test_add_reducer(self):
        ch = BinaryOperatorAggregate(reducer=operator.add, initial=0)
        ch.update([1])
        assert ch.value == 1
        ch.update([2])
        assert ch.value == 3

    def test_list_concat(self):
        ch = BinaryOperatorAggregate(reducer=operator.add, initial=[])
        ch.update([[1, 2]])
        assert ch.value == [1, 2]
        ch.update([[3]])
        assert ch.value == [1, 2, 3]

    def test_custom_reducer(self):
        def merge(a: dict, b: dict) -> dict:
            return {**a, **b}

        ch = BinaryOperatorAggregate(reducer=merge, initial={})
        ch.update([{"a": 1}])
        assert ch.value == {"a": 1}
        ch.update([{"b": 2}])
        assert ch.value == {"a": 1, "b": 2}

    def test_empty_update(self):
        ch = BinaryOperatorAggregate(reducer=operator.add, initial=5)
        assert ch.update([]) is False

    def test_checkpoint_roundtrip(self):
        ch = BinaryOperatorAggregate(reducer=operator.add, initial=0)
        ch.update([10])
        ch.update([5])
        snap = ch.checkpoint()
        ch2 = BinaryOperatorAggregate(reducer=operator.add)
        ch2.from_checkpoint(snap)
        assert ch2.value == 15

    def test_reset(self):
        ch = BinaryOperatorAggregate(reducer=operator.add, initial=0)
        ch.update([100])
        ch.reset()
        assert ch.value == 0


# ── Topic ─────────────────────────────────────────────────────────────


class TestTopic:
    def test_initial_empty(self):
        ch = Topic()
        assert ch.value == []

    def test_append(self):
        ch = Topic()
        ch.update(["a"])
        assert ch.value == ["a"]

    def test_multiple_appends(self):
        ch = Topic()
        ch.update(["a"])
        ch.update(["b", "c"])
        assert ch.value == ["a", "b", "c"]

    def test_batch_update(self):
        ch = Topic()
        ch.update([["a", "b", "c"]])
        assert ch.value == ["a", "b", "c"]

    def test_dedup_by_key(self):
        ch = Topic(unique_by=lambda x: x.id if hasattr(x, "id") else x)
        ch.update(["a"])
        ch.update(["a"])  # Duplicate — should be skipped
        assert ch.value == ["a"]

    def test_no_dedup_default(self):
        ch = Topic()
        ch.update(["a"])
        ch.update(["a"])  # No dedup by default
        assert ch.value == ["a", "a"]

    def test_checkpoint_roundtrip(self):
        ch = Topic()
        ch.update(["x", "y"])
        snap = ch.checkpoint()
        ch2 = Topic()
        ch2.from_checkpoint(snap)
        assert ch2.value == ["x", "y"]

    def test_reset(self):
        ch = Topic()
        ch.update(["a", "b"])
        ch.reset()
        assert ch.value == []


# ── EphemeralValue ────────────────────────────────────────────────────


class TestEphemeralValue:
    def test_initial_none(self):
        ch = EphemeralValue()
        assert ch.value is None

    def test_update(self):
        ch = EphemeralValue()
        ch.update(["temp"])
        assert ch.value == "temp"

    def test_last_wins(self):
        ch = EphemeralValue()
        ch.update(["a"])
        ch.update(["b"])
        assert ch.value == "b"

    def test_checkpoint_returns_none(self):
        ch = EphemeralValue()
        ch.update(["data"])
        assert ch.checkpoint() is None

    def test_reset_clears(self):
        ch = EphemeralValue()
        ch.update(["data"])
        ch.reset()
        assert ch.value is None


# ── NamedBarrierValue ─────────────────────────────────────────────────


class TestNamedBarrierValue:
    def test_not_triggered_initially(self):
        ch = NamedBarrierValue(expected_writers={"a", "b"})
        assert ch.value is False

    def test_triggered_when_all_arrive(self):
        ch = NamedBarrierValue(expected_writers={"a", "b"})
        ch.update(["a"])
        assert ch.value is False
        ch.update(["b"])
        assert ch.value is True

    def test_checkpoint_roundtrip(self):
        ch = NamedBarrierValue(expected_writers={"a", "b"})
        ch.update(["a"])
        snap = ch.checkpoint()
        ch2 = NamedBarrierValue(expected_writers={"a", "b"})
        ch2.from_checkpoint(snap)
        assert ch2.value is False
        ch2.update(["b"])
        assert ch2.value is True

    def test_reset(self):
        ch = NamedBarrierValue(expected_writers={"a", "b"})
        ch.update(["a", "b"])
        assert ch.value is True
        ch.reset()
        assert ch.value is False


# ── channel_for_field ─────────────────────────────────────────────────


class TestChannelForField:
    def test_plain_type_returns_last_value(self):
        ch = channel_for_field(str)
        assert isinstance(ch, LastValue)

    def test_list_type_returns_topic(self):
        ch = channel_for_field(list)
        assert isinstance(ch, Topic)

    def test_binop_reducer(self):
        ch = channel_for_field(operator.add)
        assert isinstance(ch, BinaryOperatorAggregate)

    def test_annotated_with_reducer(self):
        from typing import Annotated

        ch = channel_for_field(Annotated[int, operator.add])
        assert isinstance(ch, BinaryOperatorAggregate)

    def test_annotated_list(self):
        from typing import Annotated
        from src.graph.reducers import add_messages

        ch = channel_for_field(Annotated[list, add_messages])
        assert isinstance(ch, Topic)