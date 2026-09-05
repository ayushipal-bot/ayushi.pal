"""Mock order-status tool.

Simulates an external order-management API. Real integration would replace
the body of `get_order_status` with an HTTP call to that service; the
signature and exceptions are designed so that swap is a one-function change.
"""


class OrderNotFoundError(Exception):
    """Raised when the order id does not exist."""


class ToolExecutionError(Exception):
    """Raised when the (simulated) external API call fails."""


_MOCK_ORDERS: dict[str, dict] = {
    "ORD-1001": {
        "status": "Shipped",
        "eta": "2026-09-08",
        "items": ["Widget Pro x2"],
    },
    "ORD-1002": {
        "status": "Processing",
        "eta": "2026-09-10",
        "items": ["Starter Kit x1"],
    },
    "ORD-1003": {
        "status": "Delivered",
        "eta": "2026-09-01",
        "items": ["Widget Pro x1", "Cable x3"],
    },
}

# Special id used by tests/demos to deterministically simulate an upstream
# failure (timeout, 5xx, etc.) without needing to mock a real HTTP client.
FAILING_ORDER_ID = "ORD-FAIL"


def get_order_status(order_id: str, *, force_failure: bool = False) -> dict:
    """Look up an order's status.

    Raises:
        ToolExecutionError: the external API is unavailable (simulated).
        OrderNotFoundError: no such order exists.
    """
    if force_failure or order_id == FAILING_ORDER_ID:
        raise ToolExecutionError("order-status API is currently unavailable")

    order = _MOCK_ORDERS.get(order_id.upper())
    if order is None:
        raise OrderNotFoundError(f"no order found with id '{order_id}'")

    return {"order_id": order_id.upper(), **order}
