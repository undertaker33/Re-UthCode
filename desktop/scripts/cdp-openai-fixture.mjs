#!/usr/bin/env node

/**
 * Local OpenAI-compatible HTTP fixture for the real Desktop runtime.
 *
 * It intentionally speaks only the public Chat Completions wire format.  The
 * production Provider, Core, Application, Bridge, and Renderer remain the
 * code under test; this process only supplies deterministic local responses.
 *
 * Examples (the launcher is mandatory so state is isolated before spawn):
 *   node scripts/cdp-launcher.mjs -- node scripts/cdp-openai-fixture.mjs --port 8765 --scenario stream
 *   node scripts/cdp-launcher.mjs -- node scripts/cdp-openai-fixture.mjs --port 8765 --scenario tool
 */

import { createServer } from "node:http";
import { appendFile, writeFile } from "node:fs/promises";
import { assertCdpEnvironmentIsolated } from "./cdp-test-guard.mjs";

function option(name, fallback = undefined) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] ?? fallback : fallback;
}

const port = Number(option("port", "0"));
const scenario = option("scenario", "stream");
const logPath = option("log");
const readyFile = option("ready-file");
const delayMs = Number(option("delay-ms", "1200"));
let requestCount = 0;

try {
  assertCdpEnvironmentIsolated({
    label: "cdp-openai-fixture",
    outputPaths: [logPath, readyFile].filter(Boolean),
  });
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`cdp-openai-fixture isolation_failure: ${message}\n`);
  process.exit(1);
}

function log(event, details = {}) {
  const line = JSON.stringify({
    at: new Date().toISOString(),
    event,
    ...details,
  });
  process.stdout.write(`${line}\n`);
  if (logPath) void appendFile(logPath, `${line}\n`, "utf8");
}

async function bodyOf(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function json(response, status, value) {
  const rendered = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(rendered),
    "cache-control": "no-store",
  });
  response.end(rendered);
}

function chunk(delta, finishReason = null, usage = null) {
  return {
    id: "chatcmpl-uthcode-fixture",
    object: "chat.completion.chunk",
    created: 1,
    model: "fixture-model",
    choices: [{ index: 0, delta, finish_reason: finishReason }],
    usage,
  };
}

function fixtureChunks(requestBody) {
  const messages = Array.isArray(requestBody.messages) ? requestBody.messages : [];
  const hasToolResult = messages.some((message) => message?.role === "tool");
  const hasToolDefinitions = Array.isArray(requestBody.tools) && requestBody.tools.length > 0;
  if (scenario === "tool" && hasToolDefinitions && !hasToolResult) {
    return [
      chunk({ role: "assistant" }),
      chunk({
        tool_calls: [{
          index: 0,
          id: "call-uthcode-fixture",
          type: "function",
          function: { name: "ReadFile", arguments: "{\"path\":\"README.md\"}" },
        }],
      }),
      chunk({}, "tool_calls", { prompt_tokens: 2, completion_tokens: 2, total_tokens: 4 }),
    ];
  }
  if (scenario === "ask" && hasToolDefinitions && !hasToolResult) {
    return [
      chunk({ role: "assistant" }),
      chunk({
        tool_calls: [{
          index: 0,
          id: "call-uthcode-ask",
          type: "function",
          function: {
            name: "AskUserQuestion",
            arguments: JSON.stringify({
              questions: [
                {
                  question_id: "fixture-choice",
                  header: "Fixture choice",
                  question: "Which local fixture path should continue?",
                  kind: "single_select",
                  options: [
                    { label: "stream", description: "Continue the streaming path" },
                    { label: "other", description: "Provide another path" },
                  ],
                  allow_other: true,
                },
                {
                  question_id: "fixture-note",
                  header: "Fixture note",
                  question: "Add a note for this run.",
                  kind: "text",
                },
                {
                  question_id: "fixture-tags",
                  header: "Fixture tags",
                  question: "Which local paths should be included?",
                  kind: "multi_select",
                  options: [
                    { label: "README", description: "Include the README path" },
                    { label: "tests", description: "Include the tests path" },
                  ],
                  allow_other: true,
                },
              ],
            }),
          },
        }],
      }),
      chunk({}, "tool_calls", { prompt_tokens: 2, completion_tokens: 4, total_tokens: 6 }),
    ];
  }
  if (scenario === "permission" && hasToolDefinitions && !hasToolResult) {
    return [
      chunk({ role: "assistant" }),
      chunk({
        tool_calls: [{
          index: 0,
          id: "call-uthcode-permission",
          type: "function",
          function: { name: "ReadFile", arguments: JSON.stringify({ path: ".env" }) },
        }],
      }),
      chunk({}, "tool_calls", { prompt_tokens: 2, completion_tokens: 2, total_tokens: 4 }),
    ];
  }
  if (scenario === "plan" && hasToolDefinitions && !hasToolResult) {
    return [
      chunk({ role: "assistant" }),
      chunk({
        tool_calls: [{
          index: 0,
          id: "call-uthcode-plan",
          type: "function",
          function: {
            name: "ProposePlan",
            arguments: JSON.stringify({ plan: "Read the fixture README and report the result." }),
          },
        }],
      }),
      chunk({}, "tool_calls", { prompt_tokens: 2, completion_tokens: 4, total_tokens: 6 }),
    ];
  }
  const suffix = hasToolResult ? " tool result accepted" : "";
  return [
    chunk({ role: "assistant" }),
    chunk({ content: `fixture response${suffix}` }),
    chunk({}, "stop", { prompt_tokens: 2, completion_tokens: 3, total_tokens: 5 }),
  ];
}

function sendSse(response, chunks) {
  response.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  for (const value of chunks) response.write(`data: ${JSON.stringify(value)}\n\n`);
  response.end("data: [DONE]\n\n");
}

const server = createServer(async (request, response) => {
  if (request.method === "GET" && request.url === "/health") {
    json(response, 200, { ok: true, scenario, requests: requestCount });
    return;
  }
  const pathname = new URL(request.url ?? "/", "http://127.0.0.1").pathname;
  if (request.method !== "POST" || !pathname.endsWith("/chat/completions")) {
    json(response, 404, { error: { message: "fixture endpoint not found", type: "not_found" } });
    return;
  }

  const requestBody = await bodyOf(request);
  requestCount += 1;
  log("request", {
    count: requestCount,
    path: pathname,
    model: requestBody.model,
    stream: requestBody.stream === true,
    toolCount: Array.isArray(requestBody.tools) ? requestBody.tools.length : 0,
    toolNames: Array.isArray(requestBody.tools) ? requestBody.tools.map((item) => item?.function?.name ?? item?.name).filter((item) => typeof item === "string") : [],
    messageRoles: Array.isArray(requestBody.messages) ? requestBody.messages.map((item) => item?.role) : [],
  });
  const failureRequests = scenario === "retry" ? 3 : 1;
  if ((scenario === "failure" || scenario === "retry") && requestCount <= failureRequests) {
    json(response, 504, {
      error: { message: "local fixture transient timeout", type: "server_error", code: "fixture_504" },
    });
    return;
  }
  if (scenario === "delay") await new Promise((resolve) => setTimeout(resolve, delayMs));
  if (requestBody.stream === true) {
    sendSse(response, fixtureChunks(requestBody));
  } else {
    json(response, 200, {
      id: "chatcmpl-uthcode-fixture",
      object: "chat.completion",
      created: 1,
      model: "fixture-model",
      choices: [{ index: 0, message: { role: "assistant", content: "fixture response" }, finish_reason: "stop" }],
      usage: { prompt_tokens: 2, completion_tokens: 3, total_tokens: 5 },
    });
  }
});

server.on("error", (error) => {
  log("server_error", { message: error instanceof Error ? error.message : String(error) });
  process.exitCode = 1;
});

server.listen(port, "127.0.0.1", async () => {
  const address = server.address();
  const actualPort = typeof address === "object" && address ? address.port : port;
  const ready = { event: "ready", port: actualPort, baseUrl: `http://127.0.0.1:${actualPort}/v1`, scenario };
  log(ready.event, ready);
  if (readyFile) await writeFile(readyFile, `${JSON.stringify(ready)}\n`, "utf8");
});

function close() {
  log("shutdown", { requests: requestCount });
  server.close(() => process.exit());
}
process.once("SIGINT", close);
process.once("SIGTERM", close);
