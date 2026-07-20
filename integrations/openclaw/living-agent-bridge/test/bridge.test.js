import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBridgeRequest,
  createBeforeDispatchHandler,
  normalizeConfig,
} from "../index.js";

const TOKEN = "bridge-test-token";

function config(overrides = {}) {
  return normalizeConfig({ token: TOKEN, ...overrides }, {});
}

function event(overrides = {}) {
  return {
    content: "Hello",
    channel: "openclaw-weixin",
    senderId: "wechat-user",
    senderName: "Owner",
    timestamp: 1784540000000,
    isGroup: false,
    ...overrides,
  };
}

function context(overrides = {}) {
  return {
    channelId: "openclaw-weixin",
    accountId: "wechat-account",
    conversationId: "wechat-conversation",
    senderId: "wechat-user",
    sessionKey: "agent:main:wechat-user",
    ...overrides,
  };
}

function stats() {
  return {
    claimed: 0,
    replied: 0,
    observed: 0,
    rejected: 0,
    failures: 0,
    lastInboundAt: 0,
    lastSuccessAt: 0,
    lastErrorCode: null,
  };
}

test("ignores channels outside the configured OpenClaw channel", async () => {
  let called = false;
  const handler = createBeforeDispatchHandler({
    configProvider: () => config(),
    stats: stats(),
    fetchImpl: async () => {
      called = true;
      throw new Error("unexpected");
    },
  });

  const result = await handler(event({ channel: "telegram" }), context({ channelId: "telegram" }));

  assert.equal(result, undefined);
  assert.equal(called, false);
});

test("sends stable identity metadata and returns a synthetic reply", async () => {
  let request;
  const counters = stats();
  const handler = createBeforeDispatchHandler({
    configProvider: () => config(),
    stats: counters,
    fetchImpl: async (url, options) => {
      request = { url, options };
      return new Response(
        JSON.stringify({
          protocol_version: 1,
          handled: true,
          event_id: "event-1",
          turn: null,
          message: "LivingAgent reply",
          reason_code: "reply_authorized",
        }),
      );
    },
  });

  const result = await handler(event(), context());
  const payload = JSON.parse(request.options.body);

  assert.deepEqual(result, { handled: true, text: "LivingAgent reply" });
  assert.equal(request.url, "http://127.0.0.1:8765/v1/adapters/openclaw/messages");
  assert.equal(request.options.headers.authorization, `Bearer ${TOKEN}`);
  assert.equal(payload.channel_id, "openclaw-weixin");
  assert.equal(payload.account_id, "wechat-account");
  assert.equal(payload.conversation_id, "wechat-conversation");
  assert.equal(payload.sender_id, "wechat-user");
  assert.equal(payload.content, "Hello");
  assert.equal(payload.message_id.length, 64);
  assert.equal(counters.replied, 1);
});

test("message id derivation is deterministic", () => {
  const first = buildBridgeRequest(event(), context(), config());
  const second = buildBridgeRequest(event(), context(), config());

  assert.equal(first.payload.message_id, second.payload.message_id);
});

test("account allowlist rejects before network access", async () => {
  let called = false;
  const counters = stats();
  const handler = createBeforeDispatchHandler({
    configProvider: () => config({ allowedAccountIds: ["allowed-account"] }),
    stats: counters,
    fetchImpl: async () => {
      called = true;
      throw new Error("unexpected");
    },
  });

  const result = await handler(event(), context());

  assert.deepEqual(result, { handled: true });
  assert.equal(called, false);
  assert.equal(counters.lastErrorCode, "account_not_allowed");
});

test("LivingAgent observe response remains handled without text", async () => {
  const counters = stats();
  const handler = createBeforeDispatchHandler({
    configProvider: () => config(),
    stats: counters,
    fetchImpl: async () =>
      new Response(
        JSON.stringify({
          protocol_version: 1,
          handled: true,
          event_id: "event-1",
          turn: null,
          message: null,
          reason_code: "runtime_observed",
        }),
      ),
  });

  assert.deepEqual(await handler(event(), context()), { handled: true });
  assert.equal(counters.observed, 1);
});

test("network and schema failures are silent and never fall back to OpenClaw agent", async () => {
  for (const fetchImpl of [
    async () => {
      throw new Error("socket details must not escape");
    },
    async () => new Response("not-json"),
    async () => new Response(JSON.stringify({ handled: false })),
    async () =>
      new Response(
        JSON.stringify({
          protocol_version: 1,
          handled: true,
          event_id: "event-1",
          turn: null,
          message: "x".repeat(4001),
          reason_code: "reply_authorized",
        }),
      ),
  ]) {
    const counters = stats();
    const handler = createBeforeDispatchHandler({
      configProvider: () => config(),
      stats: counters,
      fetchImpl,
    });

    assert.deepEqual(await handler(event(), context()), { handled: true });
    assert.equal(counters.failures, 1);
  }
});

test("missing token and unsafe remote endpoints fail closed", async () => {
  assert.throws(
    () => normalizeConfig({ endpoint: "http://remote.example/messages", token: TOKEN }, {}),
    /remote_endpoint_forbidden/,
  );
  const counters = stats();
  const handler = createBeforeDispatchHandler({
    configProvider: () => config({ token: "" }),
    stats: counters,
    fetchImpl: async () => {
      throw new Error("unexpected");
    },
  });

  assert.deepEqual(await handler(event(), context()), { handled: true });
  assert.equal(counters.lastErrorCode, "token_missing");
});
