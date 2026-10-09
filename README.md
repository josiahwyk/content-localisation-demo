# Proof-Content Localization Engine

A small AI-in-the-loop CLI tool exploring how far AI can go before a team needs to hire more people
to get more content output. Many B2B companies have real, published proof content — customer stories,
blog case studies — but repackaging one of them for a new audience, region, or channel is manual,
one-off work today. This tool takes a single real, already-published proof point and reframes it —
same facts, same underlying story — for a different audience, region, job function, and platform,
without ever inventing a new claim. The intent isn't just a marketing-team tool: the same mechanism
works as an employee-advocacy tool — anyone at a company, not only marketing, can get a base post plus
a few prompting questions and finish it in their own voice for a social post, email, or tweet.

## Design principles

- **Never invent.** The system prompt hard-bans introducing any quote, number, or outcome not
  present in the source record. A programmatic fact-check pass then cross-checks every number in
  the generated output against the source record and flags anything that doesn't trace back —
  a second, independent guardrail on top of the prompt instruction, not a replacement for it.
- **AI drafts, a human ships.** Every output is explicitly marked for review. Nothing here
  auto-publishes.
- **Voice matters more on some platforms than others.** Short/mechanical formats (a tweet, an
  Instagram caption) get a near-finished draft. Long-form, voice-driven formats (LinkedIn, a
  blog post) intentionally get *less* — an angle, a few talking points, and some prompting
  questions, not finished prose. AI-written long-form content reads as generic, and a
  trust-sensitive customer category can't afford that.
- **The proof library only ever holds real, already-published facts.** Adding a new source
  requires either pasting text or a URL — Claude extracts only what's explicitly stated (leaving
  fields blank rather than guessing), and nothing is saved to the library until a human confirms
  the extraction looks right.

## Commands

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# See what's in the proof library
python3 proof_localize.py list-sources

# See the exact prompt with no API call (free, no key needed)
python3 proof_localize.py localize --source acme_co \
    --audience smb --region region_1 --role sales --platform twitter --dry-run

# Generate for real
python3 proof_localize.py localize --source acme_co \
    --audience smb --region region_1 --role sales --platform twitter

# Add a new real proof point (preview only, until --confirm)
python3 proof_localize.py add-source --text-file story.txt
python3 proof_localize.py add-source --text-file story.txt --confirm

# Plain-language request instead of flags
python3 proof_localize.py ask "give me a LinkedIn post about our region_1 enterprise customer for a region_4 marketing audience"
```

Four axes drive every generation: **audience** (smb/enterprise), **region**, **role** (who the
output is for — marketing, sales, or other), and **platform** (tweet, IG caption/story/reel,
LinkedIn, blog). Platform automatically determines draft vs. scaffold mode.

## Why this shape

Content and proof points only compound if they're reusable across every region, segment, and role
that could use them — one video on one webpage doesn't scale that way. This tool tests whether the
repackaging step can be safely AI-assisted — with guardrails strict enough for a trust-sensitive
category — without ever fabricating a new claim, and without needing to add headcount to get more
usable content out of what's already real and already public.

## Status and roadmap

Working prototype, tested with real Anthropic API calls against real published proof points from
a public company website. Not connected to any production system — the proof library in this repo
is placeholder/example data for demonstration purposes.

Not yet built: a point-and-click front end (currently CLI-only), and a centralized place to store
and track generated outputs (currently they just print to the terminal). Both are deliberately
scoped to be built once there's a real destination/team to build them for, rather than guessed at
in advance.

## License

All rights reserved. See [LICENSE](LICENSE). No permission is granted to use, copy, modify or distribute this code without prior written permission.
