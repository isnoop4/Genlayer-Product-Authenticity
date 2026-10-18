# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
import json
import typing
import genlayer as gl

MAX_CHALLENGES = 3


def _parse_json(text):
    """Pull the first {...} object out of an LLM reply (tolerates code fences)."""
    t = text.strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(t[start : end + 1])


def _require(c, product_id):
    if product_id not in c.status:
        raise gl.vm.UserError(f"product_id '{product_id}' is not registered")


def _log(c, product_id, event):
    events = json.loads(c.history[product_id]) if product_id in c.history else []
    events.append(event)
    c.history[product_id] = json.dumps(events)


def _all_ids(c):
    return json.loads(c.index["all"]) if "all" in c.index else []


def _summary(c, product_id):
    return {
        "product_id": product_id,
        "claimed_origin": c.claimed_origin[product_id],
        "registered_by": c.registered_by[product_id],
        "status": c.status[product_id],
    }


def _challenges_used(c, product_id):
    events = json.loads(c.history[product_id]) if product_id in c.history else []
    return len([e for e in events if e.get("type") == "CHALLENGE"])


class ProductAuthenticity(gl.contract.Contract):
    claimed_origin: gl.storage.TreeMap[str, str]
    evidence_url: gl.storage.TreeMap[str, str]
    registered_by: gl.storage.TreeMap[str, str]
    # "PENDING" | "VERIFIED" | "REJECTED" | "DISPUTED" | "REVOKED"
    status: gl.storage.TreeMap[str, str]
    reasoning: gl.storage.TreeMap[str, str]
    # --- v1: challenge mechanism ---
    challenger: gl.storage.TreeMap[str, str]
    counter_evidence: gl.storage.TreeMap[str, str]
    challenge_reason: gl.storage.TreeMap[str, str]
    history: gl.storage.TreeMap[str, str]  # JSON list of events per product
    index: gl.storage.TreeMap[str, str]  # key "all" -> JSON list of product_ids

    def __init__(self):
        pass

    # ------------------------------------------------------------------ writes

    @gl.public.write
    def register_product(
        self, product_id: str, claimed_origin: str, evidence_url: str
    ) -> None:
        if not product_id or not claimed_origin or not evidence_url:
            raise gl.vm.UserError(
                "product_id, claimed_origin, and evidence_url are all required"
            )
        if product_id in self.status:
            raise gl.vm.UserError(f"product_id '{product_id}' is already registered")

        sender = gl.message.sender_address.as_hex
        self.claimed_origin[product_id] = claimed_origin
        self.evidence_url[product_id] = evidence_url
        self.registered_by[product_id] = sender
        self.status[product_id] = "PENDING"
        self.reasoning[product_id] = ""
        self.challenger[product_id] = ""
        self.counter_evidence[product_id] = ""
        self.challenge_reason[product_id] = ""
        self.history[product_id] = "[]"

        ids = _all_ids(self)
        ids.append(product_id)
        self.index["all"] = json.dumps(ids)
        _log(self, product_id, {"type": "REGISTER", "by": sender})

    @gl.public.write
    def verify_authenticity(self, product_id: str) -> typing.Any:
        _require(self, product_id)
        # v1: only PENDING products can be verified. Settled verdicts change
        # only through update_evidence (REJECTED) or the challenge flow.
        if self.status[product_id] != "PENDING":
            raise gl.vm.UserError(
                f"only PENDING products can be verified (current: {self.status[product_id]})"
            )

        # Read storage into locals BEFORE the nondet block.
        claimed_origin = self.claimed_origin[product_id]
        evidence_url = self.evidence_url[product_id]

        def leader_fn() -> str:
            try:
                page_text = gl.nondet.web.render(evidence_url, mode="text")
            except Exception as e:
                return json.dumps({
                    "verdict": "REJECTED",
                    "reasoning": f"Could not retrieve evidence_url: {e}",
                })

            prompt = f"""You are verifying a product-authenticity / supply-chain-origin
claim for an on-chain registry. Judge ONLY what the page text says. Do NOT
judge how official, famous or trustworthy the website is; treat the text as a
record supplied by the registrant. Mark VERIFIED if the text explicitly names
the product (or its brand/product line) and states the claimed origin. Mark
REJECTED if the text never states the origin, names a different origin, or is
generic and unrelated to a specific product.

Claimed origin: {claimed_origin}

Evidence page content:
---
{page_text[:4000]}
---

Respond with ONLY a JSON object, no preamble, no markdown fences, in exactly
this shape:
{{"verdict": "VERIFIED" or "REJECTED", "reasoning": "<one short sentence>"}}"""

            response = gl.nondet.exec_prompt(prompt)
            try:
                parsed = _parse_json(response)
                verdict = parsed.get("verdict")
                if verdict not in ("VERIFIED", "REJECTED"):
                    verdict = "REJECTED"
                return json.dumps({
                    "verdict": verdict,
                    "reasoning": str(parsed.get("reasoning", ""))[:300],
                })
            except Exception:
                return json.dumps({
                    "verdict": "REJECTED",
                    "reasoning": "Non-JSON or malformed model response",
                })

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            try:
                own_parsed = json.loads(leader_fn())
                leader_parsed = json.loads(leaders_res.calldata)
            except Exception:
                return False
            # Only the verdict must match; the reasoning text may vary.
            return leader_parsed.get("verdict") == own_parsed.get("verdict")

        raw_result = gl.vm.run_nondet_default(leader_fn, validator_fn)

        try:
            parsed = json.loads(raw_result)
            verdict = parsed.get("verdict", "REJECTED")
            reasoning_text = parsed.get("reasoning", "")
        except Exception:
            verdict = "REJECTED"
            reasoning_text = "Non-JSON or malformed validator response"
        if verdict not in ("VERIFIED", "REJECTED"):
            verdict = "REJECTED"

        self.status[product_id] = verdict
        self.reasoning[product_id] = reasoning_text
        _log(self, product_id, {"type": "VERIFY", "verdict": verdict, "reasoning": reasoning_text})
        return verdict

    @gl.public.write
    def update_evidence(self, product_id: str, new_evidence_url: str) -> None:
        """Registrant swaps in better evidence after a REJECTED verdict."""
        _require(self, product_id)
        sender = gl.message.sender_address.as_hex
        if sender != self.registered_by[product_id]:
            raise gl.vm.UserError("only the registrant can update evidence")
        if self.status[product_id] != "REJECTED":
            raise gl.vm.UserError("evidence can only be updated while REJECTED")
        if not new_evidence_url:
            raise gl.vm.UserError("new_evidence_url is required")

        self.evidence_url[product_id] = new_evidence_url
        self.status[product_id] = "PENDING"
        self.reasoning[product_id] = ""
        _log(self, product_id, {"type": "EVIDENCE_UPDATED", "by": sender, "evidence_url": new_evidence_url})

    @gl.public.write
    def challenge_product(
        self, product_id: str, counter_evidence_url: str, reason: str
    ) -> None:
        """Anyone except the registrant can contest a VERIFIED claim."""
        _require(self, product_id)
        if not counter_evidence_url or not reason:
            raise gl.vm.UserError("counter_evidence_url and reason are required")
        if self.status[product_id] != "VERIFIED":
            raise gl.vm.UserError(
                f"only VERIFIED products can be challenged (current: {self.status[product_id]})"
            )

        sender = gl.message.sender_address.as_hex
        if sender == self.registered_by[product_id]:
            raise gl.vm.UserError("the registrant cannot challenge their own product")

        events = json.loads(self.history[product_id])
        used = [e for e in events if e.get("type") == "CHALLENGE"]
        if len(used) >= MAX_CHALLENGES:
            raise gl.vm.UserError(f"challenge limit reached ({MAX_CHALLENGES})")
        if any(e.get("counter_evidence") == counter_evidence_url for e in used):
            raise gl.vm.UserError("this counter-evidence URL was already used in a challenge")

        self.challenger[product_id] = sender
        self.counter_evidence[product_id] = counter_evidence_url
        self.challenge_reason[product_id] = reason[:500]
        self.status[product_id] = "DISPUTED"
        _log(self, product_id, {
            "type": "CHALLENGE",
            "by": sender,
            "counter_evidence": counter_evidence_url,
            "reason": reason[:500],
        })

    @gl.public.write
    def resolve_challenge(self, product_id: str) -> typing.Any:
        """Validators weigh original evidence vs counter-evidence. Anyone can trigger."""
        _require(self, product_id)
        if self.status[product_id] != "DISPUTED":
            raise gl.vm.UserError(
                f"no open challenge (current: {self.status[product_id]})"
            )

        claimed_origin = self.claimed_origin[product_id]
        original_url = self.evidence_url[product_id]
        counter_url = self.counter_evidence[product_id]
        reason = self.challenge_reason[product_id]

        def leader_fn() -> str:
            try:
                counter_text = gl.nondet.web.render(counter_url, mode="text")
            except Exception as e:
                return json.dumps({
                    "ruling": "DISMISSED",
                    "reasoning": f"Could not retrieve counter-evidence: {e}",
                })
            try:
                original_text = gl.nondet.web.render(original_url, mode="text")
            except Exception:
                original_text = "(original evidence page unavailable)"

            prompt = f"""You are the arbiter of a dispute in an on-chain product-authenticity
registry. A product's origin claim was VERIFIED earlier. A challenger now
submits counter-evidence. Rule UPHELD only if the counter-evidence explicitly
and specifically contradicts the claimed origin of THIS product. Vague,
generic, unrelated, or merely suspicious material must be DISMISSED. Do not
judge how official or well-known either website is; judge only what the text says.

Claimed origin: {claimed_origin}
Challenger's reason: {reason}

Original evidence:
---
{original_text[:3000]}
---

Counter-evidence:
---
{counter_text[:3000]}
---

Respond with ONLY a JSON object, no preamble, no markdown fences, in exactly
this shape:
{{"ruling": "UPHELD" or "DISMISSED", "reasoning": "<one short sentence>"}}"""

            response = gl.nondet.exec_prompt(prompt)
            try:
                parsed = _parse_json(response)
                ruling = parsed.get("ruling")
                if ruling not in ("UPHELD", "DISMISSED"):
                    ruling = "DISMISSED"
                return json.dumps({
                    "ruling": ruling,
                    "reasoning": str(parsed.get("reasoning", ""))[:300],
                })
            except Exception:
                return json.dumps({
                    "ruling": "DISMISSED",
                    "reasoning": "Non-JSON or malformed model response",
                })

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            try:
                own_parsed = json.loads(leader_fn())
                leader_parsed = json.loads(leaders_res.calldata)
            except Exception:
                return False
            return leader_parsed.get("ruling") == own_parsed.get("ruling")

        raw_result = gl.vm.run_nondet_default(leader_fn, validator_fn)

        try:
            parsed = json.loads(raw_result)
            ruling = parsed.get("ruling", "DISMISSED")
            reasoning_text = parsed.get("reasoning", "")
        except Exception:
            ruling = "DISMISSED"
            reasoning_text = "Non-JSON or malformed validator response"
        if ruling not in ("UPHELD", "DISMISSED"):
            ruling = "DISMISSED"

        self.status[product_id] = "REVOKED" if ruling == "UPHELD" else "VERIFIED"
        self.reasoning[product_id] = reasoning_text
        _log(self, product_id, {"type": "RULING", "ruling": ruling, "reasoning": reasoning_text})
        return ruling

    # ------------------------------------------------------------------- views

    @gl.public.view
    def get_product(self, product_id: str) -> typing.Any:
        _require(self, product_id)
        return {
            "product_id": product_id,
            "claimed_origin": self.claimed_origin[product_id],
            "evidence_url": self.evidence_url[product_id],
            "registered_by": self.registered_by[product_id],
            "status": self.status[product_id],
            "reasoning": self.reasoning[product_id],
            "challenger": self.challenger[product_id],
            "counter_evidence": self.counter_evidence[product_id],
            "challenge_reason": self.challenge_reason[product_id],
            "challenges_used": _challenges_used(self, product_id),
            "max_challenges": MAX_CHALLENGES,
            "history": json.loads(self.history[product_id]),
        }

    @gl.public.view
    def get_products(self, offset: int, limit: int) -> typing.Any:
        ids = _all_ids(self)
        start = max(0, offset)
        page = ids[start : start + max(0, limit)]
        return {"total": len(ids), "items": [_summary(self, i) for i in page]}

    @gl.public.view
    def get_products_by_seller(self, seller: str) -> typing.Any:
        wanted = seller.lower()
        return [
            _summary(self, i)
            for i in _all_ids(self)
            if self.registered_by[i].lower() == wanted
        ]
