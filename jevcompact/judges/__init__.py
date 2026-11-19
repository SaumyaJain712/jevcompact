from .base import Judge, JudgeError, JudgeResponse, Question
from .mock import MockJudge

__all__ = ["Judge", "JudgeError", "JudgeResponse", "Question", "MockJudge", "build_judge"]


def build_judge(config) -> Judge:
    if config.judge == "jev":
        from .jev import JevJudge  # added in phase (b)

        return JevJudge.from_config(config)
    return MockJudge()
