"""Claude via the Agent SDK on the Pro/Max subscription. Tutor answers and opt-in desktop tasks."""
import base64
import io
import os
from dataclasses import replace

from PIL import Image
from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, StreamEvent,
                              TextBlock, query)

from .point import pick_target_size

# The pointing instructions are adapted from Clicky (MIT: see THIRD_PARTY_NOTICES.md).
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

tutorials:
only when the message ends with "(tutorial: ...)": mark each step they have to do themselves by adding :click after the label, e.g. [POINT:412,88:Track menu:click]. flippy waits until they click it before going on. when it says "(not a tutorial ...)", never use :click.
if clicking will change the screen (opens a menu, dialog, panel or another view), stop your reply right after that step: you can't see what comes next yet. once they click it you'll get a fresh screenshot and "continue", and you go on from there with the next step(s).
"""

# Model and effort come from settings (flippy-ask settings); env vars override for testing.
ENV_MODEL = os.environ.get("FLIPPY_MODEL")
ENV_EFFORT = os.environ.get("FLIPPY_EFFORT")


TIPS_PROMPT = """\
you write short tips for someone learning an app. each tip is one or two plain sentences (no markdown),
concrete and actionable: name the menu, panel, button or shortcut. skip the obvious. order them from
beginner to advanced and give each a level: 1 (first hour), 2 (first week) or 3 (power user).
reply with only a JSON array: [{"text": "...", "level": 1}, ...]
"""


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

    async def act(self, question, desktop):
        """An isolated tool session using the tutor's existing model/auth settings.

        No API client or key is introduced. Tutor and tip sessions remain tool-free.
        The local handlers enforce approval even though MCP tools are allowed here.
        """
        from .actions import PROMPT
        opts = replace(self.options, system_prompt=PROMPT, max_turns=16,
                       include_partial_messages=False, mcp_servers={"desktop": desktop.server()},
                       allowed_tools=[f"mcp__desktop__{name}" for name in ("screenshot", "click", "type", "key")])
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(question)
            text = ""
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    self.last_model = msg.model
                    if getattr(msg, "error", None):
                        raise BrainError(str(msg.error))
                    # Only the last assistant message is the task's final answer.
                    text = "".join(b.text for b in msg.content if isinstance(b, TextBlock))
                elif isinstance(msg, ResultMessage):
                    if msg.is_error or msg.subtype != "success":
                        raise BrainError(msg.result or "Desktop task did not finish.")
                    text = msg.result or text
            if desktop.cancel.is_set():
                return f"Task stopped: {desktop.failure or 'canceled'}. Check the screen before continuing."
            return text.strip() or "Task finished without a final answer; check the screen."

    async def write_tips(self, app_name: str, goal: str, n: int, skip: list[str]) -> list[dict]:
        """One text-only call, outside the conversation: n tips for app_name. skip: tips they already have."""
        opts = ClaudeAgentOptions(system_prompt=TIPS_PROMPT, tools=[], allowed_tools=[], mcp_servers={},
                                  strict_mcp_config=True, setting_sources=[], max_turns=1,
                                  model=self.options.model, effort="low", cwd=os.path.expanduser("~"))
        ask = f"App: {app_name}\n"
        if goal:
            ask += f"What they want to do: {goal}\n"
        if skip:
            ask += "They already have these (don't repeat them):\n" + "\n".join(f"- {t}" for t in skip[-60:]) + "\n"
        ask += f"Write {n} tips."
        parts = []
        async for msg in query(prompt=ask, options=opts):
            if isinstance(msg, AssistantMessage):
                if getattr(msg, "error", None):
                    raise BrainError(str(msg.error))
                parts.extend(b.text for b in msg.content if isinstance(b, TextBlock))
            elif isinstance(msg, ResultMessage) and msg.is_error:
                raise BrainError(msg.result or msg.subtype or "unknown error")
        return parse_tips("".join(parts))

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


def parse_tips(text: str) -> list[dict]:
    """The JSON array out of a reply (tolerates code fences and chatter around it)."""
    import json
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        raise BrainError("no tips in the reply")
    try:
        raw = json.loads(text[start:end + 1])
    except ValueError as e:
        raise BrainError(f"couldn't read the tips: {e}") from e
    tips = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("text", "")).strip():
            level = item.get("level", 2)
            tips.append({"text": str(item["text"]).strip(), "level": level if level in (1, 2, 3) else 2})
    if not tips:
        raise BrainError("no tips in the reply")
    return tips
