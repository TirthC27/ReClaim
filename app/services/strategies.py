"""
Named negotiation strategies. Each is a short, human-readable description
fed as context to the LLM during offer revision — the LLM reasons using
these, rather than us hardcoding numeric formulas per strategy. A
deterministic guardrail (see negotiation_engine.py) still enforces hard
limits regardless of which strategy the LLM invokes.
"""

STRATEGIES = {
    "volume_margin_flex": {
        "name": "Volume Margin Flex",
        "description": (
            "When total demand quantity is large, a merchant may accept a "
            "smaller per-unit margin than their normal floor, because the "
            "total profit across many units can exceed the profit from a "
            "single full-margin sale. Only apply this if the resulting "
            "price still keeps some margin above the merchant's wholesale "
            "cost — never sell below cost."
        ),
    },
    "undercut_response": {
        "name": "Undercut Response",
        "description": (
            "If a competing merchant's current offer has genuinely better "
            "value (lower effective price after accounting for bundles), "
            "and this merchant still has room within their margin floor, "
            "they may reduce their price or add a bundled item to remain "
            "competitive rather than lose the whole order to a rival."
        ),
    },
    "hold_firm_on_scarcity": {
        "name": "Hold Firm on Scarcity",
        "description": (
            "If a merchant's available stock is low relative to total "
            "demand, they have less need to compete aggressively on price, "
            "since only a small portion of the order can go to them "
            "regardless. Holding at a higher price is reasonable here."
        ),
    },
}

def strategies_context_text() -> str:
    return "\n".join(
        f"- {s['name']}: {s['description']}" for s in STRATEGIES.values()
    )
