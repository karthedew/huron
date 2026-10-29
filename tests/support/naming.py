"""Hypothesis strategies for names and relative paths."""

from hypothesis import strategies as st

FIRST = "abcdefghijklmnopqrstuvwxyz0123456789"
REST = FIRST + "_-"

segments = st.builds(
    lambda first, rest: first + rest,
    st.sampled_from(FIRST),
    st.text(alphabet=REST, max_size=20),
).filter(lambda value: value not in {"huron", "metadata"})

path_segments = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc"), blacklist_characters="/\\", max_codepoint=0x2FFF
    ),
    min_size=1,
    max_size=12,
).filter(
    lambda value: (
        value not in {".", ".."}
        and not value.startswith(".huron")
        and not value.endswith(".huron-part")
    )
)
