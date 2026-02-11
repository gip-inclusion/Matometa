import json

import httpx

from web import llm


def test_ollama_generate_basic():
    def handler(request):
        assert request.url == httpx.URL("http://ollama:11434/api/generate")
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3-coder-next"
        return httpx.Response(200, json={"response": "bonjour", "done": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    try:
        text = llm._ollama_generate(
            "Salut",
            model="qwen3-coder-next",
            max_tokens=5,
            temperature=0.1,
            timeout=10,
            client=client,
        )
    finally:
        client.close()

    assert text == "bonjour"
