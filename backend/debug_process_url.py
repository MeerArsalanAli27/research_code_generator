import traceback
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

try:
    response = client.post(
        "/process_url",
        data={
            "url": "https://example.com",
            "framework": "pytorch",
            "llm": "openai",
            "api_key": "test"
        },
        timeout=20,
    )
    print("status", response.status_code)
    print(response.headers)
    try:
        print(response.json())
    except Exception:
        print(response.text)
except Exception:
    traceback.print_exc()
