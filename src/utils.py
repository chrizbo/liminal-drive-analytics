"""Pure utility functions with no Streamlit or Google API dependencies."""


def doc_url(doc_id, url, mime=""):
    """Return a usable URL — stored one if available, otherwise construct from ID."""
    if url:
        return url
    if "presentation" in mime:
        return f"https://docs.google.com/presentation/d/{doc_id}"
    return f"https://docs.google.com/document/d/{doc_id}"


def mime_icon(mime):
    if "document" in mime:
        return "📄"
    if "presentation" in mime:
        return "📊"
    return "📁"


def direness_score(priority_tier, in_deg_count=0, gain=0, prior_act=0):
    """0–10 score indicating how urgent a Needs Attention item is."""
    if priority_tier == "high":
        return min(10, 6 + in_deg_count)
    elif priority_tier == "medium":
        return min(7, 4 + round(gain / 10))
    else:
        return min(5, 2 + round(prior_act / 10))


def severity_label(score):
    if score >= 9:
        return "🚨 Critical"
    elif score >= 7:
        return "🔴 Serious"
    elif score >= 5:
        return "🟠 Moderate"
    elif score >= 3:
        return "🟡 Minor"
    else:
        return "🔵 Low"
