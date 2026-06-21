#!/usr/bin/env node

const baseUrl = process.argv[2];
if (!baseUrl) {
  console.error("usage: scripts/smoke-router-ws.mjs <websocket-url>");
  process.exit(2);
}

const probe = `router-smoke-${Date.now()}`;
const recipientAgentId = `agent-router-smoke-${Date.now()}`;
const url = `${baseUrl}?agent_id=${encodeURIComponent(recipientAgentId)}`;
const ws = new WebSocket(url);

const timeout = setTimeout(() => {
  console.error("timed out waiting for routed websocket payload");
  ws.close();
  process.exit(1);
}, 10000);

ws.addEventListener("open", () => {
  ws.send(
    JSON.stringify({
      action: "route",
      message_id: `message_${probe}`,
      thread_id: `thread_${probe}`,
      sender_agent_id: "agent-router-smoke-sender",
      recipient_agent_ids: [recipientAgentId],
      payload: {
        probe,
        ok: true,
      },
    }),
  );
});

ws.addEventListener("message", (event) => {
  let data;
  try {
    data = JSON.parse(event.data);
  } catch {
    return;
  }

  if (data.probe === probe && data.ok === true) {
    clearTimeout(timeout);
    console.log(JSON.stringify({ ok: true, probe, recipient_agent_id: recipientAgentId }));
    ws.close();
  }
});

ws.addEventListener("error", (event) => {
  clearTimeout(timeout);
  console.error("websocket error", event.message || event.type);
  process.exit(1);
});
