"""Evaluation harness for the DATAEZ agent.

Three layers, cheapest first:

L1 routing  — deterministic scoring of the orchestrator's intent classification
              and tool selection against a labelled golden set. One LLM call
              per case, no database, no agent loop.
L2 behaviour— the agent loop driven against seeded fixtures with assertions on
              the tool trace and resulting database state.
L3 judge    — LLM-as-a-judge quality scoring, for what L1 and L2 cannot assert.

L1 and L2 are deterministic given a model; only L3 is subjective. Putting the
cheap deterministic layers first is what makes the suite runnable often enough
to act as a regression gate.
"""
