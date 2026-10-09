# ChatGPT subscription-only implementation gate

Status: live ChatGPT inference and release are blocked on included-only funding
and capability verification. Documentation reviewed on 2026-10-08. No OAuth
registration, inference request, credit-balance read or billing-setting change was
performed for this documentation review.

The contribution requires included subscription usage only: no API-key billing,
credits consumption or automatic funding fallback. Shared settings and Claude
improvements can proceed independently.

Two integration routes have different implementation status:

- **Codex app-server:** an adapter is being implemented around the user's existing
  native ChatGPT login and ephemeral threads. It checks native account type and
  rejects API-key accounts. Mocked protocol work does not establish working live
  inference, tool-free tutor behavior or zero-credit enforcement. These remain
  release and live-test gates.
- **Native Sign in with ChatGPT + Responses:** the proposed direct OAuth route
  remains blocked before implementation on the funding and eligibility evidence
  below. No new OAuth flow or credential store is introduced by the Codex route.

Neither route's connection label or authentication success proves that usage
cannot draw from credits. The [official app-server documentation](https://developers.openai.com/codex/app-server)
describes the runtime interface; it does not replace the funding contract.

## Verified documentation and remaining uncertainty

The official [integration overview](https://developers.openai.com/siwc/token-sharing-open-source)
describes optional permission for eligible Responses requests in open-source and
locally hosted apps. Dynamic registration associates a client with its selected
user/workspace; hosts use stable separate identifiers. These facts do not prove
that Flippy is eligible or that requests cannot consume credits.

The [account guide](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
describes app-specific access and limits for plan usage and credits in ChatGPT
Settings. It does **not establish the exact zero-credit setting, a policy-query
contract, or the enforcement semantics required here**. A link to settings alone
cannot verify the active policy. Review the current page again before acting;
the controls exist in documentation, but their strict behavior remains untested.

The [UI guidelines](https://developers.openai.com/siwc/ui-ux-guidelines) expressly
allow eligible usage from either included plan allowance or a credits balance.
Consequently, successful sign-in and a “Using ChatGPT plan” label are insufficient
proof of included-only funding.

The [inference guide](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
documents OAuth bearer authentication to the public Responses endpoint, streaming
with storage disabled, and a required completed terminal event. A usage-limit
failure can arrive after streaming begins. The reviewed examples provide no
included-only request option.

The [recovery guide](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery)
says usage errors stop inference without silently switching to another billing
path. That protects against undocumented fallback; it does not disambiguate
included allowance from credits permitted within the documented plan route.
An app-specific limit can trigger a usage-limit error even when the overall plan
still has allowance.

These are documentation observations, not a proof that no suitable control
exists. Do not infer enforcement from a local remaining-usage estimate, a request
preflight or an account with no purchased credits.

## Evidence required before direct OAuth implementation or live Codex acceptance

1. Obtain an official contract identifying the supported control that enables
   included allowance while denying credits for the issued Flippy client/profile.
2. Establish how the app or approved acceptance flow can verify that policy and
   detect changes; cover every host sharing the client.
3. Confirm server-side enforcement for simultaneous requests and allowance/limit
   transitions during an active stream. Local checks are not atomic reservations.
4. In an isolated, approved verification flow, demonstrate one included request
   and one controlled app-limit denial while credit usage remains unchanged.
   Prefer a supported test limit. Do not drain a subscription or purchase credits.
5. Record the official source, selected client/profile policy and outcome without
   tokens, account identifiers, balances, screenshots of private billing data or
   raw credential-bearing diagnostics. Revalidate mutable policy before release.

Any account-control change or live billing verification retains its native
approval boundary. An agent or maintainer's project approval cannot replace the
funding contract. If enforcement cannot be established, keep live ChatGPT
inference disabled. Do not use a warning or opt-in checkbox as proof, introduce an
API-key fallback, or build the speculative direct OAuth path. For Codex, also
verify that ordinary tutor/tip/video requests expose no action or built-in tools,
that desktop tasks expose only the intended catalog, and that ephemeral threads
avoid runtime persistence under the supported contract.

## Project eligibility and license

The reviewed source base (`073250be0106e00e8ac5f5a0a24094d754633ae7`) has third-party
notices but no project license file. Third-party asset licenses do not license
Flippy itself. Kap must choose the project license or obtain explicit integration
eligibility confirmation. This contribution does not select or add a license on
his behalf.

Once the funding and applicable route's eligibility gates pass, run explicitly
approved live acceptance against the exact adapter revision. The direct OAuth
route additionally needs the agreed native sign-in implementation and its
protocol/security tests. Until then, Claude remains the demonstrated inference
connection; provider selection and a Codex adapter must not be described as
verified live ChatGPT functionality.
