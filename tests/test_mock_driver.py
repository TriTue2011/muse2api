"""Mock driver: deterministic, offline."""
from muse2api.drivers.mock import MockDriver


def _chat_body():
    return {
        "model": "muse-spark-1.3",
        "messages": [{"role": "user", "content": "write a haiku"}],
    }


async def test_list_models():
    models = await MockDriver().list_models()
    assert models
    assert any(m.id == "muse-spark-1.3" for m in models)


async def test_chat_complete_shape():
    resp = await MockDriver().chat_complete(_chat_body(), timeout=5)
    assert resp["object"] == "chat.completion"
    choice = resp["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"]
    assert choice["finish_reason"] == "stop"


async def test_chat_stream_yields_deltas():
    chunks = [c async for c in MockDriver().chat_stream(_chat_body(), timeout=5)]
    assert chunks
    assert "".join(chunks).strip()


async def test_responses_create_shape():
    resp = await MockDriver().responses_create({"model": "x", "input": "hi"}, 5)
    assert resp["object"] == "response"
    assert resp["status"] == "completed"
    assert resp["output"][0]["content"][0]["text"]


async def test_generate_image_shape():
    resp = await MockDriver().generate_image({"prompt": "a fox"}, 5)
    assert resp["data"][0]["url"]


async def test_get_model_found_and_missing():
    driver = MockDriver()
    model = await driver.get_model("muse-spark-1.3")
    assert model is not None and model.id == "muse-spark-1.3"
    assert await driver.get_model("nope-9") is None


async def test_service_status():
    status = await MockDriver().service_status()
    assert status["status"] == "ok"
