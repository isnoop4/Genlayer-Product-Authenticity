// Binding between what the page DISPLAYS and what an action SUBMITS.
// Pure logic, no DOM, no SDK: shared by index.html and test-binding.html.
//
// Guarantees:
//  1. Lookups are sequence-tokened: only the latest lookup may update the display;
//     delayed or out-of-order responses are dropped.
//  2. Actions are locked while the latest lookup is pending.
//  3. The product id and the expected_status of an action always come from the
//     displayed product, never from a free text field.
//  4. If the displayed product and the action id differ, the action aborts.
//  5. Right before the transaction is sent, guard() re-checks that the display
//     did not change in the meantime (fee estimation is async).
//  6. After a write the display is stale until it is looked up again.

export const ACTION_RULES = {
  verify_authenticity: "PENDING",
  update_evidence: "REJECTED",
  challenge_product: "VERIFIED",
  resolve_challenge: "DISPUTED",
  appeal: "RULED",
  finalize: "RULED",
};

export class BindingError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "BindingError";
    this.code = code;
  }
}

export function createBinder(fetchProduct) {
  let seq = 0;
  let pending = false;
  let displayed = null; // { id, status, product }
  let stale = false;
  let busy = false;

  async function lookup(requestedId) {
    const id = String(requestedId ?? "").trim();
    const token = ++seq;
    pending = true;
    try {
      const product = await fetchProduct(id);
      if (token !== seq) return { dropped: true }; // a newer lookup exists
      if (!product || product.product_id !== id) {
        throw new BindingError("ID_MISMATCH", "response is for a different product");
      }
      displayed = { id: product.product_id, status: product.status, product };
      stale = false;
      pending = false;
      return { dropped: false, displayed };
    } catch (e) {
      if (token !== seq) return { dropped: true };
      displayed = null; // never keep showing a product that failed to refresh
      stale = false;
      pending = false;
      throw e;
    }
  }

  async function act(action, requestedId, send) {
    if (pending) throw new BindingError("LOOKUP_PENDING", "a lookup is still pending");
    if (!displayed) throw new BindingError("NO_PRODUCT", "no product is displayed");
    if (stale) throw new BindingError("STALE", "display is stale, reload the product first");
    if (busy) throw new BindingError("BUSY", "another action is in flight");
    if (String(requestedId ?? "").trim() !== displayed.id) {
      throw new BindingError("ID_MISMATCH", "action id differs from the displayed product");
    }
    const need = ACTION_RULES[action];
    if (!need) throw new BindingError("UNKNOWN_ACTION", "unknown action " + action);
    if (displayed.status !== need) {
      throw new BindingError("BAD_STATUS", `${action} needs ${need}, displayed is ${displayed.status}`);
    }

    const snap = { id: displayed.id, status: displayed.status, token: seq };
    const guard = () => {
      if (!displayed || displayed.id !== snap.id || seq !== snap.token || pending) {
        throw new BindingError("DISPLAY_CHANGED", "displayed product changed before sending");
      }
    };

    busy = true;
    try {
      return await send(snap.id, snap.status, guard);
    } finally {
      busy = false;
      stale = true; // chain state may have changed, force a reload
    }
  }

  return {
    lookup,
    act,
    get displayed() { return displayed; },
    get pending() { return pending; },
    get stale() { return stale; },
    get busy() { return busy; },
  };
}
