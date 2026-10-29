"""Bedrock chat model factory."""

from app.config import get_settings

# Bedrock throttles bursts (seen with Nova Pro: "ThrottlingException: Too many requests").
# Adaptive mode slows the client down and retries instead of failing the call.
BEDROCK_MAX_ATTEMPTS = 8


def get_llm(model_id: str):
    """Build a deterministic Bedrock chat model; credentials come from the AWS env vars."""
    from botocore.config import Config  # lazy: keeps mocked tests import-free
    from langchain_aws import ChatBedrockConverse

    if not model_id:
        raise ValueError("Bedrock model ID is empty; set MODEL_* in .env")
    return ChatBedrockConverse(
        model=model_id,
        region_name=get_settings().aws_region,
        temperature=0,
        config=Config(retries={"max_attempts": BEDROCK_MAX_ATTEMPTS, "mode": "adaptive"}),
    )
