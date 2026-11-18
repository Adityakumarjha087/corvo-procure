# APPROACH.md

## How I approached it

1. **Read the kit as the spec.** Before writing code I reproduced the worked examples by hand from the data, to pin down the semantics the policy leaves implicit:
   - the valuation price differs from the PO price (VCI bag)
   - ceilings are consumed in requirement order (hex bolts)
   - need-by windows are measured from the first line (examples 4/14)
   - the suggestion top-up is ordered by a delivery-plus-quality score (examples 3, 9–12)

   I also cross-checked every contract PDF against the register (all 10 match; 2 exist only as PDFs) and listed the data traps: blocked suppliers in history, a blocked contract holder, an expired contract, near-empty ceilings, an invalid plant, a zero quantity, "urgent" in free text, and a likely duplicate PR.
2. **Engine first, as pure functions.** `backend/app/engine` takes a dataset, PR lines and the approved policy versions, and returns decisions plus a step-by-step trace. It has no database or HTTP code, so the same function serves the API, the chat preview, the policy impact preview and the tests.
3. **Policy as data.** Every limit, window, weight and the ordered rule list live in a JSON document (`backend/app/policy/corvo_v5_0.json`). Rules are condition trees over named facts with an outcome. The engine just walks the list. New kinds of rule (plant-only, category, department, performance floors, new routes, reordering) need no code. Versions are immutable once approved and are chosen by effective date.
4. **AI only where language is the problem, behind deterministic guards.**
   - *Chat:* Claude extracts fields from what the requester typed (structured JSON output). The item match, follow-up questions, validation and the decision preview are deterministic, so the assistant cannot invent an item.
   - *Amendments:* Claude reads the PDF or text and returns edit operations. The server applies and validates them and renders the diff itself. A person approves after seeing the diff and an impact preview.
   - Both degrade gracefully without a key (regex extractor / JSON editor), so the app never depends on the AI being up.
5. **UI for one obvious next action per screen.** The buyer drawer leads with Approve, and the "why" (clause, version, contract or PO relied on) is the first thing under the numbers.
6. **Verify, then ship.** 46 pytest tests cover:
   - all 14 worked decisions, plus clubbing, PO grouping, PO-number spacing, no blocked or inactive suppliers, and the PDF contract dates
   - the 3 preferred lists
   - amendments changing decisions without code
   - the matcher and the chat flow
   - the API end to end

   I also ran `docker compose up` and smoke-tested the health check, UI and API on Postgres, and screenshot-tested every page with Playwright in dark, light and phone widths.

## AI tools used

- **Building:** Claude Code (Anthropic's CLI agent, model Claude Opus 5.5) for analysis of the kit, code generation, tests, and the docs. I reviewed the design choices, verified the outputs against the worked examples, and can explain and change any part.
- **Inside the app:** the Anthropic Python SDK with `claude-opus-5-5`:
  - `backend/app/ai/chat.py`: extracts PR fields from chat messages (structured output, low effort for speed)
  - `backend/app/ai/policy_reader.py`: turns an amendment document into validated edit operations (structured output, high effort, PDF input)
  - Server-side refusal fallback is enabled where available. Errors fall back to the deterministic paths with a clear message.

## Trade-offs I'd revisit with more time

- Real authentication and role permissions (the user is currently chosen in the UI and sent as a header; every action is audited).
- Posting approved contract POs back to contract consumption and PO history (runs are deliberately independent today, see DECISIONS E).
- Semantic item matching (embeddings) for descriptions with no shared words; today unknown wording is sent to a human rather than guessed.
