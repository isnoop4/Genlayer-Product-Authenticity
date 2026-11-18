# Product Authenticity Registry

An Intelligent Contract on GenLayer that verifies product-origin claims with web evidence, lets anyone dispute a verified claim, and now puts bonds behind both sides with one appeal round.

| | |
|---|---|
| Network | GenLayer Studio Next (chain 61997, Studio v0.123.0-rc.13, GenVM v0.4) |
| Contract (v2) | `0xcA81E6fc29dd7bCf0d9a14a44D701897E8aB8538` |
| Explorer | https://explorer-studio-next.genlayer.com/address/0xcA81E6fc29dd7bCf0d9a14a44D701897E8aB8538 |
| Frontend | `docs/index.html` (pin the commit SHA when you submit) |
| Regression test | `docs/test-binding.html` (10/10) |

## Versions

- **v0** – each claim gets one final verdict (VERIFIED or REJECTED).
- **v1** – adds `challenge_product` and `resolve_challenge`: validators compare the original and counter-evidence (UPHELD revokes, DISMISSED restores). Contract `0xF03531aE59C9a071a5591eD9764102c5aa377491`, accepted as Milestone v1.
- **v2 (this release)** – bonds and one appeal round.

## What v2 adds

**Bonds (skin in the game).** `deposit(amount)` credits a free balance. `register_product` and `challenge_product` each lock 100 units, `appeal` locks 200. The side that loses pays its bond to the winner.

**One appeal round.** `resolve_challenge` now only issues the round 1 ruling and moves the product to `RULED`. The losing side may call `appeal` once. Round 2 uses a stricter prompt (UPHELD only if the counter-evidence directly contradicts the claim) and settles immediately. Without an appeal, anyone can call `finalize`.

**Stale-state guard.** `challenge_product`, `resolve_challenge`, `appeal` and `finalize` take `expected_status`, so an action sent from an outdated screen is rejected on-chain.

### Status machine

```
PENDING --verify--> VERIFIED | REJECTED
REJECTED --update_evidence (locks 100)--> PENDING
VERIFIED --challenge_product (locks 100)--> DISPUTED
DISPUTED --resolve_challenge--> RULED (round 1)
RULED --finalize--> REVOKED (UPHELD) | VERIFIED (DISMISSED)
RULED --appeal (loser, locks 200)--> round 2 ruling --> REVOKED | VERIFIED
```

### Bond settlement

| Final ruling | Registrant bond | Challenger bond | Appeal bond |
|---|---|---|---|
| UPHELD (revoked) | to challenger | returned | returned to appellant only if the appeal flipped the result, otherwise to the winner |
| DISMISSED (restored) | stays locked behind the claim | to registrant | same rule |

### Contract interface

Writes: `deposit`, `register_product`, `verify_authenticity`, `update_evidence`, `challenge_product(product_id, counter_evidence_url, reason, expected_status)`, `resolve_challenge(product_id, expected_status)`, `appeal(product_id, expected_status)`, `finalize(product_id, expected_status)`.
Views: `get_product`, `get_products(offset, limit)`, `get_products_by_seller`, `get_balance(address)`.

## Frontend and binding fix

The frontend shows deposit and balance, registration, the product certificate with its history timeline, and the context-sensitive actions for the displayed status.

The reviewer asked that challenge, resolve and evidence-update actions be bound to the product currently displayed. `docs/binding.js` does this for every v2 action:

- lookups are sequence-tokened, so delayed or out-of-order responses are dropped;
- actions are locked while a lookup is pending;
- the product id and `expected_status` are read from the displayed product, never from a text field;
- the action aborts if the displayed product and the submitted id differ;
- the send step re-checks the display right before the transaction is written;
- after a write the display is stale until it is reloaded.

`docs/test-binding.html` runs 10 checks against the same module (including 200 random delay orders). Last run: **10/10 pass**. Node: `node docs/run-tests.mjs`.

## Tested on Studio Next

The cases below ran on the first v2 deployment (`0x29E2166fAFD8755A75d33F229e014dBb951e8B0c`, GenVM v0.3). Studio Next then moved to GenVM v0.4, which stops v0.3 contracts, so the same code was redeployed at the address above with only the runner header changed (the v0.3 to v0.4 migration items do not affect this contract). A re-run on the new address is listed in the last row.

| Case | Flow | Result |
|---|---|---|
| V2-01 | strong counter-evidence, resolve, finalize | UPHELD, REVOKED; seller bond moved to challenger, challenger bond returned |
| V2-02 | weak counter-evidence, resolve, appeal by challenger | DISMISSED in rounds 1 and 2, VERIFIED; challenger bond and appeal bond (300) moved to the registrant |
| V2-03 | same as V2-02 | same outcome; balances matched the expected arithmetic (A free 800 / locked 200, B free 500 / locked 0, total 1500 = 3 × 500 deposited) |
| v0.4 redeploy (N-01) | deposit ×2, register, verify, weak challenge, resolve, appeal by the challenger | VERIFIED, DISMISSED in rounds 1 and 2, SETTLED VERIFIED (2 rounds), winner = registrant; registrant balance free 700 / locked 100; the frontend on GitHub Pages reads the registry and shows the certificate with its full history |
| Guards | stale `expected_status` (wrong status, trailing space, duplicate appeal) | rejected with `status changed: expected …, got …` |

## Limitations

- Bonds are **internal units**. `deposit` does not transfer GEN and has no backing, so the economics are a simulation of the mechanism. A mainnet version should accept real value transfers.
- There is no appeal deadline: `finalize` can be called by anyone at any time after round 1.
- Validators judge only the page text, so the result depends on what the evidence pages say.
- The frontend signs with a connected wallet or a pasted test private key (kept in memory only). Use a test wallet.

## Layout

```
contracts/Product_authenticity.py   v2 contract
docs/index.html                     frontend
docs/binding.js                     display <-> action binding
docs/binding.test.js                10 checks
docs/test-binding.html              browser runner
docs/run-tests.mjs                  Node runner
```
