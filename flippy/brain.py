"""Claude via the Agent SDK on the Pro/Max subscription. Answer-only: no tools."""
import base64
import io
import os

from PIL import Image
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent,
                              TextBlock)

from .point import pick_target_size

SYSTEM_PROMPT = """\
you're a friendly tutor that can see the user's screen. they typed a question; your reply is shown in a small panel.

rules:
- default to one to three sentences, direct and dense. go deeper only if asked.
- plain text, no markdown or lists.
- if the question relates to the screen, reference specific things you see. if the screenshot isn't relevant, just answer.
- small icons are easy to misread. if you can't tell what an icon is, say what it looks like and that you're not sure, rather than guessing a name.

pointing:
you have a pointer that can highlight things on screen. use it when the user is looking for a button, menu, setting, or area, or when you walk them through several things on screen. don't point for general-knowledge questions.
to point, put [POINT:x,y:label] right after the words that mention the thing, where x,y are integer pixel coordinates in the screenshot (origin top-left, x right, y down, using the dimensions given) and label is 1-3 words.
the pointer glides to each tag as your reply is read out, and the panel moves with it showing only the text since the previous tag. so when you walk through several things, write one short sentence per thing, each ending with its tag, in a sensible order (at most 6). one thing = one tag.
if pointing wouldn't help, end with [POINT:none].
"""

# Model and effort come from settings (flippy-ask settings); env vars override for testing.
ENV_MODEL = os.environ.get("FLIPPY_MODEL")
ENV_EFFORT = os.environ.get("FLIPPY_EFFORT")


class BrainError(Exception):
    pass


def prepare_image(path: str, long_edge: int = 1920) -> tuple[str, tuple[int, int], tuple[int, int]]:
    """Downscale a screenshot (long_edge 0 = full size). Returns (base64 jpeg, image size, original size)."""
    with Image.open(path) as im:
        orig = im.size
        target = pick_target_size(*orig, long_edge or max(orig))
        small = im.convert("RGB").resize(target, Image.LANCZOS)
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode(), target, orig


class Brain:
    def __init__(self):
        # Never bill the API: the SDK picks up ANTHROPIC_API_KEY if it's set.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            tools=[],                 # no built-in tools at all
            allowed_tools=[],
            mcp_servers={},
            strict_mcp_config=True,   # ignore any user/project MCP config
            setting_sources=[],       # don't load CLAUDE.md, hooks, user settings
            max_turns=1,
            include_partial_messages=True,  # text deltas, so the pointer can move as the reply arrives
            model=ENV_MODEL,
            effort=ENV_EFFORT or "low",
            cwd=os.path.expanduser("~"),
        )
        self.client: ClaudeSDKClient | None = None
        self.dirty = False  # options changed; next question starts a fresh session
        self.last_model = None

    def configure(self, model: str | None, effort: str):
        """None model = the account's default. Applies on the next (fresh) session."""
        model, effort = ENV_MODEL or model, ENV_EFFORT or effort
        if (self.options.model, self.options.effort) != (model, effort):
            self.options.model, self.options.effort = model, effort
            self.dirty = self.client is not None

    async def start(self):
        self.client = ClaudeSDKClient(options=self.options)
        await self.client.connect()
        self.dirty = False

    async def stop(self):
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def reset(self):
        await self.stop()
        await self.start()

    async def ask(self, question: str, b64_jpeg: str, img_size: tuple[int, int], on_text=None) -> str:
        """Returns the full reply. on_text(delta) is called with text chunks as they stream in."""
        if self.client is None:
            await self.start()
        w, h = img_size
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_jpeg}},
            {"type": "text", "text": f"(screenshot is {w}x{h} pixels)\n\n{question}"},
        ]

        async def messages():
            yield {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None}

        await self.client.query(messages())
        parts: list[str] = []
        async for msg in self.client.receive_response():
            if isinstance(msg, StreamEvent):
                ev = msg.event
                if on_text and ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    on_text(ev["delta"]["text"])
            elif isinstance(msg, AssistantMessage):
                self.last_model = msg.model
                if getattr(msg, "error", None):
                    raise BrainError(str(msg.error))
                parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
            elif isinstance(msg, ResultMessage) and msg.is_error:
                raise BrainError(msg.result or msg.subtype or "unknown error")
        text = "".join(parts).strip()
        if not text:
            raise BrainError("empty reply")
        return text
