"""Parse `--select` strings like `"1,3,5-7"` to 0-based index lists."""
from __future__ import annotations


def parse_select(spec: str, *, total: int) -> list[int]:
    """Parse 1-based selection string, return sorted 0-based unique indices.

    Format: comma-separated tokens, each either `N` or `A-B`.
    Raises ValueError on empty input, 0 / negative index, out-of-range
    index, reverse range (`5-3`), or garbage tokens.
    """
    spec = spec.strip()
    if not spec:
        raise ValueError("empty selection string")

    indices: set[int] = set()
    for raw_token in spec.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            a_str, b_str = (p.strip() for p in token.split("-", 1))
            try:
                a, b = int(a_str), int(b_str)
            except ValueError as e:
                raise ValueError(f"bad range token: {token!r}") from e
            if a > b:
                raise ValueError(f"invalid range (reverse): {token!r}")
            for n in range(a, b + 1):
                _add_one_based(indices, n, total)
        else:
            try:
                n = int(token)
            except ValueError as e:
                raise ValueError(f"bad token: {token!r}") from e
            _add_one_based(indices, n, total)

    if not indices:
        raise ValueError("empty selection string")
    return sorted(indices)


def _add_one_based(acc: set[int], n: int, total: int) -> None:
    if n < 1:
        raise ValueError(f"indices are 1-based, got {n}")
    if n > total:
        raise ValueError(f"index {n} out of range (have {total})")
    acc.add(n - 1)
