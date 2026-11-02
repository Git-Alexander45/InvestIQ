import assert from "node:assert/strict";
import { test } from "node:test";
import { proxyTarget, requestAllowed } from "../lib/proxyPath.ts";

const BASE = "http://127.0.0.1:8765";

test("forwards plain API paths with the query string", () => {
  const u = proxyTarget(BASE, ["instruments", "64", "bars"], "?interval=1d");
  assert.equal(u.href, "http://127.0.0.1:8765/api/instruments/64/bars?interval=1d");
});

test("rejects traversal, empty paths and anything that could change host", () => {
  for (const segs of [[], [".."], ["reports", "..", "..", "etc"], ["a b"], ["%2e%2e"], ["http:", "", "evil.com"], ["@evil.com"], ["x?y"]]) {
    assert.equal(proxyTarget(BASE, segs, ""), null, JSON.stringify(segs));
  }
});

const ok = (over) => ({ method: "GET", host: "127.0.0.1:3000", origin: null, secFetchSite: "same-origin", ...over });

test("allows the dashboard's own requests and local tools", () => {
  assert.equal(requestAllowed(ok({})), true);
  assert.equal(requestAllowed(ok({ host: "localhost:3000", method: "POST", origin: "http://localhost:3000" })), true);
  assert.equal(requestAllowed(ok({ secFetchSite: null })), true); // curl and other local clients
  assert.equal(requestAllowed(ok({ secFetchSite: "none" })), true); // typed into the address bar
});

test("rejects DNS rebinding and cross-site requests", () => {
  assert.equal(requestAllowed(ok({ host: "evil.example:3000" })), false);
  assert.equal(requestAllowed(ok({ host: null })), false);
  assert.equal(requestAllowed(ok({ method: "POST", origin: "https://evil.example", secFetchSite: null })), false);
  assert.equal(requestAllowed(ok({ method: "POST", secFetchSite: "cross-site" })), false);
  assert.equal(requestAllowed(ok({ method: "PUT", secFetchSite: "same-site", origin: "http://127.0.0.1:3001" })), false);
  assert.equal(requestAllowed(ok({ method: "POST", origin: "null", secFetchSite: null })), false);
});
