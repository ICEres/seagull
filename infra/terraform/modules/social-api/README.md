# Social API Module

Terraform module for the social/user backend.

Current MVP resources:

- API Gateway HTTP API.
- Lambda function for the local Social API adapter.
- DynamoDB tables for identities, profiles, nodes, pair tokens, rooms,
  memberships, follows, posts, feed events, notifications, and moderation
  records.

Later resources:

- Cognito user pool and app client.
- EventBridge rules.
- CloudWatch logs and alarms.
