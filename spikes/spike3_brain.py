"""Spike 3: Agent SDK on the subscription answers about a saved screenshot.

Run:  .venv/bin/python spikes/spike3_brain.py <screenshot.png> "question" ["follow-up"]
"""
import asyncio
import sys
import time

sys.path.insert(0, __file__.rsplit("/spikes/", 1)[0])
from flippy.brain import Brain, prepare_image  # noqa: E402
from flippy.point import image_to_logical, parse_reply  # noqa: E402


async def main():
    path, questions = sys.argv[1], sys.argv[2:]
    b64, img_size, shot_size = prepare_image(path)
    print(f"image {img_size} from {shot_size}, {len(b64) // 1024} KiB b64")
    brain = Brain()
    t0 = time.monotonic()
    await brain.start()
    print(f"connected in {time.monotonic() - t0:.1f}s")
    for q in questions:
        t0 = time.monotonic()
        raw = await brain.ask(q, b64, img_size)
        text, pt = parse_reply(raw)
        print(f"\nQ: {q}\nraw ({time.monotonic() - t0:.1f}s): {raw}\ntext: {text}\npoint: {pt}")
        if pt:
            print("logical:", image_to_logical(pt, img_size, shot_size, 1.0))
    await brain.stop()

asyncio.run(main())
