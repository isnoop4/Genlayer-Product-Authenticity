# Product Authenticity Registry

An on-chain registry where sellers register a product's claimed origin together with a public evidence URL. GenLayer validators read the evidence page, reach consensus on whether it supports the claim, and anyone can later contest a verified claim with counter-evidence.

- **Live demo:** https://isnoop4.github.io/Genlayer-Product-Authenticity
- **Contract (Studio Next, chain ID 61997):** [`0xF03531aE59C9a071a5591eD9764102c5aa377491`](https://explorer-studio-next.genlayer.com/address/0xF03531aE59C9a071a5591eD9764102c5aa377491)
- **Contract source:** [`Product_authenticity.py`](./Product_authenticity.py)

## Milestone v1: challenge mechanism

Version 0 had a single, final verdict: a claim was `VERIFIED` or `REJECTED` and nothing could change it. A seller whose evidence page happened to pass had no further scrutiny, and a seller with a weak page had no way to fix it.

v1 adds a correction path, all decided by validator consensus.

| What changed | v0 | v1 |
|---|---|---|
| Statuses | PENDING, VERIFIED, REJECTED | adds DISPUTED, REVOKED |
| Contest a verified claim | not possible | `challenge_product` with counter-evidence and a reason |
| Decide a challenge | none | `resolve_challenge`, validators compare original and counter evidence |
| Fix a rejected claim | register under a new ID | `update_evidence`, status returns to PENDING |
| Re-verification | callable at any time | only while PENDING |
| Audit trail | latest status only | full event history per product |
| Reads | `get_product` | adds `get_products` (paged) and `get_products_by_seller` |
| Frontend | register and verify | adds challenge, resolve, update evidence, history timeline, registry list |

## How it works

```
register_product ──> PENDING ──verify_authenticity──> VERIFIED ──challenge_product──> DISPUTED
                        ^                                 ^                              |
                        |                                 |  DISMISSED                   | resolve_challenge
                 update_evidence                          +------------------------------+
                        |                                                                | UPHELD
                     REJECTED <──verify_authenticity── PENDING                         REVOKED
```

- **Verification:** the leader fetches the evidence page and asks an LLM whether the text explicitly states the claimed origin for the product. Validators repeat the check independently and must reach the same verdict.
- **Challenge:** anyone except the registrant can contest a `VERIFIED` product by submitting a counter-evidence URL and a reason. The status becomes `DISPUTED`.
- **Resolution:** anyone can trigger `resolve_challenge`. Validators read both pages. `UPHELD` revokes the claim; `DISMISSED` restores `VERIFIED`.
- **Safeguards:** the registrant cannot challenge their own product, at most 3 challenges are allowed per product, and the same counter-evidence URL cannot be reused.

## Contract interface

Writes: `register_product`, `verify_authenticity`, `update_evidence`, `challenge_product`, `resolve_challenge`
Views: `get_product`, `get_products`, `get_products_by_seller`

## Test results

Run on Studio Next against the deployed contract above, using public GitHub Gists about a fictional brand (one supporting the origin claim, one contradicting it, one generic) and two separate wallets.

| # | Scenario | Expected | Result |
|---|---|---|---|
| 1 | Register `NW-001`, verify with supporting evidence | VERIFIED | As expected |
| 2 | Second wallet challenges `NW-001` with contradicting evidence, then resolve | REVOKED (UPHELD) | As expected |
| 3 | Second wallet challenges `NW-002` with generic evidence, then resolve | VERIFIED again (DISMISSED) | As expected |
| 4 | `NW-003` registered with weak evidence is rejected, evidence updated, verified again | REJECTED, PENDING, VERIFIED | As expected |
| 5 | Registrant challenges own product; challenge on non-VERIFIED product; reuse of counter-evidence URL; verify on a non-PENDING product | Contract rejects each | As expected |

Transactions are visible on the [contract page in the explorer](https://explorer-studio-next.genlayer.com/address/0xF03531aE59C9a071a5591eD9764102c5aa377491).

## Known limitations

- Verification judges what the evidence page says, not who published it. Evidence is supplied by the registrant, so a self-published page can pass. A future version could restrict evidence to allow-listed domains or official sources.
- A challenge is only as strong as its counter-evidence. Vague or generic material is dismissed by design.
- Validators sometimes disagree on borderline pages, which leaves a transaction undetermined and the status unchanged. The prompt was tightened to judge the page text only to reduce this.
- Studio Next is a release-candidate network, so deployed state may be reset.

## Running the demo

Open `index.html` through any static host (GitHub Pages is used for the live demo). Connect a wallet, or use a throwaway test key, on Studio Next (chain ID 61997). The contract address is set in the `CONFIG` block at the top of the script.

## Files

- `Product_authenticity.py`: the Intelligent Contract
- `index.html`: single-file frontend
- `README.md`: this file
