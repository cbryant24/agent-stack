"""What the model passes when it structures the director's feedback, and the rules applied to it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from music_curation.constants import POSITIVE_REACTIONS

Reaction = Literal["loved", "liked", "liked_with_changes", "disliked", "prompt_failed",
                   "copyright_blocked", "never_ran", "lost_track"]
Valence = Literal["positive", "negative"]
Scope = Literal["genre", "production", "instrumentation", "vocal", "arrangement", "general"]
# The track was never heard, so there is nothing to rate.
UNHEARD = {"copyright_blocked", "never_ran", "lost_track"}


class TasteInput(BaseModel):
    statement: str = Field(description="The lesson, in the director's terms.")
    valence: Valence
    scope: Scope = "general"


class ReportArgs(BaseModel):
    generation: str = Field(description="The generation: its id, a unique prefix of 8+ characters, or 'latest'.")
    reaction: Reaction
    rating: int | None = Field(default=None, ge=1, le=5, description="Only if the director gave one.")
    notes: str | None = Field(default=None, description="Action-oriented: what to change next time.")
    context: str | None = Field(default=None, description="Why the director reacted this way.")


class ReactionInput(ReportArgs):
    raw_feedback: str = Field(description="The director's feedback, VERBATIM.")
    rendered_as_prompted: bool | None = Field(
        default=None, description="Did Suno render what the prompt asked for? True: it did (so a bad result is "
                                  "taste). False: it did not (a prompt-engineering failure). Leave unset if the "
                                  "director has not said.")
    taste_lessons: list[TasteInput] = Field(default_factory=list, description="Lesson candidates, if the "
                                            "feedback states a durable preference. Proposed, never written here.")


class Checked(BaseModel):
    refusals: list[str] = Field(default_factory=list)       # the proposal is wrong as given
    open_questions: list[str] = Field(default_factory=list)  # ask the director before recording
    notes: list[str] = Field(default_factory=list)           # advisory


def check_reaction(inp: ReactionInput) -> Checked:
    """The reaction vocabulary's rules. `disliked` means Suno rendered the prompt and the result is
    not to taste; `prompt_failed` means Suno did not render the prompt's intent. They weigh
    differently in memory (taste versus prompt engineering), so the two are never swapped."""
    out = Checked()
    if not inp.raw_feedback.strip():
        out.refusals.append("raw_feedback is empty: pass the director's own words")
    r, rendered = inp.reaction, inp.rendered_as_prompted
    if r == "disliked" and rendered is False:
        out.refusals.append("reaction 'disliked' means Suno rendered the prompt and the result is not to taste; "
                            "with rendered_as_prompted=false this is 'prompt_failed'")
    if r == "prompt_failed" and rendered is True:
        out.refusals.append("reaction 'prompt_failed' means Suno did not render the prompt's intent; "
                            "with rendered_as_prompted=true this is 'disliked'")
    if r in ("disliked", "prompt_failed") and rendered is None:
        out.open_questions.append(
            "Did Suno render what the prompt asked for? If yes and you did not like it, that is 'disliked' (taste). "
            "If it ignored or mangled the prompt, that is 'prompt_failed' (prompt engineering).")
    if inp.rating is not None:
        if r in UNHEARD:
            out.refusals.append(f"a rating does not apply to '{r}': the track was not heard")
        elif r not in POSITIVE_REACTIONS:
            out.notes.append(f"a rating is unusual for '{r}' (ratings are meaningful for positive reactions)")
    return out
