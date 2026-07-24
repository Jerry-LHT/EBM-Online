from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.application.use_cases.run_q2pico import RunQ2PICO
from ebm_backend.online_pipeline.domain.question import QuestionPICO


@dataclass
class _FakeQ2PICO:
    calls: list[dict[str, object]] = field(default_factory=list)

    def run(self, *, question_text: str, expand_outcomes: bool = True) -> QuestionPICO:
        self.calls.append(
            {
                "question_text": question_text,
                "expand_outcomes": expand_outcomes,
            }
        )
        return QuestionPICO(P=["adults"], O_expanded=["quality of life"])


def test_run_q2pico_delegates_to_business_capability() -> None:
    q2pico = _FakeQ2PICO()
    use_case = RunQ2PICO(q2pico=q2pico)

    result = use_case.execute(
        question_text="Should adults receive treatment?",
        expand_outcomes=True,
    )

    assert result == QuestionPICO(P=["adults"], O_expanded=["quality of life"])
    assert q2pico.calls == [
        {
            "question_text": "Should adults receive treatment?",
            "expand_outcomes": True,
        }
    ]
