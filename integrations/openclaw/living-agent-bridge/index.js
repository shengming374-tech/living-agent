import { createHash } from "node:crypto";

const PLUGIN_ID = "living-agent-bridge";
const DEFAULTS = Object.freeze({
  endpoint: "http://127.0.0.1:8765/v1/adapters/openclaw/messages",
  token: "",
  tokenEnv: "LIVING_AGENT_OPENCLAW_BRIDGE_TOKEN",
  channelId: "openclaw-weixin",
  allowedAccountIds: [],
  timeoutMs: 90000,
  followupDelayMs: 450,
  maxMessageChars: 12000,
  allowRemoteEndpoint: false,
});

const STATE = {
  installed: false,
  config: null,
  logger: null,
  stats: {
    startedAt: Date.now(),
    claimed: 0,
    replied: 0,
    followupsSent: 0,
    followupFailures: 0,
    followupsCancelled: 0,
    staleResponses: 0,
    deliveryReceipts: 0,
    deliveryReceiptFailures: 0,
    lastReceiptErrorCode: null,
    observed: 0,
    rejected: 0,
    failures: 0,
    lastInboundAt: 0,
    lastSuccessAt: 0,
    lastErrorCode: null,
  },
};

function text(value, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function boundedInteger(value, fallback, minimum, maximum) {
  return Number.isInteger(value) && value >= minimum && value <= maximum ? value : fallback;
}

export function normalizeConfig(raw = {}, environment = process.env) {
  const value = raw && typeof raw === "object" ? raw : {};
  const tokenEnv = text(value.tokenEnv, DEFAULTS.tokenEnv).trim() || DEFAULTS.tokenEnv;
  if (!/^[A-Z_][A-Z0-9_]*$/.test(tokenEnv)) {
    throw new Error("token_env_invalid");
  }
  const endpoint = new URL(text(value.endpoint, DEFAULTS.endpoint));
  if (endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
    throw new Error("endpoint_credentials_or_query_forbidden");
  }
  if (!new Set(["http:", "https:"]).has(endpoint.protocol)) {
    throw new Error("endpoint_scheme_invalid");
  }
  const allowRemoteEndpoint = value.allowRemoteEndpoint === true;
  const loopback = new Set(["127.0.0.1", "localhost", "::1"]).has(endpoint.hostname);
  if (!loopback && (!allowRemoteEndpoint || endpoint.protocol !== "https:")) {
    throw new Error("remote_endpoint_forbidden");
  }
  const token = text(value.token).trim() || text(environment[tokenEnv]).trim();
  const channelId = text(value.channelId, DEFAULTS.channelId).trim();
  if (!channelId || channelId.length > 100) {
    throw new Error("channel_id_invalid");
  }
  const allowedAccountIds = Array.isArray(value.allowedAccountIds)
    ? value.allowedAccountIds.map((item) => text(item).trim()).filter(Boolean)
    : [];
  return {
    endpoint: endpoint.toString(),
    token,
    tokenEnv,
    channelId,
    allowedAccountIds: new Set(allowedAccountIds),
    timeoutMs: boundedInteger(value.timeoutMs, DEFAULTS.timeoutMs, 1000, 120000),
    followupDelayMs: boundedInteger(value.followupDelayMs, DEFAULTS.followupDelayMs, 100, 5000),
    maxMessageChars: boundedInteger(
      value.maxMessageChars,
      DEFAULTS.maxMessageChars,
      1,
      100000,
    ),
    allowRemoteEndpoint,
  };
}

function stableMessageId(event, context, content) {
  const explicit = text(context?.messageId).trim();
  if (explicit) return explicit.slice(0, 255);
  const identity = JSON.stringify([
    text(context?.channelId || event?.channel),
    text(context?.accountId),
    text(context?.conversationId),
    text(context?.senderId || event?.senderId),
    Number.isFinite(event?.timestamp) ? event.timestamp : 0,
    content,
  ]);
  return createHash("sha256").update(identity).digest("hex");
}

function sessionIdentity(channelId, accountId, sessionKey) {
  if (!sessionKey) return "";
  const digest = createHash("sha256")
    .update(JSON.stringify([channelId, accountId, sessionKey]))
    .digest("hex");
  return `session-${digest}`;
}

export function buildBridgeRequest(event, context, config) {
  const channelId = text(context?.channelId || event?.channel).trim();
  if (channelId !== config.channelId) return null;
  const accountId = text(context?.accountId || event?.accountId).trim();
  if (config.allowedAccountIds.size > 0 && !config.allowedAccountIds.has(accountId)) {
    return { rejected: "account_not_allowed" };
  }
  const sessionKey = text(context?.sessionKey || event?.sessionKey).trim();
  const directFallback = sessionIdentity(channelId, accountId, sessionKey);
  const explicitConversationId = text(
    context?.conversationId || event?.conversationId,
  ).trim();
  const explicitSenderId = text(context?.senderId || event?.senderId).trim();
  const conversationId = explicitConversationId || explicitSenderId || directFallback;
  const senderId = explicitSenderId || explicitConversationId || directFallback;
  const content = text(event?.content || event?.body).trim();
  const missingFields = [];
  if (!accountId) missingFields.push("account_id");
  if (!conversationId) missingFields.push("conversation_id");
  if (!senderId) missingFields.push("sender_id");
  if (!content) missingFields.push("content");
  if (missingFields.length > 0) {
    return { rejected: "required_field_missing", missingFields };
  }
  if (content.length > config.maxMessageChars) {
    return { rejected: "message_too_large" };
  }
  const timestampMs = Number.isFinite(event?.timestamp)
    ? Math.max(0, Math.trunc(event.timestamp))
    : Date.now();
  return {
    deliveryTarget: explicitConversationId || explicitSenderId || "",
    payload: {
      protocol_version: 1,
      channel_id: channelId,
      account_id: accountId,
      conversation_id: conversationId,
      sender_id: senderId,
      sender_name: text(event?.senderName).slice(0, 200) || null,
      message_id: stableMessageId(event, context, content),
      content,
      timestamp_ms: timestampMs,
      is_group: event?.isGroup === true,
      session_key: sessionKey.slice(0, 500) || null,
      run_id: text(context?.runId).slice(0, 100) || null,
    },
  };
}

function validResponse(value) {
  const messages = responseMessages(value);
  const primaryMessage = typeof value?.message === "string" ? value.message.trim() : null;
  const explicitMessagesValid =
    value?.messages === undefined ||
    (Array.isArray(value.messages) &&
      value.messages.length <= 3 &&
      value.messages.every(
        (item) => typeof item === "string" && item.trim() && item.length <= 4000,
      ));
  const primaryMatches =
    value?.message === null
      ? messages.length === 0
      : primaryMessage !== null && messages.length > 0 && messages[0] === primaryMessage;
  const utteranceSessionValid =
    value?.utterance_session_id === undefined ||
    value.utterance_session_id === null ||
    (typeof value.utterance_session_id === "string" &&
      value.utterance_session_id.length > 0 &&
      value.utterance_session_id.length <= 255);
  const unitDelaysValid =
    value?.unit_delays_ms === undefined ||
    (Array.isArray(value.unit_delays_ms) &&
      value.unit_delays_ms.length === messages.length &&
      value.unit_delays_ms.every(
        (item) => Number.isInteger(item) && item >= 0 && item <= 10000,
      ));
  return (
    value &&
    typeof value === "object" &&
    value.protocol_version === 1 &&
    value.handled === true &&
    (value.message === null || (primaryMessage !== null && value.message.length <= 4000)) &&
    explicitMessagesValid &&
    primaryMatches &&
    messages.length <= 3 &&
    utteranceSessionValid &&
    unitDelaysValid &&
    (messages.length <= 1 || typeof value.utterance_session_id === "string") &&
    typeof value.reason_code === "string"
  );
}

function responseUnitDelays(value, messages, fallbackDelayMs) {
  if (
    Array.isArray(value?.unit_delays_ms) &&
    value.unit_delays_ms.length === messages.length
  ) {
    return value.unit_delays_ms;
  }
  return messages.map((_message, index) => (index === 0 ? 0 : fallbackDelayMs));
}

function responseMessages(value) {
  if (Array.isArray(value?.messages)) {
    if (!value.messages.every((item) => typeof item === "string")) return [];
    const messages = value.messages.map((item) => item.trim()).filter(Boolean);
    if (messages.length > 0) return messages.slice(0, 3);
  }
  return typeof value?.message === "string" && value.message.trim()
    ? [value.message.trim()]
    : [];
}

async function postToLivingAgent(payload, config, fetchImpl) {
  if (!config.token) throw new Error("token_missing");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.timeoutMs);
  timeout.unref?.();
  try {
    const response = await fetchImpl(config.endpoint, {
      method: "POST",
      headers: {
        authorization: `Bearer ${config.token}`,
        "content-type": "application/json",
        "x-living-agent-bridge-version": "1",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`http_${response.status}`);
    const raw = await response.text();
    if (raw.length > 65536) throw new Error("response_too_large");
    let decoded;
    try {
      decoded = JSON.parse(raw);
    } catch {
      throw new Error("response_invalid_json");
    }
    if (!validResponse(decoded)) throw new Error("response_schema_invalid");
    return decoded;
  } finally {
    clearTimeout(timeout);
  }
}

async function postDeliveryToLivingAgent(payload, config, fetchImpl) {
  if (!config.token) throw new Error("token_missing");
  const endpoint = new URL(config.endpoint);
  endpoint.pathname = endpoint.pathname.replace(/\/messages\/?$/, "/deliveries");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.timeoutMs);
  timeout.unref?.();
  try {
    const response = await fetchImpl(endpoint.toString(), {
      method: "POST",
      headers: {
        authorization: `Bearer ${config.token}`,
        "content-type": "application/json",
        "x-living-agent-bridge-version": "1",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`delivery_http_${response.status}`);
    const raw = await response.text();
    if (raw.length > 4096) throw new Error("delivery_response_too_large");
    let decoded;
    try {
      decoded = JSON.parse(raw);
    } catch {
      throw new Error("delivery_response_invalid_json");
    }
    if (decoded?.accepted !== true || typeof decoded.reason_code !== "string") {
      throw new Error("delivery_response_schema_invalid");
    }
  } finally {
    clearTimeout(timeout);
  }
}

function safeErrorCode(error) {
  if (error && typeof error.message === "string" && /^[a-z0-9_]+$/i.test(error.message)) {
    return error.message.slice(0, 80);
  }
  if (error && error.name === "AbortError") return "request_timeout";
  return "bridge_request_failed";
}

export function createBeforeDispatchHandler(options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const configProvider = options.configProvider || (() => STATE.config);
  const stats = options.stats || STATE.stats;
  const logger = options.logger || STATE.logger;
  const sendFollowup = options.sendFollowup;
  const reportDelivery =
    options.reportDelivery || ((payload, config) => postDeliveryToLivingAgent(payload, config, fetchImpl));
  const scheduleImpl = options.scheduleImpl || ((callback, delayMs) => setTimeout(callback, delayMs));
  const clearScheduleImpl = options.clearScheduleImpl || ((timer) => clearTimeout(timer));
  const pendingByConversation = new Map();
  const activeRequests = new Map();

  function conversationKey(built) {
    return JSON.stringify([
      built.payload.channel_id,
      built.payload.account_id,
      built.payload.conversation_id,
    ]);
  }

  function cancelPending(key) {
    const pending = pendingByConversation.get(key);
    if (!pending) return;
    pending.cancelled = true;
    for (const timer of pending.timers) clearScheduleImpl(timer);
    stats.followupsCancelled = (stats.followupsCancelled || 0) + pending.timers.size;
    pendingByConversation.delete(key);
  }

  async function reportUnitDelivery(response, built, unitIndex, config) {
    if (typeof response.utterance_session_id !== "string") return true;
    try {
      await reportDelivery(
        {
          protocol_version: 1,
          channel_id: built.payload.channel_id,
          account_id: built.payload.account_id,
          conversation_id: built.payload.conversation_id,
          utterance_session_id: response.utterance_session_id,
          unit_index: unitIndex,
        },
        config,
      );
      stats.deliveryReceipts = (stats.deliveryReceipts || 0) + 1;
      stats.lastReceiptErrorCode = null;
      return true;
    } catch (receiptError) {
      stats.deliveryReceiptFailures = (stats.deliveryReceiptFailures || 0) + 1;
      stats.lastReceiptErrorCode = safeErrorCode(receiptError);
      logger?.error?.(
        `[${PLUGIN_ID}] delivery receipt failed: ${stats.lastReceiptErrorCode}`,
      );
      return false;
    }
  }

  return async (event, context) => {
    const config = configProvider();
    if (!config) {
      stats.failures += 1;
      stats.lastErrorCode = "config_unavailable";
      return { handled: true };
    }
    const built = buildBridgeRequest(event, context, config);
    if (built === null) return;
    stats.claimed += 1;
    stats.lastInboundAt = Date.now();
    if (built.rejected) {
      stats.rejected += 1;
      stats.lastErrorCode = built.rejected;
      const fields = built.missingFields?.length
        ? ` fields=${built.missingFields.join(",")}`
        : "";
      logger?.warn?.(`[${PLUGIN_ID}] inbound rejected: ${built.rejected}${fields}`);
      return { handled: true };
    }
    const key = conversationKey(built);
    const requestToken = {};
    cancelPending(key);
    activeRequests.set(key, requestToken);
    try {
      const response = await postToLivingAgent(built.payload, config, fetchImpl);
      if (activeRequests.get(key) !== requestToken) {
        stats.staleResponses = (stats.staleResponses || 0) + 1;
        return { handled: true };
      }
      stats.lastSuccessAt = Date.now();
      stats.lastErrorCode = null;
      const messages = responseMessages(response);
      if (messages.length > 0) {
        stats.replied += 1;
        await reportUnitDelivery(response, built, 0, config);
        if (activeRequests.get(key) !== requestToken) {
          stats.staleResponses = (stats.staleResponses || 0) + 1;
          return { handled: true };
        }
        if (messages.length > 1 && built.deliveryTarget && typeof sendFollowup === "function") {
          const pending = { cancelled: false, timers: new Set() };
          pendingByConversation.set(key, pending);
          const delays = responseUnitDelays(response, messages, config.followupDelayMs);
          let cumulativeDelayMs = 0;
          messages.slice(1).forEach((message, index) => {
            cumulativeDelayMs += delays[index + 1];
            const scheduledDelayMs = cumulativeDelayMs;
            let timer;
            timer = scheduleImpl(async () => {
              if (pending.cancelled || pendingByConversation.get(key) !== pending) return;
              pending.timers.delete(timer);
              if (pending.timers.size === 0) pendingByConversation.delete(key);
              try {
                await sendFollowup({
                  channelId: built.payload.channel_id,
                  accountId: built.payload.account_id,
                  to: built.deliveryTarget,
                  text: message,
                });
                stats.followupsSent = (stats.followupsSent || 0) + 1;
                await reportUnitDelivery(response, built, index + 1, config);
              } catch (error) {
                stats.followupFailures = (stats.followupFailures || 0) + 1;
                stats.lastErrorCode = safeErrorCode(error);
                logger?.error?.(`[${PLUGIN_ID}] follow-up send failed: ${stats.lastErrorCode}`);
              }
            }, scheduledDelayMs);
            pending.timers.add(timer);
            timer?.unref?.();
          });
        }
        const first =
          messages.length > 1 && (!built.deliveryTarget || typeof sendFollowup !== "function")
            ? messages.join("\n")
            : messages[0];
        return { handled: true, text: first };
      }
      stats.observed += 1;
      return { handled: true };
    } catch (error) {
      const code = safeErrorCode(error);
      stats.failures += 1;
      stats.lastErrorCode = code;
      logger?.error?.(`[${PLUGIN_ID}] LivingAgent request failed: ${code}`);
      return { handled: true };
    } finally {
      if (activeRequests.get(key) === requestToken) activeRequests.delete(key);
    }
  };
}

function createRuntimeFollowupSender(api) {
  return async ({ channelId, accountId, to, text: message }) => {
    const adapter = await api.runtime?.channel?.outbound?.loadAdapter?.(channelId);
    if (!adapter?.sendText) throw new Error("outbound_unavailable");
    await adapter.sendText({
      cfg: api.config,
      to,
      text: message,
      accountId,
    });
  };
}

function statusSnapshot() {
  return {
    pluginId: PLUGIN_ID,
    installed: STATE.installed,
    configured: STATE.config !== null && Boolean(STATE.config.token),
    channelId: STATE.config?.channelId ?? null,
    endpoint: STATE.config?.endpoint ?? null,
    allowedAccountIds: STATE.config ? [...STATE.config.allowedAccountIds] : [],
    failMode: "silent",
    stats: { ...STATE.stats },
  };
}

export function register(api) {
  STATE.logger = api?.logger ?? null;
  try {
    STATE.config = normalizeConfig(api?.pluginConfig ?? {});
    STATE.stats.lastErrorCode = STATE.config.token ? null : "token_missing";
  } catch (error) {
    STATE.config = null;
    STATE.stats.lastErrorCode = safeErrorCode(error);
  }
  if (STATE.installed) return;

  api.on(
    "before_dispatch",
    createBeforeDispatchHandler({ sendFollowup: createRuntimeFollowupSender(api) }),
    { priority: 100 },
  );
  api.registerGatewayMethod(
    "livingAgentBridge.status",
    async ({ respond }) => respond(true, statusSnapshot()),
    { scope: "operator.read" },
  );
  STATE.installed = true;
  api.logger?.info?.(
    `[${PLUGIN_ID}] active channel=${STATE.config?.channelId ?? "invalid"} failMode=silent`,
  );
}

export default { id: PLUGIN_ID, register };
