from __future__ import annotations

import re

from app.models import Claim
from app.services.signals import extract_claim_signals

_SPLIT_RE = re.compile(
    r",(?!\d{3})|;|\s+and\s+|\s+but\s+|\s+however\s+|\s+whereas\s+", re.IGNORECASE
)
_SUBJECT_START_RE = re.compile(
    r"^(our|we|the|its|it|they|this|that|these|those|all|my|his|her|their|there|"
    r"you|your|i|a|an|each|every|most|some|no|not)\b",
    re.IGNORECASE,
)
_VERB_START_RE = re.compile(
    r"^(costs?|supports?|includes?|offers?|requires?|runs?|is|are|was|were|uses?|"
    r"has|have|provides?|depends?|allows?|integrates?|works?|ships?|removes?|"
    r"released?|supports?)\b",
    re.IGNORECASE,
)

# Frames that carry no searchable information ("Our platform uses ...").
_FRAME_RE = re.compile(
    r"\b(our|my|the platform|this platform|their|we|us|i|the product|this product)\b",
    re.IGNORECASE,
)

_CATEGORY_QUERY_HINT = {
    "api_version": "latest version release notes",
    "pricing": "pricing current price",
    "regulation": "current regulation status",
    "integration": "documentation supported integration",
    "company_info": "latest announcement",
    "general": "latest",
}


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_BULLET_RE = re.compile(r"^\s*(?:[-*\u2022\u00b7]+|\d+[.)])\s+")


def _strip_bullet(text: str) -> str:
    return _BULLET_RE.sub("", text).strip()


def _classify_claim(segment: str) -> tuple[str, str]:
    normalized = segment.lower()

    if re.search(r"\b(api|sdk|endpoint|version|v\d+)(?:\s+|\D+)(?:version\s+)?v?\d+(?:\.\d+)*", normalized):
        return "api_version", "high"
    if re.search(r"\$\s?\d+(?:\.\d+)?\s*(?:/|per\s+)(month|year|day|week|quarter|user|seat)", normalized):
        return "pricing", "high"
    if re.search(r"\b(gdpr|ccpa|hipaa|sox|regulation|compliance|policy|law)\b", normalized):
        return "regulation", "high"
    if re.search(r"\b(supports|integrates|works with|compatible with|partner(?:s|ed)? with|connects to)\b", normalized):
        return "integration", "medium"
    if re.search(r"\b(company|product|launch|release|pricing|roadmap|partnership|customer)\b", normalized):
        return "company_info", "medium"
    return "general", "medium"


_VERB_WORDS = {
    "uses", "use", "using", "costs", "cost", "is", "are", "was", "were", "supports",
    "support", "includes", "include", "offers", "provide", "provides", "requires",
    "runs", "has", "have", "ships", "released", "allows", "integrates", "works",
    "depends", "gives", "lets", "makes",
}


_OPINION_RE = re.compile(
    r"\b(i think|i believe|in my (opinion|view)|we believe|arguably|"
    r"best|worst|beautiful|amazing|terrible|awesome|should|must|ought to|"
    r"obviously|clearly the best|love|hate|prefer|feel(s)? like)\b",
    re.IGNORECASE,
)
_PREDICTION_RE = re.compile(
    r"\b(will|won't|going to|expect(ed)? to|forecast|projected|predict|"
    r"by (19|20)\d{2}|next (year|quarter|month|week)|soon|in the future|"
    r"is likely to|are likely to|should reach)\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"\?\s*$|^(what|why|how|when|where|who|which|is|are|can|could|do|does|did)\b",
                          re.IGNORECASE)


def classify_claim_kind(text: str) -> str:
    """fact | opinion | prediction | question.

    Only facts are sent to the evidence engine. Everything else gets a
    non-factual result rather than an invented verdict.
    """
    stripped = text.strip()
    if _QUESTION_RE.search(stripped):
        return "question"
    if _OPINION_RE.search(stripped):
        return "opinion"
    if _PREDICTION_RE.search(stripped):
        return "prediction"
    return "fact"


# Link labels and UI chrome read like imperative sentences ("Deploy on FastAPI
# Cloud", "Follow us on LinkedIn"). They assert nothing, so they are not claims.
_IMPERATIVE_START_RE = re.compile(
    r"^(deploy|follow|install|read|click|try|get|join|subscribe|sign|run|open|visit|"
    r"learn|watch|buy|download|contact|share|report|explore|browse|register|upgrade|"
    r"migrate|contribute|sponsor|hire|book|call|email|send|paste|copy|add|create|"
    r"use|note|see|make|start|keep|ensure|avoid|enable|disable|set|don't|do not|"
    r"configure|connect|refer|check out)\b",
    re.IGNORECASE,
)
_ASSERTION_RE = re.compile(
    r"\b(is|are|was|were|has|have|had|does|do|did|will|would|can|could|may|might|must|"
    r"uses?|using|costs?|requires?|includes?|supports?|offers?|provides?|runs?|ships?|"
    r"releases?|released|allows?|integrates?|works?|depends?|removes?|adds?|becomes?|"
    r"contains?|means?|says?|said|reports?|announced?|launched?|serves?|powers?|"
    r"handles?|returns?|accepts?|stores?|sends?|generates?|enables?|dropped?|deprecated|"
    r"fix(?:es|ed)?|adds?|added|drops?|updates?|updated|upgrades?|implements?|improves?|"
    r"renames?|bumps?|adopts?|migrates?|generates?|ships?|introduces?|patch(?:es|ed)?)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d")


_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+")
# "PR #16739 by @tiangolo" is a bookkeeping reference, not a statement.
_REFERENCE_RE = re.compile(r"\bPR\s*#\d+\b|@[A-Za-z0-9_]+")


def _strip_noise(text: str) -> str:
    cleaned = _EMOJI_RE.sub(" ", text)
    cleaned = _REFERENCE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    return _normalize_space(cleaned).strip(" ·-")


def _alpha_words(text: str) -> list[str]:
    return [word for word in text.split() if len(re.sub(r"[^A-Za-z]", "", word)) >= 2]


def is_assertive(text: str) -> bool:
    """True when a fragment reads as a statement that could be checked."""
    stripped = _strip_noise(text)
    if len(stripped) < 12 or stripped.endswith(":"):
        return False
    if len(_alpha_words(stripped)) < 3:
        return False
    if _IMPERATIVE_START_RE.match(stripped):
        return False
    return bool(_ASSERTION_RE.search(stripped) or _NUMBER_RE.search(stripped))


def _subject_of(sentence: str) -> str:
    """The leading noun phrase a trailing fragment lost when it was split.

    "The Tavily Project plan costs $20/month and includes X" -> "The Tavily Project plan"
    """
    words = sentence.split()
    subject: list[str] = []
    for word in words[:5]:
        bare = re.sub(r"[^\w$]", "", word).lower()
        if bare in _VERB_WORDS:
            break
        subject.append(word)
        if len(subject) == 4:
            break
    if subject:
        return " ".join(subject).rstrip(",:;")
    return " ".join(words[:2]) if len(words) >= 2 else sentence


def _restore_subject(sentence: str, part: str, index: int) -> str:
    """Keep split fragments readable: 'costs $20/month' -> 'Our platform costs $20/month'."""
    if index == 0:
        return part
    if _SUBJECT_START_RE.match(part) or not _VERB_START_RE.match(part):
        return part
    subject = _subject_of(sentence)
    if subject.lower() in part.lower():
        return part
    return f"{subject} {part}"


def build_search_query(claim_text: str, category: str = "general") -> str:
    """Turn a claim into a query a search engine can actually answer."""
    cleaned = _FRAME_RE.sub(" ", claim_text)
    cleaned = re.sub(r"[^\w\s.\-$/,]", " ", cleaned)
    cleaned = re.sub(r",(?!\d{3})", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    words = [word for word in cleaned.split() if len(word) > 1]
    query = " ".join(words[:10]).strip()

    hint = _CATEGORY_QUERY_HINT.get(category, "")
    if hint and hint.split()[0] not in query.lower():
        query = f"{query} {hint}".strip()

    return _normalize_space(query) or claim_text.strip()


def extract_claims(answer: str) -> list[Claim]:
    if not answer or not answer.strip():
        return []

    sentence_chunks = re.split(r"(?<=[.!?])\s+|\n+", answer)
    claims: list[Claim] = []

    for sentence in sentence_chunks:
        cleaned = _normalize_space(_strip_bullet(sentence))
        if not cleaned:
            continue

        parts = _SPLIT_RE.split(cleaned)
        for index, part in enumerate(parts):
            trimmed = _normalize_space(part)
            if not trimmed:
                continue

            trimmed = _normalize_space(_restore_subject(cleaned, trimmed, index))
            trimmed = _strip_noise(trimmed)
            if len(trimmed) < 5:
                continue
            # A fragment must read as a claim: it needs letters and cannot open
            # with a stray digit left over from splitting "100,000 searches".
            if not re.match(r"[A-Za-z\"'(]", trimmed) or len(re.findall(r"[A-Za-z]", trimmed)) < 3:
                continue
            if not is_assertive(trimmed):
                continue

            category, volatility = _classify_claim(trimmed)
            confidence = 0.86 if volatility == "high" else 0.72
            claims.append(
                Claim(
                    text=trimmed,
                    volatility=volatility,
                    category=category,
                    confidence=confidence,
                    signals=extract_claim_signals(trimmed),
                    kind=classify_claim_kind(trimmed),
                )
            )

    if not claims:
        text = _normalize_space(answer)
        claims.append(
            Claim(
                text=text,
                volatility="medium",
                category="general",
                confidence=0.6,
                signals=extract_claim_signals(text),
                kind=classify_claim_kind(text),
            )
        )

    return claims
