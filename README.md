# Claude Code Feedback Synthesizer

A Product Ops tool that fetches GitHub issues from anthropics/claude-code and generates a weekly digest for PM review.

## What It Does

- Fetches last 7 days of issues from the Claude Code repo
- Categorizes by type (bug, feature request, UX confusion, documentation)
- Identifies top-discussed issues and emerging themes
- Extracts representative user quotes
- Outputs a scannable markdown digest

## Usage
```bash
python feedback_synthesizer.py
```

Output is written to `weekly_digest.md`.

## Built With

Built using Claude Code in ~2 hours.

## Sample Output

See [sample_digest.md](sample_digest.md) for an example output.
