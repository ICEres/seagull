# AI Provider Terraform Module

AWS dev module for the Seagull AI provider backend.

It provisions:

- API Gateway HTTP API.
- Python Lambda API handler.
- DynamoDB tables for runs, run events, usage, server credits, user credits,
  provider config, admin audit events, model policies, and budget limits.

The MVP deploys the fake provider adapter only. Real provider credentials and
provider-specific adapters are intentionally deferred.
