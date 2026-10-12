"""Request schema validation."""
import pytest
from pydantic import ValidationError

from muse2api.api.schemas import (
    ChatCompletionRequest,
    ImageGenerationRequest,
    ResponsesRequest,
)


def test_chat_request_ok():
    req = ChatCompletionRequest(
        model="muse-spark-1.3",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert req.stream is False


def test_chat_request_requires_messages():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(model="muse-spark-1.3", messages=[])


def test_chat_request_requires_model():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(messages=[{"role": "user", "content": "hi"}])


def test_chat_request_allows_extra_openai_fields():
    req = ChatCompletionRequest(
        model="muse-spark-1.3",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        top_p=0.9,
        stop=["END"],
    )
    assert req.top_p == 0.9


def test_responses_request_defaults():
    req = ResponsesRequest(input="hello")
    assert req.model == "muse-spark-1.3"
    assert req.stream is False


def test_image_request_n_bounds():
    with pytest.raises(ValidationError):
        ImageGenerationRequest(prompt="x", n=9)
