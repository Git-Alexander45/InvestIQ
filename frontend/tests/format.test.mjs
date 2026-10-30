import assert from "node:assert/strict";
import { test } from "node:test";
import { fmtNum, fmtPct, tone } from "../lib/format.ts";

test("formats missing values as a dash, never as zero", () => {
  assert.equal(fmtNum(null), "—");
  assert.equal(fmtPct(undefined), "—");
});

test("signs and tones", () => {
  assert.equal(fmtPct(1.234), "+1.23%");
  assert.equal(fmtPct(-2), "-2.00%");
  assert.equal(tone(0.1), "up");
  assert.equal(tone(-0.1), "down");
  assert.equal(tone(null), "");
});
