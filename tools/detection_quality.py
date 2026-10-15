"""Enforce explicit, reproducible synthetic detection regression floors."""


def failures(stats, occurrences, precision_hits, precision_total, policy):
    precision = policy["precision"]
    if not isinstance(precision, (int, float)) or isinstance(precision, bool) or not 0 <= precision <= 1:
        raise ValueError("Invalid precision floor")
    errors = []
    for label, counters in (("values", stats), ("occurrences", occurrences)):
        for name, minimum in policy[label].items():
            if not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or not 0 <= minimum <= 1:
                raise ValueError(f"Invalid detection floor: {label}/{name}")
            counts = counters.get(tuple(name.split("/", 1)), (0, 0))
            hits, total = counts
            if total <= 0 or not 0 <= hits <= total or hits / total < minimum:
                errors.append(f"{label}/{name}: {hits}/{total}; minimum {minimum:.1%}")
    if precision_total <= 0 or precision_hits / precision_total < policy["precision"]:
        errors.append(f"precision: {precision_hits}/{precision_total}; minimum {policy['precision']:.1%}")
    return errors
