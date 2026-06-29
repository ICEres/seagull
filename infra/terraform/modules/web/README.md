# Web Module

Terraform module for the Seagull frontend.

Resources:

- S3 bucket for static assets.
- CloudFront distribution with origin access control.
- Terraform-managed static asset uploads from the Vite `dist` directory.
- Runtime `config.js` that points the static app at the deployed Social API and auth config.
- ACM certificate in `us-east-1` for the CloudFront viewer certificate.
- Route 53 DNS validation records and A/AAAA aliases for the frontend and optional admin domains.

CloudFront viewer certificates must live in `us-east-1`, so callers must pass an
`aws.us_east_1` provider alias into this module.
