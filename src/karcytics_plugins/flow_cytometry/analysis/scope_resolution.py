"""Shared helper for resolving which samples a scoped action should affect."""


def resolve_target_samples(
    scope: str,
    group_id: str | None,
    sample_id: str,
    experiment,
) -> list[str]:
    """Return the list of sample IDs affected by a scoped action.

    `scope` is "sample" (just `sample_id`) or "group" (everything in the
    group named by `group_id`, or every sample when `group_id == "all"`).
    """
    if scope == "sample":
        return [sample_id]
    if group_id == "all":
        return list(experiment.samples.keys())
    target_group = experiment.groups.get(group_id) if group_id is not None else None
    return target_group.sample_ids if target_group else [sample_id]
