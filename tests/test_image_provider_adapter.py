from __future__ import annotations

from types import SimpleNamespace

from narrascape.providers.image_adapter import ReferenceImageProviderAdapter


def test_reference_image_adapter_wraps_generation_in_budget_transaction():
    calls = []
    generator = SimpleNamespace(_generate_one=lambda **kwargs: calls.append(kwargs) or True)

    class Coordinator:
        def reserve(self, reservation_id, estimated_cost, *, task):
            calls.append(("reserve", reservation_id, estimated_cost, task))

        def commit(self, reservation_id):
            calls.append(("commit", reservation_id))

    adapter = ReferenceImageProviderAdapter(
        generator=generator,
        provider="seedream",
        coordinator=Coordinator(),
        estimated_cost=0.25,
    )

    assert adapter.generate(out_name="style_anchor", prompt="still life")
    assert calls[0] == ("reserve", "pre_production:seedream:style_anchor", 0.25, {})
    assert calls[1]["prompt"] == "still life"
    assert calls[2] == ("commit", "pre_production:seedream:style_anchor")
