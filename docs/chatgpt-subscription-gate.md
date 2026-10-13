# ChatGPT: included usage only

Flippy may use only a subscription's included usage: no API-key billing, no credits, no automatic funding
fallback. Documentation reviewed 2026-10-08.

## Codex app-server (shipped)

ChatGPT runs through the user's installed Codex in a home of Flippy's own, with ephemeral threads; API-key
accounts are rejected (`flippy/codex_provider.py`, protocol: the
[app-server documentation](https://developers.openai.com/codex/app-server)). `flippy/usage_guard.py` reads the
plan's rate limits before each request and stops a turn the moment credits are reported, and says what that can't
rule out. The only absolute guarantee is turning credits off in the ChatGPT account, which setup tells the user.

## Direct Sign in with ChatGPT + Responses (not built)

Blocked until included-only funding can be proven. The official docs don't establish it:

- The [integration overview](https://developers.openai.com/siwc/token-sharing-open-source) offers optional
  permission for eligible Responses requests from open-source and locally hosted apps; that doesn't make Flippy
  eligible.
- The [account guide](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) has
  per-app limits for plan usage and credits in ChatGPT Settings, but no exact zero-credit setting, policy query or
  enforcement semantics.
- The [UI guidelines](https://developers.openai.com/siwc/ui-ux-guidelines) allow eligible usage from the plan
  allowance *or* credits, so a sign-in or a "Using ChatGPT plan" label proves nothing.
- The [inference guide](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) has no
  included-only request option, and a usage-limit failure can arrive mid-stream.
- The [recovery guide](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery) says usage
  errors never silently switch billing path, which doesn't separate included allowance from permitted credits.

Before building it, get:

1. An official contract naming the control that allows included usage and denies credits for Flippy's
   client/profile, and how to verify that policy and notice changes, for every host sharing the client.
2. Server-side enforcement for simultaneous requests and limit transitions mid-stream (local checks aren't atomic).
3. An approved, isolated test: one included request and one controlled app-limit denial with credit usage
   unchanged (a supported test limit; never drain a subscription or buy credits). Record the source, policy and
   outcome without tokens, account ids, balances or private billing screenshots.

If that can't be established, don't build it: no warning or opt-in checkbox as proof, no API-key fallback.

Eligibility also needs a project license: Flippy has third-party notices but no license of its own, and Kapil has
to choose one (or get explicit eligibility confirmation).
