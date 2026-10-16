# No-echo relay connectivity probe

This small package uses Python 3.10+ standard library only. It does not need
ShopSimulator data, GPU, training, account login, or dependency installation.
No actual authenticated probe has been run by the assistant. Public documentation
has not established the exact model/API compatibility; the path below is an
explicit candidate to test, not a claim that it works.

Run from the extracted package folder in an interactive terminal on the
computer/environment you explicitly chose for this work:

    python3 -m evaluation.probe --endpoint https://st.walkcoding.top/v1/chat/completions --probe-authorized

At `Relay API key (hidden, not saved):`, paste/type the key and press Enter.
Characters must not appear. Do not put the key in the command, environment,
files, redirected input, chat, screenshots, or shell history. The program refuses
non-interactive/echo fallback input and holds the key only in process memory.
It clears its reference at completion; this is not a cryptographic memory-erasure
guarantee. Close the terminal process when finished. No account terms checkbox
is accepted by this script.

At most two physical authenticated requests are made, only to HTTPS
st.walkcoding.top: GET /v1/models, then one <=64-output-token generation asking
for the word OK, using the exact model gpt-6.1-sol. All redirects are rejected.
An absent/mismatched model, uncertain outcome or API error stops without automatic
retry, fallback model, endpoint probing or dataset transmission. A 30-second
socket inactivity timeout applies; the 5-minute admission window is not a hard
completion deadline for an in-flight response.

Output is a sanitized JSON result with model-ID evidence, attempts, token usage
when returned, and unknown monetary cost. It contains neither key nor raw model
response. Share that result, not your credential. HTTP status, when available,
helps distinguish authentication from endpoint problems.

Success means the relay listed and returned the requested model ID. It does not
independently prove which backend model produced the response. Token usage is
not confirmed billing. This command does NOT start the 60 task-arm experiment.

The /v1/responses option is supported as an alternative explicit candidate, but
is not tried automatically. Do not retry an uncertain request merely by changing
paths. Ask for review of the sanitized result first.

Upstream utility source is retained to reuse its OpenAI-compatible response
normalization. Attribution and unresolved redistribution-license caveats remain
in THIRD_PARTY_NOTICES.md and UPSTREAM_MANIFEST.json. No datasets are included.
