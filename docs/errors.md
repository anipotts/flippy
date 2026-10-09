# Flippy error codes

When something fails, Flippy shows a short sentence and a code, like `Claude couldn't answer. · CLAUDE-FAILED`.
Find the code below for what happened and what to do. If that doesn't fix it, open an issue and include the code;
`~/Library/Logs/flippy.log` (macOS) or `~/.local/state/flippy.log` (Linux) has a matching `error <CODE>: ...` line.

Codes never change meaning. A code that's no longer used stays listed as retired.

## Connecting

## CLAUDE-LOGIN
Claude Code isn't logged in, or its login expired. Open **Setup** (menu bar → Setup…) and click **Log in…** on the
Claude card, then run `/login` in the Terminal window that opens. Flippy only uses a Claude Pro or Max subscription,
never an API key.

## CODEX-LOGIN
Codex isn't signed in with ChatGPT. Open **Setup** and click **Sign in…** on the ChatGPT card.

## NO-PROVIDER
Neither Claude nor ChatGPT is connected. Open **Setup** and connect one.

## PICK-PROVIDER
Both Claude and ChatGPT are connected and **Use** is on Automatic, so Flippy doesn't know which to use. Pick one under
**Use** in Setup, or in Settings → Models → Provider.

## Claude

## CLAUDE-MISSING
Flippy can't find Claude Code. Reinstall Flippy (it bundles Claude Code), or install Claude Code so `claude` runs in
a terminal.

## CLAUDE-START
Claude Code is there but wouldn't start. Quit and reopen Flippy. If it keeps happening, run `claude` in a terminal to
see its own error.

## CLAUDE-BUSY
Claude's servers had a problem (an outage or overload). Wait a minute and try again; https://status.anthropic.com shows
ongoing incidents.

## CLAUDE-RATE
Claude is turning away requests that come too fast. Wait a little and try again. This isn't your plan's limit (that's
PLAN-LIMIT).

## CLAUDE-BILLING
Your Claude account can't take the request for a billing reason (for example a lapsed subscription). Check your plan at
claude.ai. Flippy never switches you onto extra usage.

## CLAUDE-REJECTED
Claude refused the request as invalid. Usually the model in Settings → Models isn't available on your plan: set it to
**Account default** and try again.

## CLAUDE-INCOMPLETE
Claude stopped before it finished answering. Try again; if a desktop task did this, check the screen first.

## CLAUDE-FAILED
Claude failed for a reason Flippy doesn't recognize. Try again. If it repeats, open an issue with the matching line from
the log.

## Codex / ChatGPT

## CODEX-MISSING
Codex isn't installed. Install the Codex CLI (https://developers.openai.com/codex/cli/) and sign in with ChatGPT.

## CODEX-OLD
Your Codex is older than Flippy supports. Update it (for example `brew upgrade codex` or `npm i -g @openai/codex`).

## CODEX-START
Codex wouldn't start. Check that `codex` runs in a terminal and that you're signed in with ChatGPT.

## CODEX-RUNTIME
Codex is signed in, but the private runtime Flippy starts for it couldn't start on this computer. Update Codex; if it
persists, open an issue.

## CODEX-ISOLATION
Flippy runs Codex separately from your own Codex settings, and something in your Codex config (`~/.codex/config.toml`)
would override that, such as a different API address. Flippy refuses rather than follow it. Remove that setting or use
Claude.

## CODEX-DISCONNECTED
The connection to Codex dropped. Try again; Flippy restarts it.

## CODEX-NO-RESPONSE
Codex didn't answer in time. Try again.

## CODEX-INCOMPLETE
Codex stopped before it finished answering. Try again.

## CODEX-FAILED
Codex failed for a reason Flippy doesn't recognize. Try again, or open an issue with the log line.

## Plan limits

## PLAN-LIMIT
You've used your plan's included usage for now (or are within 5% of it). Flippy stops here so it never spends Claude
extra usage or ChatGPT credits; the message says when the limit resets. To be fully safe, also turn extra usage /
credits off in your account.

## Desktop tasks (/act)

## ACT-HELD
A key or mouse button was held down, so Flippy didn't send input. Keep your hands off the keyboard and mouse while it
borrows the pointer, then try again.

## ACT-DECLINED
You declined an action on an approval card, so the task stopped.

## ACT-SCREEN-CHANGED
The screen changed between Flippy looking and acting, so it didn't act on something stale. Try again.

## ACT-WINDOW-CHANGED
The window or display Flippy was working in changed or went away. Bring the app back and try again.

## ACT-CAPTURE
Flippy couldn't capture the screen or the app's window. Check Screen Recording permission in System Settings.

## ACT-CLEANUP
Flippy couldn't confirm it released every key and mouse button it pressed. Restart Flippy before acting again.

## ACT-PERMISSION
Desktop tasks need Accessibility (and Screen Recording) permission. Grant them in System Settings → Privacy & Security,
then restart Flippy.

## ACT-LIMIT
The task used all the steps it's allowed. Check the screen, then start a new /act request to continue.

## ACT-STOPPED
The task stopped; the message says why (for example the app quit). Check the screen before continuing.

## ACT-FAILED
Flippy couldn't hand a desktop result back to the model. Try again.

## Anything else

## TIMEOUT
The answer took too long. Try again, or lower the effort in Settings → Models.

## NETWORK
Flippy couldn't reach the model service. Check your internet connection.

## UNKNOWN
Something failed that Flippy doesn't recognize. Open an issue with the matching log line.
