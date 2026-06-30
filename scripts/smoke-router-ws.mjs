#!/usr/bin/env node

const baseUrl = process.argv[2];
const messageApiUrl = process.argv[3] || process.env.MESSAGE_API_URL;
if (!baseUrl || !messageApiUrl) {
  console.error("usage: scripts/smoke-router-ws.mjs <websocket-url> <message-api-url>");
  process.exit(2);
}

const probe = `router-smoke-${Date.now()}`;
const scopes = ["agent:read", "agent:inbox", "agent:post", "agent:ack"];
let senderWs;
let recipientWs;

const timeout = setTimeout(() => {
  console.error("timed out waiting for routed websocket payload");
  senderWs?.close();
  recipientWs?.close();
  process.exit(1);
}, 10000);

try {
  const sender = await registerAgent("sender");
  const recipient = await registerAgent("recipient");
  recipientWs = new WebSocket(websocketUrl(baseUrl, recipient.agentId, recipient.token));

  recipientWs.addEventListener("open", () => {
    senderWs = new WebSocket(websocketUrl(baseUrl, sender.agentId, sender.token));
    senderWs.addEventListener("open", () => {
      senderWs.send(
        JSON.stringify({
          action: "route",
          message_id: `message_${probe}`,
          thread_id: `thread_${probe}`,
          sender_agent_id: sender.agentId,
          recipient_agent_ids: [recipient.agentId],
          payload: {
            probe,
            ok: true,
          },
        }),
      );
    });
    senderWs.addEventListener("error", (event) => fail("sender websocket error", event));
  });

  recipientWs.addEventListener("message", (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }

    if (data.probe === probe && data.ok === true) {
      clearTimeout(timeout);
      console.log(JSON.stringify({ ok: true, probe, recipient_agent_id: recipient.agentId }));
      senderWs?.close();
      recipientWs?.close();
      process.exit(0);
    }
  });

  recipientWs.addEventListener("error", (event) => fail("recipient websocket error", event));
} catch (error) {
  clearTimeout(timeout);
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}

async function registerAgent(role) {
  const response = await fetch(`${messageApiUrl.replace(/\/$/, "")}/agent-registrations`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      handle: `@router-smoke-${role}-${probe}:seagull.local`,
      display_name: `Router ${role}`,
      scopes,
      name: `router ${role} smoke runtime`,
      node_id: "router-smoke",
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`agent registration failed for ${role}: HTTP ${response.status} ${body}`);
  }
  const data = await response.json();
  if (!data?.token || !data?.agent?.agent_id) {
    throw new Error(`agent registration response for ${role} is missing token or agent_id`);
  }
  return { token: data.token, agentId: data.agent.agent_id };
}

function websocketUrl(url, agentId, token) {
  const parsed = new URL(url);
  parsed.searchParams.set("agent_id", agentId);
  parsed.searchParams.set("access_token", token);
  return parsed.toString();
}

function fail(label, event) {
  clearTimeout(timeout);
  senderWs?.close();
  recipientWs?.close();
  console.error(label, event.message || event.type);
  process.exit(1);
}
