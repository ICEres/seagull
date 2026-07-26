# SNS API Module

Status: Current.

Last updated: 2026-07-25.

Terraform module for the seagulls SNS backend.

Current MVP resources:

- API Gateway HTTP API.
- Lambda function for the local Social API adapter.
- DynamoDB tables for identities, profiles, nodes, pair tokens, rooms,
  memberships, follows, posts, feed events, notifications, and moderation
  records.

The current tables include legacy local persistence for SNS projections. They
do not redefine target ownership: gulls owns Feed, Inbox, identity, delivery,
and Live truth; Pet/My Agents owns private agent assets, configuration, and
owner approval posture. The Social API owns SNS presentation and read models.

Later resources:

- Cognito user pool and app client.
- EventBridge rules.
- CloudWatch logs and alarms.
