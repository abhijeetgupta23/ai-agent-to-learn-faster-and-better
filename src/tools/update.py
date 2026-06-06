"""Update the learner model based on a session turn."""

from __future__ import annotations

from src.memory.store import MemoryStore
from src.schemas import LearnerModel, Modality, SessionTurn


# Guardrails: clamp difficulty to keep the agent from trivializing or overwhelming.
DIFFICULTY_FLOOR = 1
DIFFICULTY_CEILING = 5

# How many recent correct turns at the current level trigger a promotion.
PROMOTE_AFTER_CORRECT = 3
# How many recent struggles at the current level trigger a demotion.
DEMOTE_AFTER_STRUGGLES = 2


def update_learner_model(
    learner: LearnerModel,
    turn: SessionTurn,
    store: MemoryStore | None = None,
) -> LearnerModel:
    learner.session_history.append(turn)

    if turn.correct is True:
        if turn.concept_id not in learner.mastered_concepts:
            learner.mastered_concepts.append(turn.concept_id)
        if turn.concept_id in learner.struggling_concepts:
            learner.struggling_concepts.remove(turn.concept_id)
    elif turn.correct is False:
        if turn.concept_id not in learner.struggling_concepts:
            learner.struggling_concepts.append(turn.concept_id)

    # Modality preference: weighted slide toward the modality that worked
    # for the most recent CORRECT turns.
    recent_correct = [t for t in learner.session_history[-10:] if t.correct]
    if recent_correct:
        modalities = [t.modality for t in recent_correct]
        # Pick the modality used most often in recent successes.
        top = max(set(modalities), key=modalities.count)
        learner.modality_preference = top if isinstance(top, Modality) else Modality(top)

    # Difficulty ceiling/floor adjustment.
    recent = learner.session_history[-5:]
    recent_at_level = [
        t for t in recent if _difficulty_from_turn(t, learner) == learner.difficulty_level
    ]
    correct_at_level = sum(1 for t in recent_at_level if t.correct is True)
    wrong_at_level = sum(1 for t in recent_at_level if t.correct is False)

    if correct_at_level >= PROMOTE_AFTER_CORRECT and learner.difficulty_level < DIFFICULTY_CEILING:
        learner.difficulty_level += 1
    elif wrong_at_level >= DEMOTE_AFTER_STRUGGLES and learner.difficulty_level > DIFFICULTY_FLOOR:
        learner.difficulty_level -= 1

    if store is not None:
        store.save_learner(learner)
    return learner


def _difficulty_from_turn(turn: SessionTurn, learner: LearnerModel) -> int:
    # We don't carry difficulty on the turn; use current level as a stand-in.
    # A future iteration can attach difficulty to SessionTurn.
    return learner.difficulty_level
