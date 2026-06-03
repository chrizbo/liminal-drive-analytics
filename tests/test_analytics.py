"""Tests for rising/stale/hub analytics logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from analytics import (rising_docs, stale_docs,
                       STALE_WINDOW_DAYS, STALE_RECENT_MAX, STALE_HISTORY_MIN)
from utils import direness_score, severity_label, doc_url


# ── Fixtures ──────────────────────────────────────────────────────────────────

TITLES = {
    "doc_a": "Active Doc",
    "doc_b": "Rising Doc",
    "doc_c": "Stale Hub",
    "doc_d": "Quiet Doc",
    "doc_e": "New Doc",
}

ACTIVITY = {
    "doc_a": {"recent": 10, "prior": 10},
    "doc_b": {"recent": 30, "prior": 5},   # rising
    "doc_c": {"recent": 0,  "prior": 8},   # stale
    "doc_d": {"recent": 1,  "prior": 20},  # dropping
    "doc_e": {"recent": 0,  "prior": 0},   # never active
}

IN_DEGREE = [("doc_c", 3), ("doc_b", 1), ("doc_a", 0), ("doc_d", 0), ("doc_e", 0)]


# ── rising_docs ───────────────────────────────────────────────────────────────

def test_rising_detects_gain():
    results = rising_docs(ACTIVITY, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_b" in ids

def test_rising_excludes_stable():
    results = rising_docs(ACTIVITY, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_a" not in ids

def test_rising_excludes_never_active():
    results = rising_docs(ACTIVITY, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_e" not in ids

def test_rising_sorted_by_gain():
    results = rising_docs(ACTIVITY, TITLES, top_n=10)
    gains = [r[1] for r in results]
    assert gains == sorted(gains, reverse=True)

def test_rising_respects_top_n():
    results = rising_docs(ACTIVITY, TITLES, top_n=1)
    assert len(results) <= 1


# ── stale_docs ────────────────────────────────────────────────────────────────

STALE_ACT = {
    "doc_c": {"recent_30d": 0, "history_total": 80,  "history_daily_avg": 0.9},
    "doc_d": {"recent_30d": 1, "history_total": 60,  "history_daily_avg": 0.7},
    "doc_e": {"recent_30d": 0, "history_total": 0,   "history_daily_avg": 0.0},
    "doc_a": {"recent_30d": 10,"history_total": 100, "history_daily_avg": 1.1},
}

def test_stale_detects_hub_gone_cold():
    results = stale_docs(STALE_ACT, IN_DEGREE, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_c" in ids

def test_stale_excludes_active():
    results = stale_docs(STALE_ACT, IN_DEGREE, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_a" not in ids

def test_stale_excludes_never_active_no_links():
    results = stale_docs(STALE_ACT, IN_DEGREE, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_e" not in ids

def test_stale_respects_recent_max():
    # doc_a has recent_30d=10 which is > STALE_RECENT_MAX, should not be stale
    results = stale_docs(STALE_ACT, IN_DEGREE, TITLES, top_n=10)
    ids = [r[0] for r in results]
    assert "doc_a" not in ids

def test_stale_hubs_ranked_first():
    results = stale_docs(STALE_ACT, IN_DEGREE, TITLES, top_n=10)
    if len(results) >= 2:
        # doc_c has in_degree=3, should rank highest
        assert results[0][0] == "doc_c"


# ── direness_score ────────────────────────────────────────────────────────────

def test_stale_hub_scores_high():
    assert direness_score("high", in_deg_count=3) >= 8

def test_stale_hub_capped_at_10():
    assert direness_score("high", in_deg_count=100) == 10

def test_rising_scores_medium():
    score = direness_score("medium", gain=5)
    assert 4 <= score <= 7

def test_low_scores_low():
    score = direness_score("low", prior_act=10)
    assert score <= 5

def test_scores_increase_with_signal():
    assert direness_score("high", in_deg_count=5) > direness_score("high", in_deg_count=1)


# ── severity_label ────────────────────────────────────────────────────────────

def test_critical_label():
    assert "Critical" in severity_label(9)
    assert "Critical" in severity_label(10)

def test_serious_label():
    assert "Serious" in severity_label(7)

def test_low_label():
    assert "Low" in severity_label(1)

def test_all_scores_have_labels():
    for score in range(11):
        label = severity_label(score)
        assert label and len(label) > 0


# ── doc_url ───────────────────────────────────────────────────────────────────

def test_doc_url_returns_stored_url():
    assert doc_url("abc123", "https://example.com") == "https://example.com"

def test_doc_url_constructs_doc_url():
    url = doc_url("abc123", "")
    assert "abc123" in url
    assert "docs.google.com" in url

def test_doc_url_constructs_slides_url():
    url = doc_url("abc123", "", mime="application/vnd.google-apps.presentation")
    assert "presentation" in url
    assert "abc123" in url
