"""
Tool layer — one pure function per intent.

Each tool takes plain data (no HTTP, no side effects) and returns a plain
dict. Designed so this interface maps directly onto real function-calling
if the orchestrator is later replaced by an LLM-native agent.

Implemented in Step 3.
"""
