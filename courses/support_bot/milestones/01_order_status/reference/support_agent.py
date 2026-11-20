"""Reference solution, milestone 1: order-status tool (stub data, no network)."""

ORDERS = {
    "1001": {"status": "shipped", "total": 40.0, "refunded": False},
    "1002": {"status": "delivered", "total": 25.0, "refunded": False},
    "1003": {"status": "processing", "total": 60.0, "refunded": False},
}


def get_order_status(order_id):
    """Return the status of an order; raise ValueError for an unknown id."""
    order = ORDERS.get(str(order_id))
    if order is None:
        raise ValueError(f"Unknown order id: {order_id!r}")
    return order["status"]


TOOLS = [
    {
        "name": "get_order_status",
        "description": (
            "Look up the current status of a customer's order by its order id. "
            "Use when the customer asks where an order is or whether it has shipped."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "The order id"}},
            "required": ["order_id"],
        },
    }
]
