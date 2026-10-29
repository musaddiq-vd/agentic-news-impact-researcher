"""Bedrock chat model factory."""

from app.config import get_settings


def get_llm(model_id: str):
    """Build a deterministic Bedrock chat model; credentials come from the AWS env vars."""
    from langchain_aws import ChatBedrockConverse  # lazy: keeps mocked tests import-free

    if not model_id:
        raise ValueError("Bedrock model ID is empty; set MODEL_* in .env")
    return ChatBedrockConverse(
        model=model_id,
        region_name=get_settings().aws_region,
        temperature=0,
    )
