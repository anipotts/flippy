# Provider identification assets

Retrieved October 8, 2026 (America/New_York). These marks identify the optional
providers in Flippy's setup window. They are not Flippy branding or an endorsement.
The Flippy app icon comes from the installed app through the existing permission
helper; it is not replaced by an asset in this directory.

## Claude

- Owner: Anthropic.
- Source: <https://claude.ai/favicon.svg>, the publicly served official site icon.
- `claude-symbol.svg` retains the downloaded bytes, including the original
  248 × 248 viewBox, path and orange `#D97757` fill.
- `claude.png`: rendered at 248 × 248 with transparency using CairoSVG 2.9.1.
  No path, proportions, color or framing changes.
- The public Claude product site is <https://claude.com/>. No general project
  license is asserted for Anthropic's mark; the trademark remains its owner's.

## OpenAI / ChatGPT

- Owner: OpenAI.
- Source: <https://cdn.oaistatic.com/assets/apple-touch-icon-mz9nytnj.webp>,
  the publicly served ChatGPT site touch icon.
- `openai-site-icon.webp` retains the original downloaded 180 × 180 image.
- `openai.png`: a 180 × 180 transparent white monochrome rendering. Pillow 12.3.0
  decodes the source to grayscale, uses `255 - luminance` as alpha, and sets RGB
  to white. This removes the source's white background and renders its black
  knot in white for the graphite surface. The canvas, knot geometry, proportions
  and antialias coverage are preserved; no crop, redraw or generated art is used.
- Usage guidance: <https://openai.com/brand/>. OpenAI's marks remain OpenAI's
  property. Use only to identify related OpenAI services, with appropriate space,
  subordinate to Flippy's identity, and without implying sponsorship. Their
  guidelines and revocable usage permission govern use; these files are not
  relicensed under Flippy's project license. No gated logo download or terms
  acknowledgment was performed to retrieve the public site asset.

The setup window must accurately label ChatGPT's unresolved runtime/funding gates;
the provider mark does not establish that inference is available.
