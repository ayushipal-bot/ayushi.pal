"""Runs the 6 required test cases against the app in-process and prints the
request/response JSON for each - used both as a smoke test and to generate
the sample requests/responses in the README.

Run with:
    python -m tests.test_cases
"""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CASES = [
    (
        "1. Knowledge-base question",
        {"message": "What is your refund policy?"},
    ),
    (
        "2. Order-status question requiring the tool",
        {"message": "What's the status of my order?", "order_id": "ORD-1001"},
    ),
    (
        "3. Retrieved policy info + order lookup combined",
        {
            "message": "Can I get a refund, and also what's the status of order ORD-1002?",
        },
    ),
    (
        "4. Question outside the knowledge base",
        {"message": "What's the weather like today?"},
    ),
    (
        "5. Invalid/missing order ID",
        {"message": "What's the status of my order?"},
    ),
    (
        "6. Simulated tool failure",
        {"message": "Where is my order?", "order_id": "ORD-FAIL"},
    ),
]


def main() -> None:
    for title, payload in CASES:
        response = client.post("/chat", json=payload)
        print(f"\n=== {title} ===")
        print("Request: ", json.dumps(payload, indent=2))
        print("Response:", json.dumps(response.json(), indent=2))
        assert response.status_code == 200


if __name__ == "__main__":
    main()
