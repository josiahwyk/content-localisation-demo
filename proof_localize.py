#!/usr/bin/env python3
"""
Proof-Content Localization Engine

Problem: many B2B companies already have real, published customer proof
content (video testimonials, case studies) that gets essentially zero
further distribution beyond the one webpage it lives on. This tool takes ONE
real, already-published proof point and reframes it — same facts, same
quote — for a different audience, region, job function, and platform.

It never invents a new story and never generates a brand-new claim. It only
repackages what's already true and already public.

Two output modes, chosen automatically by platform:
  - DRAFT mode  (twitter, ig_caption, ig_story, ig_reel): a near-finished
    piece of copy, since these formats are short/mechanical enough that a
    good draft saves real time.
  - SCAFFOLD mode (linkedin, blog): AI does NOT write finished prose. These
    formats carry a personal point of view and AI-written versions read as
    generic. Output is an angle + dot points + prompting questions — the
    human writes the final draft in their own voice.

Every output is marked for human review. Nothing here auto-publishes.

Requires: pip install anthropic
Set ANTHROPIC_API_KEY in your environment before a real (non --dry-run) run.

Usage
-----
List available seeded proof points:

    python3 proof_localize.py list-sources

See the exact prompt with no API call (free, no key needed):

    python3 proof_localize.py localize --source acme_co \\
        --audience smb --region region_1 --role sales --platform twitter --dry-run

Generate a draft tweet, reframing an enterprise story for an smb audience in
region_1, for a sales rep to use:

    python3 proof_localize.py localize --source acme_co \\
        --audience smb --region region_1 --role sales --platform twitter

Generate a LinkedIn scaffold (not finished prose) for marketing, region_4:

    python3 proof_localize.py localize --source acme_co \\
        --audience enterprise --region region_4 --role marketing --platform linkedin

Add a new real proof point to the library, from pasted story text (Claude
extracts the structured facts, grounded only in the text you give it — it
does NOT invent or infer beyond what's stated). Nothing is saved until you
review the extraction and re-run with --confirm:

    python3 proof_localize.py add-source --text-file customer_story.txt
    python3 proof_localize.py add-source --text-file customer_story.txt --confirm

Or from a URL (best-effort fetch — many pages are JS-rendered and won't
return real content via a simple fetch; if the tool warns the page looks
empty, copy the visible story text from your browser and use --text-file
or --text instead):

    python3 proof_localize.py add-source --url "https://example.com/customer-stories/acme-co" --confirm

Plain-language request instead of flags — Claude maps it onto the structured
parameters above, tells you how it interpreted the request, and asks for
clarification instead of guessing if anything's ambiguous:

    python3 proof_localize.py ask "Give me a LinkedIn post about our \\
        region_1 enterprise customer for a region_4 marketing audience"
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi

LIBRARY_FILE = Path(__file__).parent / "proof_library.json"

# ---------------------------------------------------------------------------
# Seed data used the first time the library file doesn't exist yet. After
# that, proof_library.json on disk is the source of truth — extend it via
# `add-source`, never by editing this dict. Every entry must be a real,
# already-published customer fact — never invented. (The seed entry below is
# fictional placeholder data for this public example.)
# ---------------------------------------------------------------------------
SEED_LIBRARY = {
    "acme_co": {
        "customer_name": "Jordan Reyes",
        "relationship": "long-time customer",
        "region": "region_1",
        "segment": "smb",
        "account_size": 40,
        "quote": "This tool lets us handle 20% more support tickets without adding headcount!",
        "metric": "20% increase in ticket throughput",
        "video_length_sec": 190,
        "source_url": "example.com/customer-stories/acme-co",
    },
}


def load_library():
    if not LIBRARY_FILE.exists():
        LIBRARY_FILE.write_text(json.dumps(SEED_LIBRARY, indent=2))
        return dict(SEED_LIBRARY)
    return json.loads(LIBRARY_FILE.read_text())


def save_library(library):
    LIBRARY_FILE.write_text(json.dumps(library, indent=2))

REGION_CONTEXT = {
    "region_1": "mature market - well established customer base",
    "region_2": "live - recently entered, growing steadily",
    "region_3": "live - recently entered",
    "region_4": "just launched - early phase",
    "region_5": "just launched - early phase",
    "region_6": "no customers yet - early interest, no confirmed launch date",
}

DRAFT_PLATFORMS = {"twitter", "ig_caption", "ig_story", "ig_reel"}
SCAFFOLD_PLATFORMS = {"linkedin", "blog"}

ROLE_FRAMING = {
    "marketing": "a marketing person who needs on-brand, channel-ready copy",
    "sales": "a Sales rep who needs a natural conversation opener or talking point to use with a lead face-to-face or by text, not polished marketing copy",
    "other": "a general external audience (e.g. partner, investor, new hire) who needs plain context, not a sales pitch",
}

PLATFORM_SPEC = {
    "twitter": "a single tweet, max 280 characters, no hashtag spam",
    "ig_caption": "an Instagram feed caption, 2-4 short lines plus up to 3 relevant hashtags",
    "ig_story": "a single short overlay line for an Instagram Story, under 15 words",
    "ig_reel": "a short Reel voiceover/caption hook, 1-2 sentences, spoken-word rhythm",
}

# Illustrative voice anchors for this public example — NOT real quotes from any
# real company, and not facts to reuse. In the real tool, this list holds real,
# published headline/caption copy from your own company's proof content, pulled
# to use as few-shot voice anchors. The pattern to look for: a concrete number
# or outcome leads the sentence, an active verb, zero hype adjectives, and the
# customer's own words used directly rather than paraphrased into "marketing
# voice." Instruction alone ("sound like us") doesn't reliably produce this
# register - real examples do.
VOICE_EXAMPLES = [
    "Cutting Onboarding Time by 40%: How Brightline Rolled Out to Every Site in Six Weeks",
    "If this tool turned off tomorrow, I'd have to hire two more people.",
    "Cutting response time from 3 days to same-day",
    "Saving $18K a year by killing a manual spreadsheet process",
    "Dropping churn from 9% to under 4% in one quarter",
    "Lifting seat utilisation by 30% without adding headcount",
    "Scaling support volume without scaling the team",
]

DRAFT_SYSTEM_PROMPT = """You are an AI-in-the-loop proof-content localization engine for a company's \
field marketing. You are given ONE real, already-published customer proof point (structured facts \
plus their real quote) and asked to reframe it — same facts, same underlying story — for a specific \
target audience, region, job function, and platform. NEVER invent a quote, number, customer detail, or \
outcome that is not present in the source record. If a detail isn't there, leave it out rather than \
guess or generalize. Never corporate jargon. You will be given real examples of the company's actual \
published voice - match their register and rhythm exactly (concrete number/outcome leads the sentence, \
active verb, zero hype adjectives, customer's own words used directly wherever the source record has a \
real quote) - do not copy the examples' content, they're for calibration only, and never let them \
override the NEVER-INVENT rule above. Output valid JSON ONLY matching this schema: \
{"content": string (the platform-ready copy), "notes_for_reviewer": string (1-2 sentences: what was \
reframed and why, so a human reviewer can sanity-check the adaptation fast), \
"status": "DRAFT - human review required before use"}."""

SCAFFOLD_SYSTEM_PROMPT = """You are an AI-in-the-loop proof-content localization engine for a company's \
field marketing. You are given ONE real, already-published customer proof point \
(structured facts plus their real quote) and asked to prepare it for a long-form, voice-driven platform \
(LinkedIn or a blog post). Do NOT write finished prose. AI-written long-form content reads as generic \
and undermines trust in this category - the human must write the final piece in their own voice. Your \
job is only to structure the raw material: identify the single sharpest angle, break it into a short \
flow of dot points a human can write from, and suggest a couple of prompting questions that help the \
human bring their own point of view. These prompting_questions are coaching prompts for the human \
drafter only - they are never shown to the platform's actual audience, so they must never contain \
finished, publishable-sounding phrasing themselves. NEVER invent a quote, number, customer detail, or \
outcome not present in the source record - this applies to prompting_questions too: do not invent a \
hypothetical illustrative number (e.g. a made-up account size) to make a question sound concrete; ask \
the question in the abstract instead (e.g. "what would this mean in dollar terms for a similarly-sized \
customer in this region?" not "...for a 400-seat account?"). You will be given real examples of the \
company's actual published voice - the "angle" you write should match their register (concrete \
number/outcome leads the sentence, active verb, zero hype adjectives) even though the dot points below \
it stay unwritten for the human. Output valid JSON ONLY matching this schema: {"angle": string (the one \
POV or hook worth taking, one sentence), "dot_points": array of 3-6 short strings (talking points in \
flow order, NOT full sentences, NOT a draft), "prompting_questions": array of 2-4 strings (abstract \
coaching questions for the human drafter, no invented numbers), "status": "SCAFFOLD - human writes the \
final draft, do not auto-generate full prose"}."""


def _extract_numbers(text):
    """Pull out numeric tokens (incl. %) for the fact-check pass."""
    return set(re.findall(r"\d+(?:\.\d+)?%?", text))


def _parse_json_response(raw_text):
    """Claude sometimes wraps JSON in a ```json ... ``` fence despite 'JSON ONLY' instructions - strip it before parsing."""
    text = raw_text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    return json.loads(text)


EXTRACTION_SYSTEM_PROMPT = """You extract structured proof-point facts from raw text describing a real, \
already-published customer source (a customer story, blog article, or industry update - not \
necessarily a customer testimonial). ONLY extract facts explicitly stated in the given text. Never infer, \
calculate, round, or fill in a plausible-sounding value. If a field isn't clearly stated in the text, \
output null (or an empty array for array fields) - do not guess. Extract EVERY distinct notable quote \
and EVERY distinct notable fact/result in the text, not just one of each - a long transcript often has \
several. Output valid JSON ONLY matching this schema: {"customer_name": string or null (or null if this \
isn't a customer testimonial), "relationship": string or null (e.g. how long they've been a customer), \
"region": string or null (wherever the source is actually located/about, in the text's own words - do \
not restrict to a fixed region list, just don't invent a location that isn't stated), "segment": one of \
"smb"/"enterprise"/"mixed"/null, "account_size": integer or null, "topic": string or null \
(one-sentence gist, most useful for non-testimonial content like industry news), "quotes": array of \
strings (every distinct direct quote worth keeping, exact wording, may be empty), "key_facts": array of \
strings (every distinct notable result/fact/outcome, in the text's own words, may be empty), \
"video_length_sec": integer or null}."""


def _slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unnamed_source"


def _get_anthropic_client():
    try:
        import anthropic
    except ImportError:
        print("Missing dependency. Run: pip install anthropic --break-system-packages", file=sys.stderr)
        sys.exit(1)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: set ANTHROPIC_API_KEY in your environment.", file=sys.stderr)
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)


def _fetch_url_text(url):
    # Use certifi's bundled CA certificates directly rather than relying on the
    # machine's system certificate store, which macOS Python installs don't
    # always link up correctly (a common "CERTIFICATE_VERIFY_FAILED" cause).
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_proof_facts(raw_text):
    """Core extraction, shared by the CLI and the UI. Returns (extracted_dict, suggested_key)."""
    client = _get_anthropic_client()
    # Long transcripts + extracting multiple quotes/facts (not just one each) need real headroom -
    # a tight budget here risks an empty/truncated response, not just a slow one.
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": raw_text}],
    )
    raw_response_text = response.content[0].text if response.content else ""
    if not raw_response_text.strip():
        raise RuntimeError(
            f"Model returned an empty response (stop_reason: {response.stop_reason}). "
            "This can happen with very long input - try a shorter excerpt, or try again."
        )
    try:
        extracted = _parse_json_response(raw_response_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model output wasn't valid JSON ({e}). Raw output: {raw_response_text[:500]}")
    key = _slugify(extracted.get("customer_name") or "unnamed_source")
    return extracted, key


def cmd_add_source(args):
    if args.url:
        try:
            raw_text = _fetch_url_text(args.url)
        except Exception as e:
            print(f"Error fetching URL: {e}\nTry --text-file or --text instead.", file=sys.stderr)
            sys.exit(1)
        if len(raw_text) < 300:
            print(
                "Warning: fetched page returned very little visible text "
                f"({len(raw_text)} chars) — it may be JS-rendered and this simple fetch can't see the "
                "real content. Copy the story text from your browser and use --text-file or --text "
                "instead for a reliable extraction.",
                file=sys.stderr,
            )
            sys.exit(1)
        source_url = args.url
    elif args.text_file:
        raw_text = Path(args.text_file).read_text().strip()
        source_url = args.source_url or f"(pasted from {args.text_file}, no URL given)"
    else:
        raw_text = args.text.strip()
        source_url = args.source_url or "(pasted text, no URL given)"

    if args.dry_run:
        print("--- DRY RUN: no API call made ---\n")
        print("SYSTEM PROMPT:\n" + EXTRACTION_SYSTEM_PROMPT + "\n")
        print("RAW TEXT GIVEN:\n" + raw_text[:2000] + ("..." if len(raw_text) > 2000 else "") + "\n")
        print("(Run without --dry-run, with ANTHROPIC_API_KEY set, to actually extract.)")
        return

    try:
        extracted, key = extract_proof_facts(raw_text)
    except RuntimeError as e:
        print(f"Extraction failed: {e}", file=sys.stderr)
        sys.exit(1)
    extracted["source_url"] = source_url

    print("EXTRACTED FACTS (grounded only in the text you gave it — review before saving):\n")
    print(json.dumps(extracted, indent=2))
    null_fields = [k for k, v in extracted.items() if v is None]
    if null_fields:
        print(f"\nNote: these fields weren't clearly stated in the source text, so they were left null: {null_fields}")

    if not args.confirm:
        print(f"\nNot saved. If this looks accurate, re-run the same command with --confirm to add it to the "
              f"library as '{key}'.")
        return

    library = load_library()
    if key in library and not args.overwrite:
        print(f"\nError: '{key}' already exists in the library. Re-run with --overwrite to replace it.", file=sys.stderr)
        sys.exit(1)
    library[key] = extracted
    save_library(library)
    print(f"\nSaved to proof_library.json as '{key}'. Use it with: --source {key}")


ASK_SYSTEM_PROMPT = """You translate a plain-language request from a team member into structured \
parameters for the proof-content localization tool. You are given the current library of real, \
already-published proof points (id, customer name, region, segment) and a plain-language request. \
Identify EVERY source in the library that plausibly matches how the request describes the source \
customer (by region, segment, and/or name) - list all of them in "source_candidates", even if there's \
more than one. Separately, name your single best guess in "source" - but do not treat picking one as \
resolving the ambiguity; the caller will force clarification if source_candidates has more than one \
entry, regardless of your best guess. NEVER invent a source id that isn't in the list given. Also \
determine: target audience segment ("smb" or "enterprise"), target region (must be one of region_1, \
region_2, region_3, region_4, region_5, region_6), who the output is for ("marketing", "sales", or \
"other"), and target platform (one of "twitter", "ig_caption", "ig_story", "ig_reel", "linkedin", \
"blog"). If the request doesn't give you enough to confidently determine a field, output null for it \
rather than guessing - do not default to a value that wasn't implied by the request. Output valid JSON \
ONLY matching this schema: {"source": string or null, "source_candidates": array of strings (all \
plausible source ids, may be length 0, 1, or more), "audience": string or null, "region": string or \
null, "role": string or null, "platform": string or null, "interpretation": string (one sentence: how \
you understood the request), "clarification_needed": string or null (what's missing/ambiguous, only if \
any field above is null or source_candidates has more than one entry)}."""


def parse_ask_query(library, query):
    """Core NL parsing, shared by the CLI and the UI. Returns the parsed params dict."""
    library_summary = {
        key: {"customer_name": v.get("customer_name"), "region": v.get("region"), "segment": v.get("segment")}
        for key, v in library.items()
    }
    user_message = f"AVAILABLE SOURCES:\n{json.dumps(library_summary, indent=2)}\n\nPlain-language request: \"{query}\""
    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=400,
        system=ASK_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return _parse_json_response(response.content[0].text)  # raises json.JSONDecodeError on failure


def validate_ask_params(library, parsed):
    """Deterministic checks on a parsed ask result. Returns a list of human-readable problems (empty if clean)."""
    problems = []

    # Ambiguous-source guard: don't trust the model's single "source" best-guess if it also
    # flagged more than one plausible candidate. As the library grows, "the region_1 enterprise
    # customer" can stop being a unique match - force clarification instead of silently picking
    # one, same "don't guess" rule as everywhere else in this tool.
    candidates = parsed.get("source_candidates") or []
    if len(candidates) > 1:
        details = ", ".join(
            f"{key} ({library.get(key, {}).get('customer_name')}, {library.get(key, {}).get('region')}, {library.get(key, {}).get('segment')})"
            for key in candidates
        )
        problems.append(f"Ambiguous source: more than one proof point matches how you described it: {details}")
        return problems  # don't bother checking the rest if source itself is ambiguous

    required = ["source", "audience", "region", "role", "platform"]
    missing = [f for f in required if not parsed.get(f)]
    if missing:
        problems.append(f"Missing: {missing}")
        return problems

    if parsed["source"] not in library:
        problems.append(f"source '{parsed['source']}' isn't in the library")
    if parsed["audience"] not in ("smb", "enterprise"):
        problems.append(f"audience '{parsed['audience']}' isn't smb/enterprise")
    if parsed["region"] not in REGION_CONTEXT:
        problems.append(f"region '{parsed['region']}' isn't a valid region")
    if parsed["role"] not in ROLE_FRAMING:
        problems.append(f"role '{parsed['role']}' isn't marketing/sales/other")
    if parsed["platform"] not in (DRAFT_PLATFORMS | SCAFFOLD_PLATFORMS):
        problems.append(f"platform '{parsed['platform']}' isn't a supported platform")
    return problems


def cmd_ask(args):
    library = load_library()

    if args.dry_run:
        library_summary = {
            key: {"customer_name": v.get("customer_name"), "region": v.get("region"), "segment": v.get("segment")}
            for key, v in library.items()
        }
        user_message = f"AVAILABLE SOURCES:\n{json.dumps(library_summary, indent=2)}\n\nPlain-language request: \"{args.query}\""
        print("--- DRY RUN: no API call made ---\n")
        print("SYSTEM PROMPT:\n" + ASK_SYSTEM_PROMPT + "\n")
        print("USER MESSAGE:\n" + user_message + "\n")
        print("(Run without --dry-run, with ANTHROPIC_API_KEY set, to actually parse + generate.)")
        return

    try:
        parsed = parse_ask_query(library, args.query)
    except json.JSONDecodeError:
        print("Warning: parser output wasn't valid JSON.", file=sys.stderr)
        sys.exit(1)

    print(f"Interpreted your request as: {parsed.get('interpretation')}\n")

    problems = validate_ask_params(library, parsed)
    if problems:
        print("Couldn't fully resolve this request into a run:")
        for p in problems:
            print(f"  {p}")
        if parsed.get("clarification_needed"):
            print(f"  Why: {parsed['clarification_needed']}")
        print("\nBe more specific (name the customer/region/audience/role/platform explicitly), or use "
              "`localize` directly with flags. Run list-sources to see exactly what's available.")
        return

    print(f"Running: --source {parsed['source']} --audience {parsed['audience']} --region {parsed['region']} "
          f"--role {parsed['role']} --platform {parsed['platform']}\n")

    try:
        output = run_localize(library, parsed["source"], parsed["audience"], parsed["region"], parsed["role"], parsed["platform"])
    except json.JSONDecodeError:
        print("Warning: model output wasn't valid JSON.", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(output, indent=2))


def cmd_list_sources(args):
    print(json.dumps(load_library(), indent=2))


def build_localize_prompt(source, audience, region, role, platform):
    mode = "draft" if platform in DRAFT_PLATFORMS else "scaffold"
    system_prompt = DRAFT_SYSTEM_PROMPT if mode == "draft" else SCAFFOLD_SYSTEM_PROMPT
    platform_line = PLATFORM_SPEC.get(platform, f"a {platform} post")
    voice_examples_block = "\n".join(f'- "{ex}"' for ex in VOICE_EXAMPLES)
    user_message = (
        f"VOICE EXAMPLES (calibration only — match this register/rhythm, do not reuse their content):\n"
        f"{voice_examples_block}\n\n"
        f"SOURCE PROOF POINT (real, already-published):\n"
        f"{json.dumps(source, indent=2)}\n\n"
        f"Target audience segment: {audience}\n"
        f"Target region: {region} ({REGION_CONTEXT.get(region, 'unknown')})\n"
        f"Who this is for: {ROLE_FRAMING[role]}\n"
        f"Target platform: {platform} — {platform_line}\n"
    )
    return mode, system_prompt, user_message


def run_localize(library, source_key, audience, region, role, platform):
    """Core generation + fact-check, shared by the `localize` and `ask` commands. Returns the output dict."""
    source = library.get(source_key)
    if not source:
        raise ValueError(f"unknown source '{source_key}'. Run list-sources to see available proof points.")

    mode, system_prompt, user_message = build_localize_prompt(source, audience, region, role, platform)

    client = _get_anthropic_client()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text
    result = _parse_json_response(raw_text)  # raises json.JSONDecodeError on failure, handled by caller

    # Fact-check pass: any number in the output that doesn't trace back to the
    # source record OR the region context is flagged for the human reviewer as a
    # possible invention. This is a second, programmatic layer on top of the
    # prompt guardrail — not a replacement for human review, a supplement to it.
    # Region context (e.g. "region_1: mature market - well established customer
    # base") is real, given data too, not just the customer record — both count
    # as grounded facts.
    source_facts_text = " ".join(str(v) for v in source.values()) + " " + REGION_CONTEXT.get(region, "")
    allowed_numbers = _extract_numbers(source_facts_text)
    generated_text = " ".join(
        v if isinstance(v, str) else " ".join(v)
        for v in result.values()
        if isinstance(v, (str, list))
    )
    found_numbers = _extract_numbers(generated_text)
    flagged = sorted(found_numbers - allowed_numbers)

    return {
        "source": source_key,
        "audience": audience,
        "region": region,
        "role": role,
        "platform": platform,
        "mode": mode,
        **result,
        "fact_check": {
            "passed": len(flagged) == 0,
            "flagged_numbers": flagged,
            "note": "Numbers here don't trace back to the source record — check before shipping." if flagged else "All numbers trace back to the source record.",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def cmd_localize(args):
    library = load_library()
    source = library.get(args.source)
    if not source:
        print(f"Error: unknown --source '{args.source}'. Run list-sources to see available proof points.", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        mode, system_prompt, user_message = build_localize_prompt(source, args.audience, args.region, args.role, args.platform)
        print(f"--- DRY RUN ({mode} mode): no API call made ---\n")
        print("SYSTEM PROMPT:\n" + system_prompt + "\n")
        print("USER MESSAGE:\n" + user_message + "\n")
        print("(Run without --dry-run, with ANTHROPIC_API_KEY set, to actually generate.)")
        return

    try:
        output = run_localize(library, args.source, args.audience, args.region, args.role, args.platform)
    except json.JSONDecodeError:
        print("Warning: model output wasn't valid JSON.", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-sources", help="List available seeded real proof points").set_defaults(func=cmd_list_sources)

    p_localize = sub.add_parser("localize", help="Reframe one real proof point for a new audience/region/role/platform")
    p_localize.add_argument("--source", required=True, help="Key from list-sources, e.g. acme_co")
    p_localize.add_argument("--audience", required=True, choices=["smb", "enterprise"])
    p_localize.add_argument("--region", required=True, choices=list(REGION_CONTEXT.keys()))
    p_localize.add_argument("--role", required=True, choices=list(ROLE_FRAMING.keys()))
    p_localize.add_argument("--platform", required=True, choices=list(DRAFT_PLATFORMS | SCAFFOLD_PLATFORMS))
    p_localize.add_argument("--dry-run", action="store_true", help="Show the prompt without calling the API (free)")
    p_localize.set_defaults(func=cmd_localize)

    p_add = sub.add_parser("add-source", help="Extract a new real proof point from a URL or pasted text and add it to the library")
    input_group = p_add.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="Best-effort fetch; falls back to telling you to paste text if the page looks JS-rendered")
    input_group.add_argument("--text-file", help="Path to a text file with the story copied from the source page")
    input_group.add_argument("--text", help="Paste the story text directly as an argument")
    p_add.add_argument("--source-url", help="Optional: the real URL this came from, if you used --text/--text-file")
    p_add.add_argument("--dry-run", action="store_true", help="Show the extraction prompt without calling the API (free)")
    p_add.add_argument("--confirm", action="store_true", help="Actually save the extracted facts to the library (omit to preview only)")
    p_add.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing entry with the same key")
    p_add.set_defaults(func=cmd_add_source)

    p_ask = sub.add_parser("ask", help="Plain-language request instead of flags, e.g. 'LinkedIn post about our region_1 enterprise customer for region_4 marketing'")
    p_ask.add_argument("query", help="Your request in plain language")
    p_ask.add_argument("--dry-run", action="store_true", help="Show the parsing prompt without calling the API (free)")
    p_ask.set_defaults(func=cmd_ask)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
