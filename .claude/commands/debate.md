Launch a structured adversarial debate to produce a high-quality PRD.

**Usage:** `/debate <topic>`

**What this does:**
1. Constructs a debate envelope with `intent.op = 'debate'` and your topic as the instruction
2. POSTs it to the Anchor service at `http://localhost:3000/envelope`
3. The service routes it to the in-process debate orchestrator
4. Host (Claude Opus) organizes up to 14 rounds of debate between Proposer (Claude Sonnet) and Reviewer (GPT-5)
5. Results appear in real-time in the Debate overlay in your browser

**Output:**
- `output/debates/<id>/spec.md` — four-layer PRD (problem → ideal → gap → strategy)
- `output/debates/<id>/transcript.json` — full debate transcript
- Browser: real-time dual-column overlay

---

$ARGUMENTS

Send the debate request to the Anchor service. The topic is: "$ARGUMENTS"

Construct and send this envelope to start the debate:

```bash
curl -s -X POST http://localhost:3000/envelope \
  -H "Content-Type: application/json" \
  -d "{\"schema_version\":\"1.0\",\"intent\":{\"op\":\"debate\",\"target_kind\":\"global\",\"target_ref\":\"__debate_cli__\",\"instruction\":\"$ARGUMENTS\"},\"provenance\":{\"session_id\":\"cli\",\"event_id\":\"evt_$(date +%s)\",\"parent_event_id\":null,\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"client_version\":\"1.0\"},\"context_bundle\":{\"subagent_id\":null,\"context_mode\":\"standard\"},\"render_state\":{\"anchor_tree\":[],\"dom_signature\":\"\"}}"
```

Run this curl command now, then report the response. If the Anchor service is not running, ask the user to run `scripts\start-anchor.bat` first.

After sending, tell the user:
- The debate has been queued with topic: "$ARGUMENTS"
- They can watch progress in real-time at http://localhost:3000 in the Debate overlay
- The spec will be saved to `output/debates/<id>/spec.md` when complete
