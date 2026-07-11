"""core/dupes.py: candidate scoring and dismissal persistence."""
from __future__ import annotations

from admin.core import dupes


def _w(slug, worldname="", author="", publishdate="", norm_name="", base_name="",
       version_token="", zip_sha256=None, payload_sha256=None):
    return dupes.WorldForDupes(
        slug=slug, worldname=worldname or slug, author=author, publishdate=publishdate,
        norm_name=norm_name or worldname.lower(), base_name=base_name or norm_name or worldname.lower(),
        version_token=version_token, zip_sha256=zip_sha256, payload_sha256=payload_sha256,
    )


def test_identical_payload_scores_1_and_beats_identical_zip():
    a = _w("a", norm_name="city", base_name="city", zip_sha256="zh1", payload_sha256="ph1")
    b = _w("b", norm_name="city redux", base_name="city", zip_sha256="zh2", payload_sha256="ph1")
    pairs = dupes.score_pairs([a, b])
    reasons = {p.reason for p in pairs}
    assert "identical_payload" in reasons
    assert "identical_zip" not in reasons  # payload identity supersedes zip identity
    p = next(p for p in pairs if p.reason == "identical_payload")
    assert p.score == 1.00
    assert p.a_slug == "a" and p.b_slug == "b"


def test_identical_zip_only_when_payload_unknown():
    a = _w("a", norm_name="city one", base_name="city one", zip_sha256="zh1")
    b = _w("b", norm_name="city two", base_name="city two", zip_sha256="zh1")
    pairs = dupes.score_pairs([a, b])
    assert any(p.reason == "identical_zip" and p.score == 0.98 for p in pairs)


def test_version_chain_needs_a_version_token_on_at_least_one_side():
    a = _w("a", norm_name="city v2", base_name="city", version_token="v2")
    b = _w("b", norm_name="city", base_name="city")
    pairs = dupes.score_pairs([a, b])
    assert any(p.reason == "version_chain" and p.score == 0.90 for p in pairs)


def test_same_base_name_without_version_token_is_not_a_version_chain():
    # Two unrelated worlds could coincidentally share a base_name after
    # normalization with no version tokens at all — shouldn't be flagged.
    a = _w("a", norm_name="city", base_name="city")
    b = _w("b", norm_name="city", base_name="city")
    pairs = dupes.score_pairs([a, b])
    assert not any(p.reason == "version_chain" for p in pairs)
    # but it should still be flagged as near_name (identical norm_name)
    assert any(p.reason == "near_name" for p in pairs)


def test_near_name_uses_sequence_matcher_ratio_as_score():
    a = _w("a", norm_name="downtown skyline project", base_name="downtown skyline project")
    b = _w("b", norm_name="downtown skyline projct", base_name="downtown skyline projct")
    pairs = dupes.score_pairs([a, b])
    p = next(p for p in pairs if p.reason == "near_name")
    assert p.score >= dupes.NEAR_NAME_CUTOFF


def test_dissimilar_names_produce_no_pair():
    a = _w("a", norm_name="a giant medieval castle complex", base_name="a giant medieval castle complex")
    b = _w("b", norm_name="tiny beach hut on stilts", base_name="tiny beach hut on stilts")
    assert dupes.score_pairs([a, b]) == []


def test_same_author_similar_requires_author_ratio_and_date_window():
    a = _w("a", author="dante", publishdate="2024-01-01",
           norm_name="olympics complex alpha", base_name="olympics complex alpha")
    b = _w("b", author="dante", publishdate="2024-01-15",
           norm_name="olympics complex beta", base_name="olympics complex beta")
    pairs = dupes.score_pairs([a, b])
    p = next((p for p in pairs if p.reason == "same_author_similar"), None)
    assert p is not None
    assert p.score == 0.70 + 0.3 * SequenceMatcherRatio(a.norm_name, b.norm_name)


def SequenceMatcherRatio(x, y):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, x, y).ratio()


def test_same_author_similar_rejected_outside_date_window():
    a = _w("a", author="dante", publishdate="2020-01-01",
           norm_name="olympics complex alpha", base_name="olympics complex alpha")
    b = _w("b", author="dante", publishdate="2024-01-01",
           norm_name="olympics complex beta", base_name="olympics complex beta")
    pairs = dupes.score_pairs([a, b])
    assert not any(p.reason == "same_author_similar" for p in pairs)


def test_each_pair_reported_at_most_once_per_reason_and_a_before_b():
    a = _w("zzz", norm_name="city", base_name="city", zip_sha256="zh1", payload_sha256="ph1")
    b = _w("aaa", norm_name="city", base_name="city", zip_sha256="zh1", payload_sha256="ph1")
    pairs = dupes.score_pairs([a, b])
    assert len(pairs) == len({(p.a_slug, p.b_slug, p.reason) for p in pairs})
    for p in pairs:
        assert p.a_slug < p.b_slug


# --- dismissal persistence ----------------------------------------------------

def test_append_dismissal_creates_and_appends(tmp_path):
    p = tmp_path / "dupe_dismissals.yaml"
    dupes.append_dismissal(p, "b-slug", "a-slug", "near_name", note="not actually the same")
    entries = dupes.load_dismissals(p)
    assert len(entries) == 1
    assert entries[0]["a_slug"] == "a-slug"  # sorted
    assert entries[0]["b_slug"] == "b-slug"
    assert entries[0]["reason"] == "near_name"
    assert entries[0]["note"] == "not actually the same"
    assert "at" in entries[0]

    dupes.append_dismissal(p, "c-slug", "a-slug", "version_chain")
    assert len(dupes.load_dismissals(p)) == 2


def test_load_dismissals_missing_file_returns_empty(tmp_path):
    assert dupes.load_dismissals(tmp_path / "nope.yaml") == []
