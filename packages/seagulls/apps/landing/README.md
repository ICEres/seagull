# Landing

Vite + React landing page for `gulls.ai`.

This is intentionally separate from the SNS/login app at `sea.gulls.ai`. The
landing page includes a lightweight demo that sends a message through the AI
provider demo endpoint (`/demo/landing/ai-run`) without requiring sign-in.

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
