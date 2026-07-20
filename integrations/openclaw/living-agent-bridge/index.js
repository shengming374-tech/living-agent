import { createHash } from "node:crypto";

const PLUGIN_ID = "living-agent-bridge";
const DEFAULTS = Object.freeze({
  endpoint: "http://127.0.0.1:8765/v1/adapters/openclaw/messages",
  token: "",
  tokenEnv: "LIVING_AGENT_OPENCLAW_BRIDGE_TOKEN",
  channelId: "openclaw-weixin",
  allowedAccountIds: [],
  timeoutMs: 15000,
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
    timeoutMs: boundedInteger(value.timeoutMs, DEFAULTS.timeoutMs, 1000, 60000),
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
  return (
    value &&
    typeof value === "object" &&
    value.protocol_version === 1 &&
    value.handled === true &&
    (value.message === null ||
      (typeof value.message === "string" && value.message.length <= 4000)) &&
    typeof value.reason_code === "string"
  );
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
    try {
      const response = await postToLivingAgent(built.payload, config, fetchImpl);
      stats.lastSuccessAt = Date.now();
      stats.lastErrorCode = null;
      if (typeof response.message === "string" && response.message.trim()) {
        stats.replied += 1;
        return { handled: true, text: response.message };
      }
      stats.observed += 1;
      return { handled: true };
    } catch (error) {
      const code = safeErrorCode(error);
      stats.failures += 1;
      stats.lastErrorCode = code;
      logger?.error?.(`[${PLUGIN_ID}] LivingAgent request failed: ${code}`);
      return { handled: true };
    }
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

  api.on("before_dispatch", createBeforeDispatchHandler(), { priority: 100 });
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
