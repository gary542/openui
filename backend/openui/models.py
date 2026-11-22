import os
from pathlib import Path
from pydantic import BaseModel

# Ship the cl100k_base encoding with the app so token counting never has to
# download it at runtime (serverless cold starts, read-only file systems).
os.environ.setdefault(
    "TIKTOKEN_CACHE_DIR", str(Path(__file__).parent / "assets" / "tiktoken")
)
import tiktoken  # noqa: E402


class ShareRequest(BaseModel):
    prompt: str
    name: str
    emoji: str
    html: str


class VoteRequest(BaseModel):
    prompt: str
    name: str
    emoji: str
    html: str
    vote: bool


def count_tokens(messages):
    """Returns the number of tokens in a text string."""
    # TODO: we're just assuming the most recent encoding
    encoding = tiktoken.get_encoding("cl100k_base")
    text = ""
    for message in messages:
        if isinstance(message["content"], str):
            text += message["content"]
        else:
            text += " ".join(
                [part["text"] for part in message["content"] if part["type"] == "text"]
            )
    num_tokens = len(encoding.encode(text))
    return num_tokens
