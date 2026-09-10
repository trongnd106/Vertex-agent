"""Tests for ``src.graph.reducers`` — reducer functions."""

from langchain_core.messages import AIMessage, HumanMessage

from src.graph.reducers import add_messages, concat


class TestAddMessages:
    def test_merge_two_lists(self):
        """Two message lists merge correctly."""
        left = [HumanMessage(content="hello", id="1")]
        right = [AIMessage(content="world", id="2")]
        merged = add_messages(left, right)
        assert len(merged) == 2
        assert merged[0].content == "hello"
        assert merged[1].content == "world"

    def test_dedup_by_id(self):
        """Messages with same ID overwrite (last wins)."""
        left = [HumanMessage(content="first", id="1")]
        right = [HumanMessage(content="second", id="1")]
        merged = add_messages(left, right)
        assert len(merged) == 1
        assert merged[0].content == "second"

    def test_single_message(self):
        """Can add a single message to a list."""
        left = [HumanMessage(content="hello", id="1")]
        merged = add_messages(left, AIMessage(content="world", id="2"))
        assert len(merged) == 2

    def test_empty_left(self):
        """Can merge into an empty list."""
        merged = add_messages([], [HumanMessage(content="first", id="1")])
        assert len(merged) == 1

    def test_empty_right(self):
        """Can merge with empty right."""
        left = [HumanMessage(content="hello", id="1")]
        merged = add_messages(left, [])
        assert len(merged) == 1


class TestConcat:
    def test_concat_two_lists(self):
        """Two lists concatenate."""
        result = concat([1, 2], [3, 4])
        assert result == [1, 2, 3, 4]

    def test_concat_single_item(self):
        """A single item gets wrapped in a list."""
        result = concat([1, 2], 3)
        assert result == [1, 2, 3]

    def test_concat_empty(self):
        """Can concat with empty lists."""
        result = concat([], [1, 2])
        assert result == [1, 2]
        result = concat([1, 2], [])
        assert result == [1, 2]