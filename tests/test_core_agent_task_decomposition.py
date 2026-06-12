import unittest
import asyncio

from loom_core.agents.core_agent import LoomCoreAgent


class _TextBlock:
    def __init__(self, text):
        self.text = text


class _MessageClient:
    def __init__(self, text):
        self._text = text
        self.messages = self

    async def create(self, **kwargs):
        return type("Resp", (), {"content": [_TextBlock(self._text)]})()


class _FakeDispatcher:
    async def resolve(self, question, context):
        return {
            "domain": "market",
            "mode": "state_driven",
            "state_scope": ["market"],
        }


class _FakeHarness:
    def cold_start(self):
        return False

    def select_state_context(self, domain, question, context):
        return {"domain": domain, "intent_context": {"decision_context": "compare signals"}}

    async def plan(self, question, workflow_decision, client, model):
        return {
            "goal": {"title": question},
            "rubrics": [{"dimension": "Evidence", "requirements": "source-backed"}],
            "excluded_hands": [],
        }

    async def review(self, question, analysis_plan, hand_artifacts, client, model):
        return {"rubric_coverage": {"Evidence": "covered"}, "follow_up_needed": False}

    async def synthesize(
        self,
        question,
        hand_artifacts,
        workflow_decision,
        client,
        model,
        analysis_plan=None,
        review_result=None,
    ):
        return {
            "stance": "hold",
            "confidence": 0.7,
            "key_drivers": [{"rule": "risk", "hand": "market", "claim": "claim 1"}],
            "reversal_condition": "risk clears",
            "strategy_refs": ["risk"],
            "clarifying_question": None,
        }

    def write_last_synthesis(self, question, workflow, synthesis):
        self.last_synthesis = synthesis

    def compose_presentation(self, **kwargs):
        return {
            "version": kwargs["presentation_spec"]["version"],
            "overview": {"stance": kwargs["synthesis"]["stance"]},
            "cards": [{"hand_id": "market"}],
            "detail_panels": {"market": {"sections": []}},
            "state_context": kwargs["presentation_spec"]["state_context"],
        }


class _AgenticHarness(_FakeHarness):
    def __init__(self):
        self.persisted_specs = []

    async def plan(self, question, workflow_decision, client, model):
        return {
            "goal": {"title": question, "success_criteria": ["answer with evidence"]},
            "sub_questions": ["what matters?"],
            "rubrics": [{"dimension": "Evidence", "requirements": "source-backed"}],
            "excluded_hands": [],
        }

    async def review(self, question, analysis_plan, hand_artifacts, client, model):
        return {
            "rubric_coverage": {"Evidence": "covered"},
            "follow_up_needed": False,
            "confidence_gaps": [],
        }



class CoreAgentTaskDecompositionTests(unittest.TestCase):
    def test_analyze_injects_brain_presentation_spec_and_returns_presentation(self):
        seen = {"calls": []}

        async def hand_runner(hand_id, task, context):
            seen["calls"].append({"hand_id": hand_id, "task": task, "context": context})
            return {
                "metadata": {"confidence": 0.7, "key_claims": ["claim 1"], "gaps": []},
                "narrative": "Market is cautious.",
                "sections": [],
                "evidence": [],
            }

        agent = LoomCoreAgent(_FakeHarness(), _FakeDispatcher(), hand_runner, client=None, model="fake")
        result = asyncio.run(agent.analyze("today market brief", {}))

        self.assertEqual("brain.presentation.v1", result["presentation_spec"]["version"])
        first_call = seen["calls"][0]
        self.assertEqual("brain.presentation.v1", first_call["context"]["presentation_spec"]["version"])
        self.assertEqual(
            "compare signals",
            first_call["context"]["brain_state_context"]["intent_context"]["decision_context"],
        )
        self.assertIn("Brain presentation contract", first_call["task"])
        self.assertEqual("hold", result["presentation"]["overview"]["stance"])

    def test_presentation_spec_places_layering_responsibility_on_brain(self):
        workflow = {"domain": "market", "mode": "dynamic", "hands": ["market", "sentiment"]}
        state_context = {
            "strategy_rules": [{"rule_id": "risk", "condition": "volatile", "action": "show caveats"}],
            "frameworks": [{"framework_id": "liquidity", "name": "Liquidity lens"}],
            "learned_notes": [{"note": "Prefer source-backed detail"}],
            "intent_context": {"decision_context": "compare signals before action"},
        }

        spec = LoomCoreAgent._build_presentation_spec(
            "today market brief",
            workflow,
            state_context,
        )

        self.assertEqual("brain.presentation.v1", spec["version"])
        self.assertEqual("market", spec["domain"])
        self.assertIn("visible_layer", spec["ui_contract"])
        self.assertIn("detail_layer", spec["ui_contract"])
        self.assertEqual("overview_only", spec["ui_contract"]["visible_layer"]["content_policy"])
        self.assertTrue(spec["ui_contract"]["detail_layer"]["all_content_requires_provenance"])
        detail_schema = spec["ui_contract"]["detail_layer"]["card_detail_schema"]
        self.assertEqual(
            ["judgment", "drivers", "evidence", "implications", "gaps", "watchlist"],
            [layer["id"] for layer in detail_schema],
        )
        self.assertEqual(state_context, spec["state_context"])
        self.assertIn("market", spec["hand_specs"])
        self.assertIn("sentiment", spec["hand_specs"])
        self.assertIn("detail_requirements", spec["hand_specs"]["market"])
        self.assertIn("evidence_requirements", spec["hand_specs"]["market"])
        self.assertIn("provenance_requirements", spec["hand_specs"]["market"])
        self.assertIn("source", spec["hand_specs"]["market"]["provenance_requirements"])
        self.assertIn(
            "all information units require provenance, not only numerical data",
            spec["hand_specs"]["market"]["provenance_requirements"],
        )

    def test_market_hand_task_requires_layered_artifact(self):
        spec = LoomCoreAgent._build_presentation_spec(
            "today market brief",
            {"domain": "market", "mode": "dynamic", "hands": ["market"]},
            {"strategy_rules": [], "frameworks": [], "learned_notes": [], "intent_context": {}},
        )
        task = LoomCoreAgent._build_hand_task(
            "runtime-market-evidence",
            "today market brief",
            {"domain": "market", "mode": "dynamic"},
            spec,
            executor_id="market",
            dimension="Generated evidence dimension",
        )

        self.assertIn("Generated hand: runtime-market-evidence", task)
        self.assertIn("Executor shell: market", task)
        self.assertIn("Brain-generated dimension: Generated evidence dimension", task)
        self.assertIn("Do not return a flat essay", task)
        self.assertIn("Brain presentation contract", task)
        self.assertIn("provenance_requirements", task)
        self.assertIn("card_detail_schema", task)
        self.assertIn("`sections`", task)
        self.assertIn("`evidence`", task)
        self.assertIn("metadata.source_notes", task)

    def test_artifact_contract_contains_drill_down_layers(self):
        contract = LoomCoreAgent._artifact_contract()

        self.assertIn("sections", contract["required_top_level"])
        self.assertIn("source_notes", contract["metadata"])
        section_ids = {section["id"] for section in contract["sections"]}
        self.assertTrue({"summary", "evidence", "analysis", "gaps"}.issubset(section_ids))
        self.assertIn("freshness", contract["evidence_items"])

    def test_fixed_domain_uses_state_generated_hand_specs_with_executor_shell(self):
        seen = {"calls": []}

        class FinanceDispatcher:
            async def resolve(self, question, context):
                return {
                    "domain": "finance",
                    "mode": "state_driven",
                    "state_scope": ["finance", "portfolio"],
                    "registered_shells": ["market", "position"],
                }

        async def hand_runner(hand_id, task, context):
            seen["calls"].append({"hand_id": hand_id, "task": task, "context": context})
            return {
                "metadata": {"confidence": 0.8, "key_claims": ["claim 1"], "gaps": []},
                "narrative": "Evidence supports caution.",
                "sections": [],
                "evidence": [],
            }

        harness = _AgenticHarness()
        client = _MessageClient(
            '{"rationale":"state needs evidence and exposure checks","tasks":['
            '{"task_id":"t1","hand_id":"runtime-evidence-agent","executor_id":"market",'
            '"dimension":"evidence pressure","task":"Collect source-backed evidence",'
            '"system_prompt":"You are an evidence pressure specialist.",'
            '"capabilities":["market_data"],'
            '"rubrics":[{"dimension":"Evidence","requirements":"source-backed"}],'
            '"priority":0,"depends_on":[]},'
            '{"task_id":"t2","hand_id":"runtime-exposure-agent","executor_id":"position",'
            '"dimension":"portfolio exposure","task":"Check exposure implication",'
            '"system_prompt":"You are a portfolio exposure specialist.",'
            '"capabilities":["portfolio"],'
            '"rubrics":[{"dimension":"Evidence","requirements":"source-backed"}],'
            '"priority":0,"depends_on":[]}'
            ']}'
        )
        agent = LoomCoreAgent(harness, FinanceDispatcher(), hand_runner, client=client, model="fake")
        result = asyncio.run(agent.analyze("review my portfolio risk", {"goal_type": "position_review"}))

        self.assertEqual(["market", "position"], [call["hand_id"] for call in seen["calls"]])
        first_spec = seen["calls"][0]["context"]["agentic_hand_spec"]
        self.assertEqual("runtime-evidence-agent", first_spec["hand_id"])
        self.assertEqual("market", first_spec["executor_id"])
        self.assertEqual("evidence pressure", first_spec["dimension"])
        self.assertEqual("You are an evidence pressure specialist.", first_spec["system_prompt"])
        self.assertEqual(["market_data"], first_spec["capabilities"])
        second_spec = seen["calls"][1]["context"]["agentic_hand_spec"]
        self.assertEqual("You are a portfolio exposure specialist.", second_spec["system_prompt"])
        self.assertEqual(["portfolio"], second_spec["capabilities"])
        self.assertEqual("state_driven", result["hand_plan"]["mode"])
        self.assertEqual(
            ["runtime-evidence-agent", "runtime-exposure-agent"],
            [task["hand_id"] for task in result["hand_plan"]["tasks"]],
        )
        self.assertEqual(["market", "position"], [task["executor_id"] for task in result["hand_plan"]["tasks"]])
        self.assertEqual("market", result["hand_artifacts"]["t1"]["metadata"]["executor_id"])

    def test_general_domain_fallback_uses_single_brain_inline_runtime_hand(self):
        seen = {}

        async def hand_runner(hand_id, task, context):
            seen["hand_id"] = hand_id
            seen["context"] = context
            return {
                "metadata": {"confidence": 0.7, "key_claims": ["claim 1"], "gaps": []},
                "narrative": "Runtime result.",
                "sections": [],
                "evidence": [],
            }

        harness = _AgenticHarness()
        agent = LoomCoreAgent(harness, _FakeDispatcher(), hand_runner, client=None, model="fake")
        result = asyncio.run(agent.analyze("organize this idea", {}))

        self.assertEqual("brain-inline", seen["hand_id"])
        self.assertEqual("runtime-inline-0", seen["context"]["agentic_hand_spec"]["hand_id"])
        self.assertEqual("brain-inline", seen["context"]["agentic_hand_spec"]["executor_id"])
        self.assertEqual("runtime", seen["context"]["agentic_hand_spec"]["lifecycle"])
        self.assertEqual("state_driven_fallback", result["hand_plan"]["mode"])
        self.assertEqual(1, len(result["hand_plan"]["tasks"]))

    def test_brain_generates_runtime_hand_and_routes_via_brain_inline(self):
        seen = {}

        async def hand_runner(hand_id, task, context):
            seen["hand_id"] = hand_id
            seen["task"] = task
            seen["context"] = context
            return {
                "metadata": {"confidence": 0.82, "key_claims": ["risk claim"], "gaps": []},
                "narrative": "Risk agent result.",
                "sections": [],
                "evidence": [],
            }

        client = _MessageClient(
            '{"rationale":"risk needs a generated runtime specialist","tasks":['
            '{"task_id":"t1","hand_id":"runtime-risk-agent-0","executor_id":"brain-inline",'
            '"dimension":"risk synthesis","task":"Assess risk in the proposed workflow",'
            '"system_prompt":"You are a runtime risk analyzer. Focus on failure modes.",'
            '"capabilities":["portfolio"],'
            '"rubrics":[{"dimension":"Risk","requirements":"identify failure modes"}],'
            '"priority":0,"depends_on":[]}'
            ']}'
        )
        agent = LoomCoreAgent(_AgenticHarness(), _FakeDispatcher(), hand_runner, client=client, model="fake")
        result = asyncio.run(agent.analyze("review this workflow risk", {}))

        spec = seen["context"]["agentic_hand_spec"]
        self.assertEqual("brain-inline", seen["hand_id"])
        self.assertEqual("runtime-risk-agent-0", spec["hand_id"])
        self.assertEqual("brain-inline", spec["executor_id"])
        self.assertEqual("risk synthesis", spec["dimension"])
        self.assertEqual("You are a runtime risk analyzer. Focus on failure modes.", spec["system_prompt"])
        self.assertEqual(["portfolio"], spec["capabilities"])
        self.assertEqual("Risk agent result.", result["hand_artifacts"]["t1"]["narrative"])


if __name__ == "__main__":
    unittest.main()
