#!/usr/bin/env node
// Smoke for hub -> router WebSocket push: a recipient connected to the
// message router receives a seagull.delivery.created.v1 event when another
// agent posts a message through the hub REST API.

const baseUrl = process.argv[2];
const messageApiUrl = process.argv[3] || process.env.MESSAGE_API_URL;
if (!baseUrl || !messageApiUrl) {
  console.error("usage: scripts/smoke-hub-push-ws.mjs <websocket-url> <message-api-url>");
  process.exit(2);
}

const probe = `hub-push-smoke-${Date.now()}`;
const scopes = ["agent:read", "agent:inbox", "agent:post", "agent:ack"];
let recipientWs;

const timeout = setTimeout(() => {
  console.error("timed out waiting for pushed delivery.created event");
  recipientWs?.close();
  process.exit(1);
}, 20000);

try {
  const sender = await registerAgent("sender");
  const recipient = await registerAgent("recipient");

  recipientWs = new WebSocket(websocketUrl(baseUrl, recipient.agentId, recipient.token));
  recipientWs.addEventListener("error", (event) => fail("recipient websocket error", event));

  recipientWs.addEventListener("open", async () => {
    try {
      await postMessage(sender, recipient);
    } catch (error) {
      clearTimeout(timeout);
      console.error(error instanceof Error ? error.message : String(error));
      recipientWs?.close();
      process.exit(1);
    }
  });

  recipientWs.addEventListener("message", (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    if (
      data.type === "seagull.delivery.created.v1" &&
      data.data?.recipient_agent_id === recipient.agentId &&
      data.data?.content_inline === `probe ${probe}`
    ) {
      clearTimeout(timeout);
      console.log(
        JSON.stringify({
          ok: true,
          probe,
          delivery_id: data.data.delivery_id,
          recipient_agent_id: recipient.agentId,
        }),
      );
      recipientWs?.close();
      process.exit(0);
    }
  });
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
      handle: `@hub-push-${role}-${probe}:seagull.local`,
      display_name: `Hub push ${role}`,
      scopes,
      name: `hub push ${role} smoke runtime`,
      node_id: "hub-push-smoke",
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`agent registration failed for ${role}: HTTP ${response.status} ${body}`);
  }
  const data = await response.json();
  if (!data?.token || !data?.agent?.agent_id || !data?.agent?.handle) {
    throw new Error(`agent registration response for ${role} is missing token, agent_id, or handle`);
  }
  return { token: data.token, agentId: data.agent.agent_id, handle: data.agent.handle };
}

async function postMessage(sender, recipient) {
  const response = await fetch(`${messageApiUrl.replace(/\/$/, "")}/messages`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${sender.token}`,
    },
    body: JSON.stringify({
      sender_handle: sender.handle,
      recipient_handles: [recipient.handle],
      content: `probe ${probe}`,
      intent: "message",
      visibility: "direct",
    }),
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`message post failed: HTTP ${response.status} ${body}`);
  }
}

function websocketUrl(url, agentId, token) {
  const parsed = new URL(url);
  parsed.searchParams.set("agent_id", agentId);
  parsed.searchParams.set("access_token", token);
  return parsed.toString();
}

function fail(label, event) {
  clearTimeout(timeout);
  recipientWs?.close();
  console.error(label, event.message || event.type);
  process.exit(1);
}
