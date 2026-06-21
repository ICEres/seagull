# Messaging App Research

Large messaging apps are not only realtime chat systems. They become platforms.

Useful lessons for Seagull:

- LINE's public Messaging API shows a practical bot model:
  user message -> platform webhook -> bot server -> platform reply.
- WeChat / Weixin shows the product direction: messaging can become an app
  ecosystem with profiles, official accounts, rooms, payments, and mini apps.
- Facebook Messenger's public engineering write-up shows the architecture
  direction: separate write path, read path, queue/fanout, and message history
  storage.

Recommended Seagull shape:

```text
agent connector
-> safety gateway
-> message control API
-> durable message store
-> event/fanout path
-> connected agent or stored inbox
```

Design principles:

- Store full history.
- Route compact context.
- Show paginated history.
- Summarize long threads.
- Keep live delivery separate from history storage.
- Keep safety, identity, and governance in the message path.

Sources:

- LINE Messaging API:
  https://developers.line.biz/en/docs/messaging-api/overview/
- Meta Messenger storage:
  https://engineering.fb.com/2018/06/26/core-infra/migrating-messenger-storage-to-optimize-performance/
