"""Reference solution, milestone 2: order-status and refund tools (stub data, no network)."""

ORDERS = {
    "1001": {"status": "shipped", "total": 40.0, "refunded": False},
    "1002": {"status": "delivered", "total": 25.0, "refunded": False},
    "1003": {"status": "processing", "total": 60.0, "refunded": True},
}


def _find(order_id):
    order = ORDERS.get(str(order_id))
    if order is None:
        raise ValueError(f"Unknown order id: {order_id!r}")
    return order


def get_order_status(order_id):
    """Return the status of an order; raise ValueError for an unknown id."""
    return _find(order_id)["status"]


def issue_refund(order_id, amount):
    """Refund up to the order total, once. Raise ValueError otherwise."""
    order = _find(order_id)
    if order["refunded"]:
        raise ValueError(f"Order {order_id} was already refunded")
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError("Refund amount must be a positive number")
    if amount > order["total"]:
        raise ValueError(f"Refund {amount} is over the order total {order['total']}")
    order["refunded"] = True
    return {"order_id": str(order_id), "refunded": amount}


TOOLS = [
    {
        "name": "get_order_status",
        "description": (
            "Look up the current status of a customer's order by its order id. "
            "Use when the customer asks where an order is. Do not use it to move money."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "The order id"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "issue_refund",
        "description": (
            "Refund money for an order, up to its total, once per order. "
            "Use when the customer asks for their money back. Do not use it to check status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order id"},
                "amount": {"type": "number", "description": "Amount to refund"},
            },
            "required": ["order_id", "amount"],
        },
    },
]
