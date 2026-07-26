// Guards the one duplicated thing in this package: the task lifecycle table.
//
// gulls owns task state (packages/gulls/packages/protocol/src/seagull_protocol/
// work.py) and the hub re-checks every transition. The TypeScript copy exists
// only so a product surface can grey out an impossible action locally. A copy
// that silently drifts is worse than no copy, so parse the Python table and
// assert the two agree exactly.

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  TASK_INACTIVE_STATES,
  TASK_LIFECYCLE_TRANSITIONS,
  type TaskState,
} from "../src/agent-request.ts";

const WORK_PY = fileURLToPath(
  new URL(
    "../../../../gulls/packages/protocol/src/seagull_protocol/work.py",
    import.meta.url,
  ),
);

/** Extract TASK_LIFECYCLE_TRANSITIONS from work.py without running Python. */
function parsePythonTransitions(source: string): Record<string, string[]> {
  const start = source.indexOf("TASK_LIFECYCLE_TRANSITIONS");
  assert.ok(start >= 0, "TASK_LIFECYCLE_TRANSITIONS not found in work.py");
  const open = source.indexOf("{", start);
  let depth = 0;
  let end = open;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const block = source.slice(open + 1, end);

  // Each entry reads `TaskState.NAME: (TaskState.A, TaskState.B,)` or `(...)`
  // on one line. Strip newlines so both layouts parse the same way.
  const flat = block.replace(/\s+/g, " ");
  const entries: Record<string, string[]> = {};
  const entryRe = /TaskState\.([A-Z_]+)\s*:\s*\(([^)]*)\)/g;
  let match: RegExpExecArray | null;
  while ((match = entryRe.exec(flat)) !== null) {
    const targets = [...match[2].matchAll(/TaskState\.([A-Z_]+)/g)].map((m) => m[1]);
    entries[match[1]] = targets;
  }
  return entries;
}

/** TaskState.RESULT_READY -> "result_ready" */
function toValue(name: string): TaskState {
  return name.toLowerCase() as TaskState;
}

describe("task lifecycle parity with seagull_protocol", () => {
  const python = parsePythonTransitions(readFileSync(WORK_PY, "utf8"));

  it("parsed the Python table at all", () => {
    // Guards the parser itself: if work.py's formatting changes so this stops
    // matching, fail loudly rather than vacuously passing on an empty table.
    assert.ok(Object.keys(python).length >= 10, "parsed too few Python states");
    assert.deepEqual(python.RELEASED, ["COMPLETED"]);
  });

  it("covers exactly the same states", () => {
    const fromPython = Object.keys(python).map(toValue).sort();
    const fromTypeScript = Object.keys(TASK_LIFECYCLE_TRANSITIONS).sort();
    assert.deepEqual(fromTypeScript, fromPython);
  });

  it("has identical transitions for every state", () => {
    for (const [name, targets] of Object.entries(python)) {
      const state = toValue(name);
      assert.deepEqual(
        [...TASK_LIFECYCLE_TRANSITIONS[state]],
        targets.map(toValue),
        `transitions diverged for ${state}`,
      );
    }
  });

  it("agrees with the Python terminal states", () => {
    // TASK_INACTIVE_STATES lives in message_hub, but it is derivable: a state
    // is inactive when nothing follows it. `failed` is the deliberate
    // exception -- it can still be disputed, yet counts as finished.
    const terminal = Object.entries(python)
      .filter(([, targets]) => targets.length === 0)
      .map(([name]) => toValue(name));

    for (const state of terminal) {
      assert.ok(TASK_INACTIVE_STATES.has(state), `${state} should be inactive`);
    }
    assert.ok(TASK_INACTIVE_STATES.has("failed"));
    assert.ok(!TASK_INACTIVE_STATES.has("running"));
  });
});
