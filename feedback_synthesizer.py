#!/usr/bin/env python3
"""
Claude Code Feedback Synthesizer

Fetches recent GitHub issues from anthropics/claude-code and generates
a weekly digest for PM review.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from collections import Counter
from typing import TypedDict, Optional


# Configuration
REPO_OWNER = "anthropics"
REPO_NAME = "claude-code"
DAYS_TO_FETCH = 7
CACHE_FILE = "issues_cache.json"


class Issue(TypedDict):
    number: int
    title: str
    body: str
    created_at: str
    comments: int
    html_url: str
    labels: list[str]
    user: str


class CategorizedIssue(TypedDict):
    issue: Issue
    category: str
    confidence: str


# Category keywords for classification
CATEGORY_KEYWORDS = {
    "bug": [
        "bug", "error", "crash", "broken", "fail", "not working", "doesn't work",
        "issue", "problem", "exception", "traceback", "unexpected", "wrong"
    ],
    "feature_request": [
        "feature", "request", "add", "support", "would be nice", "suggestion",
        "enhance", "improvement", "could you", "please add", "wish", "proposal"
    ],
    "ux_confusion": [
        "confusing", "unclear", "how do i", "how to", "don't understand",
        "unexpected behavior", "intuitive", "ux", "user experience", "hard to"
    ],
    "documentation": [
        "doc", "documentation", "readme", "example", "tutorial", "guide",
        "instructions", "typo", "clarify", "explain"
    ],
}


def fetch_issues(days: int = DAYS_TO_FETCH) -> list[Issue]:
    """Fetch issues from GitHub API created in the last N days."""
    since_date = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    params = f"?state=all&since={since_date}&per_page=100&sort=created&direction=desc"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Claude-Code-Feedback-Synthesizer"
    }

    issues: list[Issue] = []
    page = 1

    while True:
        request_url = f"{url}{params}&page={page}"
        req = Request(request_url, headers=headers)

        try:
            with urlopen(req) as response:
                data = json.loads(response.read().decode())

                if not data:
                    break

                for item in data:
                    # Skip pull requests (they also appear in issues endpoint)
                    if "pull_request" in item:
                        continue

                    # Filter to only issues created within our date range
                    created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                    cutoff = datetime.now(created.tzinfo) - timedelta(days=days)

                    if created < cutoff:
                        continue

                    issues.append({
                        "number": item["number"],
                        "title": item["title"],
                        "body": item.get("body") or "",
                        "created_at": item["created_at"],
                        "comments": item["comments"],
                        "html_url": item["html_url"],
                        "labels": [label["name"] for label in item.get("labels", [])],
                        "user": item["user"]["login"]
                    })

                page += 1

                # GitHub API rate limiting - stop if we've gone through enough pages
                if page > 10:
                    break

        except HTTPError as e:
            print(f"HTTP Error {e.code}: {e.reason}")
            break

    return issues


def categorize_issue(issue: Issue) -> CategorizedIssue:
    """Categorize a single issue based on title, body, and labels."""
    text = f"{issue['title']} {issue['body']}".lower()
    labels = [label.lower() for label in issue["labels"]]

    # First check labels for explicit categorization
    label_mapping = {
        "bug": "bug",
        "feature": "feature_request",
        "enhancement": "feature_request",
        "documentation": "documentation",
        "docs": "documentation",
        "question": "ux_confusion",
    }

    for label in labels:
        for label_key, category in label_mapping.items():
            if label_key in label:
                return {"issue": issue, "category": category, "confidence": "high"}

    # Fall back to keyword matching
    scores: dict[str, int] = {cat: 0 for cat in CATEGORY_KEYWORDS}

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[category] += 1

    # Get category with highest score
    max_score = max(scores.values())
    if max_score > 0:
        category = max(scores, key=scores.get)
        confidence = "high" if max_score >= 3 else "medium" if max_score >= 2 else "low"
        return {"issue": issue, "category": category, "confidence": confidence}

    return {"issue": issue, "category": "other", "confidence": "low"}


def categorize_all_issues(issues: list[Issue]) -> list[CategorizedIssue]:
    """Categorize all issues."""
    return [categorize_issue(issue) for issue in issues]


def extract_themes_by_category(categorized_issues: list[CategorizedIssue]) -> dict[str, list[str]]:
    """Extract common themes from issues, grouped by category."""
    # Common words to ignore
    stopwords = {
        # Basic English stopwords
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "to", "of",
        "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
        "during", "before", "after", "above", "below", "between", "under",
        "again", "further", "then", "once", "here", "there", "when", "where",
        "why", "how", "all", "each", "few", "more", "most", "other", "some",
        "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
        "very", "just", "and", "but", "if", "or", "because", "until", "while",
        "this", "that", "these", "those", "i", "me", "my", "myself", "we", "our",
        "you", "your", "he", "him", "his", "she", "her", "it", "its", "they",
        "them", "their", "what", "which", "who", "whom", "claude", "code", "use",
        "using", "used", "get", "got", "like", "also", "see", "try", "trying",
        "want", "work", "works", "working", "issue", "error", "file", "files",
        # Debug/log noise - stack traces and system info
        "version", "root", "context", "traceback", "path", "directory", "command",
        "terminal", "output", "line", "node", "python", "bash", "shell", "sudo",
        "stderr", "stdout", "debug", "info", "warn", "fatal", "stack", "trace",
        "exception", "null", "undefined", "true", "false", "none", "string",
        "number", "object", "array", "function", "module", "import", "export",
        "const", "return", "async", "await", "process", "system", "user", "users",
        "home", "local", "global", "package", "packages", "install", "installed",
        # GitHub template noise
        "https", "github", "anthropic", "anthropics", "existing", "searched",
        "checked", "confirm", "expected", "actual", "behavior", "steps", "reproduce",
        "environment", "operating", "logs", "relevant", "additional", "information",
        # Title prefix noise (from [BUG], [FEATURE REQUEST], etc.)
        "feature", "request", "feat", "enhancement", "critical", "minor", "major"
    }

    # Group issues by category
    category_groups: dict[str, list[CategorizedIssue]] = {}
    for item in categorized_issues:
        cat = item["category"]
        if cat not in category_groups:
            category_groups[cat] = []
        category_groups[cat].append(item)

    # Extract themes for each category
    themes_by_category: dict[str, list[str]] = {}

    for category, items in category_groups.items():
        word_counts: Counter = Counter()

        for item in items:
            # Only use titles for cleaner signal
            text = item['issue']['title'].lower()
            # Extract words (alphanumeric only, 4+ chars)
            words = re.findall(r'\b[a-z]{4,}\b', text)
            words = [w for w in words if w not in stopwords]
            word_counts.update(words)

        # Get top themes for this category
        themes = []
        for word, count in word_counts.most_common(5):
            if count >= 2:  # At least 2 mentions within category
                themes.append(f"{word} ({count})")

        if themes:
            themes_by_category[category] = themes[:3]  # Top 3 per category

    return themes_by_category


def is_template_line(line: str) -> bool:
    """Check if a line looks like issue template boilerplate."""
    line = line.strip()

    # Skip empty lines
    if not line:
        return True

    # Skip markdown headers and formatting
    if line.startswith(("**", "###", "##", "#", "---", "```", "- [", "- [x]", "* [")):
        return True

    # Skip common template phrases
    template_phrases = [
        "preflight checklist", "i have searched", "i have checked",
        "bug report", "feature request", "describe the bug",
        "steps to reproduce", "expected behavior", "actual behavior",
        "screenshots", "additional context", "environment",
        "operating system", "version:", "node version", "npm version",
        "to reproduce", "relevant log", "checklist"
    ]
    line_lower = line.lower()
    for phrase in template_phrases:
        if phrase in line_lower:
            return True

    # Skip lines that look like key-value pairs (e.g., "OS: macOS")
    if re.match(r'^[A-Za-z\s]+:\s*\S+', line) and len(line) < 80:
        return True

    # Skip lines that look like code or logs
    if line.startswith(("/", "at ", "Error:", "TypeError", "SyntaxError")):
        return True

    return False


def score_quote_sentiment(text: str) -> int:
    """Score a quote based on sentiment/feedback value."""
    text_lower = text.lower()
    score = 0

    # High-value sentiment words
    sentiment_words = {
        "frustrated": 3, "frustrating": 3, "annoying": 3, "annoyed": 3,
        "love": 3, "great": 2, "awesome": 2, "amazing": 2,
        "wish": 2, "hope": 2, "would be nice": 3,
        "broken": 2, "confused": 2, "confusing": 2, "unclear": 2,
        "difficult": 2, "hard to": 2, "impossible": 3,
        "doesn't work": 3, "not working": 3, "stopped working": 3,
        "please": 1, "need": 1, "important": 2, "critical": 3,
        "unfortunately": 2, "disappointed": 3, "expected": 1,
        "but": 1, "however": 1, "instead": 1,
        "keeps": 2, "always": 1, "never": 2, "every time": 2,
        "can't": 2, "cannot": 2, "unable": 2,
        "should": 1, "shouldn't": 2, "why": 1,
        "better": 1, "worse": 2, "terrible": 3, "horrible": 3,
        "useful": 2, "helpful": 2, "useless": 3,
    }

    for word, weight in sentiment_words.items():
        if word in text_lower:
            score += weight

    # Bonus for first-person perspective (actual user experience)
    if re.search(r'\b(i|my|me|we|our)\b', text_lower):
        score += 1

    return score


def is_boilerplate_sentence(text: str) -> bool:
    """Check if a sentence looks like template or boilerplate content."""
    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Skip sentences ending with colon followed by number (e.g., "Would be helpful to know: 1.")
    if re.search(r':\s*\d+\.?\s*$', text_stripped):
        return True

    # Skip sentences containing test/issue boilerplate
    boilerplate_patterns = [
        r'test coverage',
        r'issue #\d+',
        r'medium\s*-\s*feature',
        r'low\s*-\s*feature',
        r'high\s*-\s*feature',
        r'discovered during',
        r'test file:',
        r'workaround',
        r'manual verification',
        r'preflight',
        r'checklist',
    ]
    for pattern in boilerplate_patterns:
        if re.search(pattern, text_lower):
            return True

    # Skip if it looks like a list intro or header
    if text_stripped.endswith(':') or text_stripped.endswith('::'):
        return True

    # Skip numbered list items that are just labels
    if re.match(r'^\d+\.\s*\w+:?\s*$', text_stripped):
        return True

    return False


def get_representative_quotes(categorized_issues: list[CategorizedIssue]) -> list[dict]:
    """Extract representative quotes from issues."""
    candidate_quotes = []

    for item in categorized_issues:
        issue = item["issue"]
        body = issue["body"]

        if not body or len(body) < 50:
            continue

        # Split into lines and filter out template boilerplate
        lines = body.split('\n')
        clean_lines = [line.strip() for line in lines if not is_template_line(line)]

        # Rejoin and split into sentences
        clean_text = ' '.join(clean_lines)
        sentences = re.split(r'(?<=[.!?])\s+', clean_text)

        for sentence in sentences:
            sentence = sentence.strip()

            # Skip if too short (must be 50+ chars) or too long
            if len(sentence) < 50 or len(sentence) > 350:
                continue

            # Skip if still looks like template/technical content
            if is_template_line(sentence):
                continue

            # Skip boilerplate sentences
            if is_boilerplate_sentence(sentence):
                continue

            # Score the quote
            score = score_quote_sentiment(sentence)

            # Only keep quotes with strong emotional signal (score >= 2)
            if score >= 2:
                candidate_quotes.append({
                    "text": sentence,
                    "issue_number": issue["number"],
                    "category": item["category"],
                    "score": score
                })

    # Sort by score and return top quotes
    candidate_quotes.sort(key=lambda x: x["score"], reverse=True)

    # Return top 5, removing duplicates
    seen_issues = set()
    quotes = []
    for quote in candidate_quotes:
        if quote["issue_number"] not in seen_issues:
            seen_issues.add(quote["issue_number"])
            quotes.append(quote)
        if len(quotes) >= 5:
            break

    return quotes


def generate_digest(categorized_issues: list[CategorizedIssue]) -> str:
    """Generate a markdown digest from categorized issues."""
    now = datetime.utcnow()
    week_start = now - timedelta(days=DAYS_TO_FETCH)

    # Calculate category counts
    category_counts: Counter = Counter(item["category"] for item in categorized_issues)

    # Get top discussed issues
    top_discussed = sorted(
        categorized_issues,
        key=lambda x: x["issue"]["comments"],
        reverse=True
    )[:3]

    # Extract themes and quotes
    themes_by_category = extract_themes_by_category(categorized_issues)
    quotes = get_representative_quotes(categorized_issues)

    # Category display config
    category_labels = {
        "bug": "🐛 Bugs",
        "feature_request": "✨ Feature Requests",
        "ux_confusion": "😕 UX Confusion",
        "documentation": "📚 Documentation",
        "other": "📋 Other"
    }

    # Build markdown
    md = []
    md.append(f"# Claude Code Weekly Feedback Digest")
    md.append(f"**Period:** {week_start.strftime('%B %d')} - {now.strftime('%B %d, %Y')}")
    md.append("")

    # Summary
    md.append("## Summary")
    md.append(f"**Total issues opened:** {len(categorized_issues)}")
    md.append("")

    # Category breakdown with themes inline
    md.append("## Category Breakdown")
    md.append("")

    for category, label in category_labels.items():
        count = category_counts.get(category, 0)
        if count == 0:
            continue
        percentage = (count / len(categorized_issues) * 100) if categorized_issues else 0
        themes = themes_by_category.get(category, [])
        theme_str = f" — *{', '.join(themes)}*" if themes else ""
        md.append(f"- {label}: **{count}** ({percentage:.0f}%){theme_str}")
    md.append("")

    # Top discussed
    md.append("## Top 3 Most-Discussed Issues")
    md.append("")
    for i, item in enumerate(top_discussed, 1):
        issue = item["issue"]
        md.append(f"### {i}. [{issue['title']}]({issue['html_url']})")
        md.append(f"- **Comments:** {issue['comments']}")
        md.append(f"- **Category:** {item['category'].replace('_', ' ').title()}")
        md.append(f"- **Opened by:** @{issue['user']}")
        md.append("")

    # Representative quotes
    md.append("## Representative User Feedback")
    md.append("")
    if quotes:
        for quote in quotes:
            md.append(f"> \"{quote['text']}\"")
            md.append(f"> — Issue #{quote['issue_number']} ({quote['category'].replace('_', ' ')})")
            md.append("")
    else:
        md.append("*No representative quotes extracted this week.*")

    # Footer
    md.append("---")
    md.append(f"*Generated on {now.strftime('%Y-%m-%d %H:%M UTC')} by Claude Code Feedback Synthesizer*")

    return "\n".join(md)


def load_cached_issues() -> Optional[list[Issue]]:
    """Load issues from cache if available."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
            print(f"Loaded {len(data)} issues from cache")
            return data
    return None


def save_issues_to_cache(issues: list[Issue]) -> None:
    """Save issues to cache file."""
    with open(CACHE_FILE, "w") as f:
        json.dump(issues, f)
    print(f"Cached {len(issues)} issues to {CACHE_FILE}")


def main():
    """Main entry point."""
    use_cache = "--cache" in sys.argv

    if use_cache:
        issues = load_cached_issues()
        if not issues:
            print("No cache found. Fetching from GitHub...")
            use_cache = False

    if not use_cache:
        print(f"Fetching issues from {REPO_OWNER}/{REPO_NAME}...")
        issues = fetch_issues()
        print(f"Found {len(issues)} issues from the last {DAYS_TO_FETCH} days")
        if issues:
            save_issues_to_cache(issues)

    if not issues:
        print("No issues found. Try again later or use --cache if you have cached data.")
        return

    print("Categorizing issues...")
    categorized = categorize_all_issues(issues)

    print("Generating digest...")
    digest = generate_digest(categorized)

    # Write to file
    output_file = "weekly_digest.md"
    with open(output_file, "w") as f:
        f.write(digest)

    print(f"Digest written to {output_file}")
    print("\n" + "=" * 50 + "\n")
    print(digest)


if __name__ == "__main__":
    main()
