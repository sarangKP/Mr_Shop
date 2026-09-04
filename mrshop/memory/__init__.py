"""
Memory layer — ambient session state.

Stores wardrobe items, preferences, budget, current topic, topic history,
and last-mentioned item across all turns of a session. Never wiped on topic
switch; old topic state is parked so the user can pivot back without
re-explaining.
"""
