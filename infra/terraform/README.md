# Terraform

Terraform owns AWS infrastructure for Seagull.

Planned layout:

```text
envs/
  dev/
  prod/
modules/
  shared/
  safety-gateway/
  message-hub/
  social-api/
  web/
```

Root environment modules should compose reusable child modules. Keep resource
definitions out of app folders so infrastructure changes are reviewable in one
place.
