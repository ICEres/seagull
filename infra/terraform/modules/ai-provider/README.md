# Internal AI Provider Terraform Module

Status: Current.

Last updated: 2026-07-25.

AWS dev module for Seagull's optional shared internal AI Provider. It is
execution, metering, quota, audit, and cost-control infrastructure—not a
standalone customer product or direct business surface.

It provisions:

- API Gateway HTTP API.
- Python Lambda API handler.
- DynamoDB tables for runs, run events, usage, internal server/owner quota and
  accounting records (implemented with legacy `credit` names), provider config,
  admin audit events, model policies, and budget limits.

The MVP deploys the fake provider adapter only. Real provider credentials and
provider-specific adapters are intentionally deferred.
The accounting units are non-purchasable and are separate from Agent Request
task credits.
