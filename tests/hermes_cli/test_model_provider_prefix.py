"""Tests for the "<provider>/<model>" prefix handling in
detect_static_provider_for_model — the Vibe Code per-phase model format.

Regression guard for: a phase model like "anthropic/claude-sonnet-4-6" being
sent whole to the user's default provider (e.g. alibaba/dashscope) -> HTTP 404
model_not_found, because the provider prefix wasn't split off.

Runnable under pytest OR directly:
    python tests/hermes_cli/test_model_provider_prefix.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hermes_cli.models as m  # noqa: E402

d = m.detect_static_provider_for_model


def test_direct_provider_prefix_is_split():
    # The bug: this returned None (prefix unrecognised) -> caller kept the whole
    # string + default provider. Now it routes to anthropic with a bare model.
    assert d("anthropic/claude-sonnet-4-6", "alibaba") == ("anthropic", "claude-sonnet-4-6")
    # Same provider as current, but the prefix is still stripped to a bare model.
    assert d("alibaba/qwen3-coder-plus", "alibaba") == ("alibaba", "qwen3-coder-plus")
    print("ok prefix_split")


def test_bare_model_still_detected():
    # No "/", existing detection path unchanged.
    assert d("claude-sonnet-4-6", "alibaba") == ("anthropic", "claude-sonnet-4-6")
    print("ok bare_unchanged")


def test_aggregator_prefix_left_whole():
    # Aggregators use the "vendor/model" id AS the model name — must not split.
    for agg in m._AGGREGATOR_PROVIDERS:
        assert d(f"{agg}/some/model", "alibaba") != (agg, "some/model")
    print("ok aggregator_untouched")


def test_unknown_prefix_not_split():
    # A "/" with an unknown prefix is not a provider route — fall through (the
    # existing logic decides; it must not be split into (unknown, rest)).
    res = d("totally-not-a-provider/whatever", "alibaba")
    assert res is None or res[0] != "totally-not-a-provider"
    print("ok unknown_prefix")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nAll {len(fns)} tests passed.")
