# Model routing

| Kind | Role | Model | Effort chain |
|---|---|---|---|
| plan | pm | `gpt-5.6-sol` | `ultra -> max -> xhigh -> high` |
| plan-review | plan-reviewer | `gpt-5.6-sol` | `ultra -> max -> xhigh -> high` |
| code | builder | `gpt-5.6-terra` | `xhigh -> high -> medium` |
| text | writer | `gpt-5.6-luna` | `xhigh -> high -> medium` |
| reporter | reporter | `gpt-5.6-luna` | `xhigh -> high -> medium` |
| explore | explorer | `gpt-5.6-luna` | `high -> medium` |
| test | tester | `gpt-5.6-terra` | `xhigh -> high` |
| code-review | code-reviewer | `gpt-5.6-terra` | `xhigh -> high` |
| risk | risk-reviewer | `gpt-5.6-sol` | `ultra -> max -> xhigh -> high` |
| other | explorer after a recorded route decision | `gpt-5.6-terra` | `high -> medium` |

Record three separate evidence levels:

- `requested`: the route required by workflow policy.
- `configured`: the value actually passed through an agent file, spawn argument,
  or CLI configuration.
- `provider_observed`: authoritative runtime/provider telemetry when available;
  otherwise `not_reported`. JSONL success, final text, and model self-report are
  not provider attestation.

The effort chains above are an explicit workflow fallback authorization, not a
claim that every account/model supports every level. A verified client
capability table may avoid an effort the local CLI parser cannot represent;
after invocation, only an explicit unsupported-effort error permits another
same-model fallback. Authentication, account, provider, quota, rate limit,
network, permission, sandbox, model-not-found, schema, or worker-test errors do
not permit effort fallback or cross-model substitution. Report
`configured_route_enforced` when the local request is proven, and report
`provider_execution_attested` only when authoritative telemetry is present.

Sol, Terra, and Luna are content-routing tiers inside the 5.6 family: use Sol
for planning and risk, Terra for code and technical validation, and Luna for
text/reporting and light read-only exploration. They are not an automatic retry
chain. A failed call never silently falls through to another tier.
