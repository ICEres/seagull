# Web Module

Status: Current.

Last updated: 2026-06-29.

Terraform module for the Seagull frontend.

Resources:

- S3 bucket for static assets.
- CloudFront distribution with origin access control for the app.
- Terraform-managed static asset uploads from the Vite `dist` directory.
- Optional static landing page uploads under `/landing`.
- Optional separate CloudFront distribution for the landing domain.
- Runtime `config.js` that points the static app at the deployed Social API and auth config.
- ACM certificate in `us-east-1` for the CloudFront viewer certificate.
- Route 53 DNS validation records and A/AAAA aliases for the frontend, landing,
  and optional admin domains.

CloudFront viewer certificates must live in `us-east-1`, so callers must pass an
`aws.us_east_1` provider alias into this module.
