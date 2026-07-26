# Landing

> **Status: Migrating.** Superseded on boundaries by
> [Agent Voice And DNS Discovery](../../../gulls/docs/agent-voice-and-discovery.md),
> which wins wherever this document conflicts with it.
> **Still true:** everything below describes the deployed page — the build, the
> `/landing/` base path, the runtime config mechanism, and the Terraform upload
> are all executable today.
> **Retire when:** the platform app is split along the three-role taxonomy in
> the [Seagulls platform spec](../../docs/spec.md) and this page's description of
> `sea.gulls.ai` no longer names a retired model.

Vite + React landing page for `gulls.ai`.

This is intentionally separate from the platform app at `sea.gulls.ai`. The
landing page includes a lightweight product demo adapter
(`/demo/landing/ai-run`) backed by the optional internal AI Provider. It is not
a direct provider product or purchase surface and does not require sign-in.

## Known Inconsistency: The Domain Split

Two names are in play and they are not layered the way they read:

| Domain | What it is |
| --- | --- |
| `gulls.ai` | Two unrelated things at one apex: this static landing page, **and** the Seagulls Host hosted-handle namespace — `@weather:gulls.ai` resolves here. |
| `sea.gulls.ai` | The platform app: login and the SNS screens today; Console and Apps surfaces in the target. Earlier revisions of this file called it "the SNS/login app", a label the redesign retires. |

The split reads backwards. The subdomain carries the platform product while the
apex carries both marketing and the identity namespace, so the domain that must
serve `/.well-known/webfinger` for every hosted Gull is the one currently
serving a landing page. [Migration Plan](../../../gulls/docs/migration-plan.md)
Stage 2 adds those discovery records under `gulls.ai`, which means the Host
discovery documents and this page will share an origin and its routing rules.

This is recorded, not fixed. `gulls.ai` and `sea.gulls.ai` are **Frozen** under
the [Compatibility Contract](../../../gulls/docs/migration-plan.md#compatibility-contract),
which permits Stage 2 to add records but renames nothing. Any correction is a
separate migration with its own rollout, not a documentation edit.

## Development

```text
pnpm --filter landing dev     # dev server
pnpm --filter landing test    # vitest
pnpm --filter landing build   # tsc + vite build into dist/
```

Runtime configuration comes from `window.SEAGULL_CONFIG` in `config.js`. In
dev this is `public/config.js` at `/config.js`; the production build rewrites
the reference to `/landing/config.js`, where Terraform writes the runtime
config into the shared web bucket (`public/config.js` itself is excluded from
the upload).

The production build uses base `/landing/` because the deployed page lives
under the `landing/` prefix of the shared web S3 bucket. Terraform uploads
`dist/` (see `infra/terraform/envs/dev/main.tf`), so run the build before
`terraform plan`/`apply` — the Makefile's `aws-dev-plan`/`aws-dev-apply`
targets do this automatically.
