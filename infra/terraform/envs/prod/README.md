# Prod Environment

Status: Current.

Last updated: 2026-06-22.

Terraform root module for the production AWS environment.

Do not build this before the dev environment is proven.

Initial production work should focus on:

- Backups.
- Alarms.
- Least-privilege IAM.
- Domain and certificate setup.
- Deployment rollback strategy.
