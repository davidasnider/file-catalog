from enum import Enum


class TaskStatus(str, Enum):
    FAILED = "FAILED"


status = TaskStatus.FAILED
print(hasattr(status, "name"))
print(status.name)
print(str(status))
