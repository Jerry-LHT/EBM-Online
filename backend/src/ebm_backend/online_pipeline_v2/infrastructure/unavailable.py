from ebm_backend.online_pipeline_v2.domain.common import TaskName


class TaskExecutorUnavailable(RuntimeError):
    def __init__(self, task: TaskName) -> None:
        self.task = task
        super().__init__(
            f"No executor adapter is configured for the {task.value} v2 task."
        )

