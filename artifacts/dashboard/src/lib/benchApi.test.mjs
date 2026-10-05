import assert from "node:assert/strict";
import test from "node:test";
import { parseCatalogResponse } from "./benchApi.ts";

test("empty gateway responses keep the HTTP status and explain the missing body", async () => {
  await assert.rejects(
    parseCatalogResponse(new Response("", { status: 502, statusText: "Bad Gateway" })),
    /HTTP 502 Bad Gateway: The server returned an empty response body/,
  );
});

test("structured API failures prefer the readable detail message", async () => {
  const response = new Response(
    JSON.stringify({ detail: { message: "Strategy Bench is disabled on the live site." } }),
    { status: 403, statusText: "Forbidden" },
  );
  await assert.rejects(
    parseCatalogResponse(response),
    /HTTP 403 Forbidden: Strategy Bench is disabled on the live site/,
  );
});

test("HTML gateway errors are stripped to readable text", async () => {
  const response = new Response(
    "<html><title>Bad Gateway</title><body>upstream unavailable</body></html>",
    { status: 502, statusText: "Bad Gateway" },
  );
  await assert.rejects(
    parseCatalogResponse(response),
    /HTTP 502 Bad Gateway: Bad Gateway upstream unavailable/,
  );
});

test("valid catalog JSON is returned", async () => {
  const catalog = { experiments: [], exploration_runs: [] };
  const response = new Response(JSON.stringify(catalog), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
  assert.deepEqual(await parseCatalogResponse(response), catalog);
});