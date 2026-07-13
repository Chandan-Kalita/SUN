from typing import Any

from pydantic import BaseModel

class FunctionTool(BaseModel):
    arguments:str
    name:str

class ToolCall(BaseModel):
    function:FunctionTool
    id:str
    index:int
    type:str


class Message(BaseModel):
    role: str
    content: str | None = None
    tool_calls:list[ToolCall]|None=None
    tool_call_id:str | None = None
    # Future compatibility
    model_config = {
        "extra": "allow",
    }



class Choice(BaseModel):
    index: int
    message: Message
    logprobs: Any | None = None
    finish_reason: str | None = None # tool_calls | stop

    model_config = {
        "extra": "allow",
    }


class PromptTokensDetails(BaseModel):
    cached_tokens: int | None = None

    model_config = {
        "extra": "allow",
    }


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    prompt_tokens_details: PromptTokensDetails | None = None

    # DeepSeek-specific
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None

    model_config = {
        "extra": "allow",
    }


class ChatCompletionResponse(BaseModel):
    id: str
    object: str
    created: int
    model: str

    choices: list[Choice]
    usage: Usage | None = None

    system_fingerprint: str | None = None

    model_config = {
        "extra": "allow",
    }
    
class ChatResponse(BaseModel):
    success:bool
    data:ChatCompletionResponse|None
    error:str|None


class ToolResult(BaseModel):
    ok: bool
    output: str | None = None
    error: str | None = None
    exit_code: int | None = None
    note: str | None = None
    effects: str | None = None

    def render(self) -> str:
        header = f"ok:{str(self.ok).lower()}"
        if self.exit_code is not None:
            header += f" exit_code:{self.exit_code}"
        parts = [header]
        if self.note:
            parts.append(f"--- note ---\n{self.note}")
        if self.error:
            parts.append(f"--- error ---\n{self.error}")
        if self.output:
            parts.append(f"--- output ---\n{self.output}")
        if self.ok and not self.output and not self.error:
            parts.append("--- output ---\n(empty)")
        if self.effects:
            parts.append(f"--- effects ---\n{self.effects}")
        return "\n".join(parts)