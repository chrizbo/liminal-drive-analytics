"""Tests for URL classification, normalization, and domain helpers."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import db
import indexer
from indexer import classify_domain, normalize_url, get_apex_domain, truncate


# ── get_apex_domain ───────────────────────────────────────────────────────────

def test_apex_strips_subdomain():
    assert get_apex_domain("en.wikipedia.org") == "wikipedia.org"

def test_apex_preserves_apex():
    assert get_apex_domain("github.com") == "github.com"

def test_apex_deep_subdomain():
    assert get_apex_domain("chrisbutler.substack.com") == "substack.com"

def test_apex_www_stripped_before_call():
    # lstrip("www.") happens in classify_domain before apex is computed
    assert get_apex_domain("substack.com") == "substack.com"


# ── classify_domain ───────────────────────────────────────────────────────────

def test_classify_known_domain():
    domain, apex, rtype = classify_domain("https://github.com/3b1b/manim")
    assert domain == "github.com"
    assert apex == "github.com"
    assert rtype == "github"

def test_classify_subdomain_rolls_up():
    domain, apex, rtype = classify_domain("https://chrisbutler.substack.com/p/foo")
    assert domain == "chrisbutler.substack.com"
    assert apex == "substack.com"
    assert rtype == "substack"

def test_classify_unknown_uses_apex():
    domain, apex, rtype = classify_domain("https://simonwillison.net/2023/article")
    assert domain == "simonwillison.net"
    assert apex == "simonwillison.net"
    assert rtype == "tech_blog"  # in the map

def test_classify_truly_unknown():
    domain, apex, rtype = classify_domain("https://example-random-blog.com/post/1")
    assert domain == "example-random-blog.com"
    assert apex == "example-random-blog.com"
    assert rtype == "example-random-blog.com"  # falls back to apex

def test_classify_empty_url():
    domain, apex, rtype = classify_domain("")
    assert rtype == "unknown"

def test_classify_wikipedia():
    domain, apex, rtype = classify_domain("https://en.wikipedia.org/wiki/Ontology")
    assert domain == "en.wikipedia.org"
    assert apex == "wikipedia.org"
    assert rtype == "wikipedia"


# ── normalize_url ─────────────────────────────────────────────────────────────

def test_normalize_strips_fragment():
    url = normalize_url("https://example.com/page#section")
    assert "#" not in url

def test_normalize_strips_query_for_regular_domain():
    url = normalize_url("https://example.com/page?utm_source=twitter&utm_medium=social")
    assert "utm_source" not in url
    assert "utm_medium" not in url

def test_normalize_youtube_preserves_video_id():
    url = normalize_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=related")
    assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

def test_normalize_youtu_be():
    url = normalize_url("https://youtu.be/dQw4w9WgXcQ")
    assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

def test_normalize_github_preserves_path(monkeypatch):
    import indexer
    monkeypatch.setattr(indexer, "PATH_SIGNIFICANT", {"github.com"})
    url = normalize_url("https://github.com/3b1b/manim?tab=readme")
    assert "3b1b/manim" in url
    assert "tab=" not in url

def test_normalize_github_strips_trailing_slash(monkeypatch):
    import indexer
    monkeypatch.setattr(indexer, "PATH_SIGNIFICANT", {"github.com"})
    url = normalize_url("https://github.com/3b1b/manim/")
    assert not url.endswith("/")

def test_normalize_arxiv_preserves_path(monkeypatch):
    import indexer
    monkeypatch.setattr(indexer, "PATH_SIGNIFICANT", {"arxiv.org"})
    url = normalize_url("https://arxiv.org/abs/2301.07041")
    assert "2301.07041" in url

def test_normalize_reddit_preserves_path(monkeypatch):
    import indexer
    monkeypatch.setattr(indexer, "PATH_SIGNIFICANT", {"reddit.com"})
    url = normalize_url("https://www.reddit.com/r/MachineLearning/comments/abc123/title/")
    assert "MachineLearning" in url
    assert "abc123" in url


# ── truncate ──────────────────────────────────────────────────────────────────

def test_truncate_short_string():
    assert truncate("hello") == "hello"

def test_truncate_exact_length():
    assert truncate("a" * 40) == "a" * 40

def test_truncate_long_string():
    result = truncate("a" * 50)
    assert len(result) == 40
    assert result.endswith("...")

def test_truncate_custom_length():
    result = truncate("hello world", n=8)
    assert len(result) == 8
    assert result == "hello..."


class FakeExecute:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeFiles:
    def list(self, **kwargs):
        return FakeExecute({"files": [{
            "id": "doc-1", "name": "Example Doc",
            "mimeType": "application/vnd.google-apps.document",
            "createdTime": "", "modifiedTime": "", "owners": [], "webViewLink": "",
        }]})


class FakeDrive:
    def files(self):
        return FakeFiles()


class FakeDocuments:
    def get(self, documentId):
        return FakeExecute({"body": {}})


class FakeDocs:
    def documents(self):
        return FakeDocuments()


class FakeActivityQuery:
    def query(self, body):
        return FakeExecute({"activities": []})


class FakeActivity:
    def activity(self):
        return FakeActivityQuery()


def test_run_reports_structured_progress(monkeypatch, tmp_path):
    database_path = str(tmp_path / "progress.db")
    monkeypatch.setattr(indexer, "get_credentials", lambda: object())
    monkeypatch.setattr(
        indexer, "build_services",
        lambda credentials: (FakeDrive(), FakeDocs(), object(), FakeActivity(), object()),
    )
    monkeypatch.setattr(indexer, "connect", lambda path=None: db.connect(database_path))
    events = []

    result = indexer.run(30, False, expand=False, progress=events.append)

    assert result["files_found"] == 1
    assert any(event["phase"] == "indexing" and event["total"] == 1 for event in events)
    assert events[-1]["phase"] == "complete"
