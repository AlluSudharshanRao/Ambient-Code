"""
Ambient Code — Layer 3 Insight Engine.

Polls context.db (written by Layer 2), evaluates pattern triggers,
assembles LLM context, calls OpenAI, and appends findings to
~/.ambient-code/findings.ndjson for the Layer 1 VS Code extension
to surface.

Components
----------
reader.py          Read-only queries on context.db
triggers/          Pattern detectors (velocity, long function, uncovered churn)
llm/               OpenAI client + prompt assembly
writer.py          Findings NDJSON writer with cooldown
main.py            InsightEngine poll loop + entry point
"""
