"""Normalize legacy Agent instructions into the single work_rules field."""


def merge_work_rules(behavior, boundaries):
    execution = (behavior or "").strip()
    boundary = (boundaries or "").strip()
    if not execution:
        return boundary or None
    if not boundary or boundary == execution:
        return execution
    return f"执行方式\n{execution}\n\n工作边界\n{boundary}"
