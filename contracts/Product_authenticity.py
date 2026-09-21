# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
import json
import typing
import genlayer as gl


class ProductAuthenticity(gl.contract.Contract):
    claimed_origin: gl.storage.TreeMap[str, str]
    evidence_url: gl.storage.TreeMap[str, str]
    registered_by: gl.storage.TreeMap[str, str]
    status: gl.storage.TreeMap[str, str]  # "PENDING" | "VERIFIED" | "REJECTED"
    reasoning: gl.storage.TreeMap[str, str]

    def __init__(self):
        pass

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

        self.claimed_origin[product_id] = claimed_origin
        self.evidence_url[product_id] = evidence_url
        self.registered_by[product_id] = gl.message.sender_address.as_hex
        self.status[product_id] = "PENDING"
        self.reasoning[product_id] = ""

    @gl.public.write
    def verify_authenticity(self, product_id: str) -> typing.Any:
        if product_id not in self.status:
            raise gl.vm.UserError(f"product_id '{product_id}' is not registered")

        # Read storage into locals BEFORE the nondet block (storage proxies
        # aren't accessible inside leader_fn/validator_fn).
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
claim for an on-chain registry. Be strict: only mark VERIFIED if the evidence
explicitly and specifically supports THIS product's claimed origin. Generic
pages, unrelated brand pages, or evidence that doesn't name the specific
origin claim must be REJECTED.

Claimed origin: {claimed_origin}

Evidence page content:
\"\"\"{page_text[:4000]}\"\"\"

Respond with ONLY a JSON object, no preamble, no markdown fences, in exactly
this shape:
{{"verdict": "VERIFIED" or "REJECTED", "reasoning": "<one short sentence>"}}"""

            response = gl.nondet.exec_prompt(prompt)
            return response.strip()

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            try:
                own_result = leader_fn()
                leader_parsed = json.loads(leaders_res.calldata)
                own_parsed = json.loads(own_result)
            except Exception:
                return False
            # Only the verdict needs to match — the one-sentence reasoning
            # text can vary slightly between independent LLM calls.
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

        return verdict

    @gl.public.view
    def get_product(self, product_id: str) -> typing.Any:
        if product_id not in self.status:
            raise gl.vm.UserError(f"product_id '{product_id}' is not registered")

        return {
            "product_id": product_id,
            "claimed_origin": self.claimed_origin[product_id],
            "evidence_url": self.evidence_url[product_id],
            "registered_by": self.registered_by[product_id],
            "status": self.status[product_id],
            "reasoning": self.reasoning[product_id],
        }
