import { createBinder, BindingError } from "./binding.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const prod = (id, status) => ({ product_id: id, status });

// plan: one entry per fetch call, consumed in call order
function fetcher(plan) {
  let i = 0;
  return async (id) => {
    const p = plan[i++] || {};
    if (p.delay) await sleep(p.delay);
    if (p.fail) throw new Error("not registered");
    return prod(p.reply ?? id, p.status ?? "VERIFIED");
  };
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}
async function rejects(promise, code) {
  try {
    await promise;
  } catch (e) {
    assert(e instanceof BindingError && e.code === code, `expected ${code}, got ${e && (e.code || e.message)}`);
    return;
  }
  throw new Error(`expected ${code}, but it resolved`);
}

function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

export const tests = [
  ["1. lookup binds displayed id and status", async () => {
    const b = createBinder(fetcher([{ status: "DISPUTED" }]));
    await b.lookup("P-1");
    assert(b.displayed.id === "P-1" && b.displayed.status === "DISPUTED");
    assert(!b.pending);
  }],

  ["2. delayed or out-of-order lookups never overwrite the latest one", async () => {
    // older answers LATER than newer
    const a = createBinder(fetcher([{ delay: 40, status: "VERIFIED" }, { delay: 0, status: "DISPUTED" }]));
    const p1 = a.lookup("OLD");
    const p2 = a.lookup("NEW");
    const [r1] = await Promise.all([p1, p2]);
    assert(r1.dropped === true, "old lookup should be dropped");
    assert(a.displayed.id === "NEW" && a.displayed.status === "DISPUTED", "NEW must stay displayed");
    // older answers EARLIER than newer
    const c = createBinder(fetcher([{ delay: 0 }, { delay: 30 }]));
    const q1 = c.lookup("A");
    const q2 = c.lookup("B");
    await Promise.all([q1, q2]);
    assert(c.displayed.id === "B");
  }],

  ["3. actions are locked while a lookup is pending", async () => {
    const b = createBinder(fetcher([{}, { delay: 30 }]));
    await b.lookup("P-1");
    const p = b.lookup("P-1");
    assert(b.pending === true);
    await rejects(b.act("challenge_product", "P-1", async () => {}), "LOOKUP_PENDING");
    await p;
    assert(!b.pending);
  }],

  ["4. action id that differs from the displayed id aborts", async () => {
    const b = createBinder(fetcher([{ status: "VERIFIED" }]));
    await b.lookup("P-1");
    let sent = false;
    await rejects(b.act("challenge_product", "P-2", async () => { sent = true; }), "ID_MISMATCH");
    assert(!sent, "send must not run");
  }],

  ["5. id and expected_status come from the displayed product", async () => {
    const b = createBinder(fetcher([{ status: "RULED" }]));
    await b.lookup("P-9");
    let got;
    await b.act("finalize", "P-9", async (id, status) => { got = { id, status }; });
    assert(got.id === "P-9" && got.status === "RULED");
  }],

  ["6. an action not allowed for the displayed status is blocked", async () => {
    const b = createBinder(fetcher([{ status: "PENDING" }]));
    await b.lookup("P-1");
    await rejects(b.act("challenge_product", "P-1", async () => {}), "BAD_STATUS");
    await rejects(b.act("appeal", "P-1", async () => {}), "BAD_STATUS");
  }],

  ["7. a failed lookup clears the display and blocks actions", async () => {
    const b = createBinder(fetcher([{ status: "VERIFIED" }, { fail: true }]));
    await b.lookup("P-1");
    let threw = false;
    try { await b.lookup("P-2"); } catch { threw = true; }
    assert(threw, "lookup should throw");
    assert(b.displayed === null, "old product must not stay displayed");
    await rejects(b.act("challenge_product", "P-2", async () => {}), "NO_PRODUCT");
  }],

  ["8. guard aborts when the display changes while the tx is being prepared", async () => {
    const b = createBinder(fetcher([{ status: "VERIFIED" }, { status: "VERIFIED" }]));
    await b.lookup("P-1");
    let wrote = false;
    const run = b.act("challenge_product", "P-1", async (id, status, guard) => {
      await sleep(20);        // fee estimation takes time...
      guard();                // ...and the user switched product meanwhile
      wrote = true;
    });
    await sleep(5);
    await b.lookup("P-2");    // switch display during estimation
    await rejects(run, "DISPLAY_CHANGED");
    assert(!wrote, "no transaction may be sent");
  }],

  ["9. after a write the display is stale until it is looked up again", async () => {
    const b = createBinder(fetcher([{ status: "DISPUTED" }, { status: "RULED" }]));
    await b.lookup("P-1");
    await b.act("resolve_challenge", "P-1", async () => {});
    await rejects(b.act("resolve_challenge", "P-1", async () => {}), "STALE");
    await b.lookup("P-1");
    assert(b.displayed.status === "RULED" && !b.stale);
  }],

  ["10. 200 random delay orders: the last requested product always wins", async () => {
    const rand = rng(42);
    for (let round = 0; round < 200; round++) {
      const n = 2 + Math.floor(rand() * 4);
      const plan = Array.from({ length: n }, () => ({ delay: Math.floor(rand() * 6) }));
      const b = createBinder(fetcher(plan));
      const ps = [];
      for (let i = 0; i < n; i++) ps.push(b.lookup("P-" + i));
      await Promise.all(ps);
      assert(b.displayed.id === "P-" + (n - 1) && !b.pending, `round ${round} diverged`);
    }
  }],
];

export async function runAll() {
  const out = [];
  for (const [name, fn] of tests) {
    try {
      await fn();
      out.push({ name, ok: true });
    } catch (e) {
      out.push({ name, ok: false, error: e.message });
    }
  }
  return out;
}
