"""
Orchestration layer — the agent brain (PRD §6).

Owns per-turn execution: runs intent detection, decides routing (direct tool
call, clarifying question), invokes tools, updates memory, and produces
turn_trace for observability. Implemented in Step 6.
"""
