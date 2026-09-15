"""
Proof-Content Localization Engine, point-and-click front end.

Same logic as proof_localize.py, just a UI over it instead of a terminal.
Run with: streamlit run app.py (or double-click "Launch Tool.command")
"""

import json

import streamlit as st

from proof_localize import (
    DRAFT_PLATFORMS,
    SCAFFOLD_PLATFORMS,
    REGION_CONTEXT,
    ROLE_FRAMING,
    _fetch_url_text,
    _slugify,
    extract_proof_facts,
    load_library,
    parse_ask_query,
    run_localize,
    save_library,
    validate_ask_params,
)

st.set_page_config(page_title="Proof-Content Localizer", page_icon="📦", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []  # in-session only - not persisted, per the "storage is a later decision" note

st.title("📦 Proof-Content Localization Engine")
st.caption(
    "Reframes a real, already-published customer proof point for a new audience/region/role/platform. "
    "Never invents a fact. Every output is a draft for human review, never auto-published."
)

tab_localize, tab_ask, tab_sources, tab_add, tab_history = st.tabs(
    ["🎯 Localize", "💬 Ask (plain language)", "📚 Sources", "➕ Add Source", "🕒 Session history"]
)

# ---------------------------------------------------------------------------
# Tab: Localize (the 4 structured controls)
# ---------------------------------------------------------------------------
with tab_localize:
    library = load_library()
    if not library:
        st.warning("Proof library is empty. Add a source first in the 'Add Source' tab.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            source_key = st.selectbox(
                "Source proof point",
                options=list(library.keys()),
                format_func=lambda k: f"{library[k].get('customer_name')} — {library[k].get('region')}, {library[k].get('segment')}",
                key="loc_source",
            )
            audience = st.radio("Target audience", ["smb", "enterprise"], horizontal=True, key="loc_audience")
            role = st.selectbox(
                "Who this is for",
                options=list(ROLE_FRAMING.keys()),
                format_func=lambda r: {"marketing": "Marketing", "sales": "Sales", "other": "Other"}[r],
                key="loc_role",
            )
        with col2:
            region = st.selectbox("Target region", options=list(REGION_CONTEXT.keys()), key="loc_region")
            st.caption(f"Market context: {REGION_CONTEXT[region]}")
            platform = st.selectbox(
                "Target platform",
                options=list(DRAFT_PLATFORMS) + list(SCAFFOLD_PLATFORMS),
                key="loc_platform",
            )
            mode = "draft" if platform in DRAFT_PLATFORMS else "scaffold"
            st.caption(f"Mode: **{mode}** — " + (
                "near-finished copy, since this format is short/mechanical." if mode == "draft"
                else "outline only (angle + dot points), never finished prose — you write the final version."
            ))

        source = library[source_key]
        with st.expander("Source facts being used (real, unedited)"):
            st.json(source)

        if st.button("Generate", type="primary", key="loc_generate"):
            with st.spinner("Generating..."):
                try:
                    output = run_localize(library, source_key, audience, region, role, platform)
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    output = None

            if output:
                st.session_state.history.insert(0, {"type": "localize", "output": output})

                if output["fact_check"]["passed"]:
                    st.success("Fact-check passed — every number traces back to the real source data.")
                else:
                    st.error(f"Fact-check FAILED — unverified numbers: {output['fact_check']['flagged_numbers']}. Review carefully before using.")

                st.warning(output["status"])

                if mode == "draft":
                    st.text_area("Generated content", output.get("content", ""), height=150)
                    st.caption(f"Reviewer note: {output.get('notes_for_reviewer', '')}")
                else:
                    st.markdown(f"**Angle:** {output.get('angle', '')}")
                    st.markdown("**Dot points (write from these):**")
                    for dp in output.get("dot_points", []):
                        st.markdown(f"- {dp}")
                    st.markdown("**Prompting questions (for you, the drafter — not for the audience):**")
                    for q in output.get("prompting_questions", []):
                        st.markdown(f"- {q}")

                with st.expander("Full raw output (JSON)"):
                    st.json(output)

# ---------------------------------------------------------------------------
# Tab: Ask (plain language)
# ---------------------------------------------------------------------------
with tab_ask:
    st.markdown("Type a request in plain language instead of picking the 4 controls above.")
    query = st.text_input(
        "Your request",
        placeholder="e.g. give me a LinkedIn post about our region_1 enterprise customer for a region_4 marketing audience",
        key="ask_query",
    )
    if st.button("Ask", type="primary", key="ask_submit") and query:
        library = load_library()
        with st.spinner("Interpreting your request..."):
            try:
                parsed = parse_ask_query(library, query)
            except Exception as e:
                st.error(f"Couldn't parse the request: {e}")
                parsed = None

        if parsed:
            st.info(f"Interpreted as: {parsed.get('interpretation')}")
            problems = validate_ask_params(library, parsed)
            if problems:
                st.warning("Couldn't fully resolve this into a run:")
                for p in problems:
                    st.markdown(f"- {p}")
                if parsed.get("clarification_needed"):
                    st.markdown(f"**Why:** {parsed['clarification_needed']}")
                st.caption("Be more specific, or use the Localize tab directly.")
            else:
                st.caption(
                    f"Running: source={parsed['source']}, audience={parsed['audience']}, "
                    f"region={parsed['region']}, role={parsed['role']}, platform={parsed['platform']}"
                )
                with st.spinner("Generating..."):
                    try:
                        output = run_localize(library, parsed["source"], parsed["audience"], parsed["region"], parsed["role"], parsed["platform"])
                    except Exception as e:
                        st.error(f"Generation failed: {e}")
                        output = None

                if output:
                    st.session_state.history.insert(0, {"type": "ask", "query": query, "output": output})
                    if output["fact_check"]["passed"]:
                        st.success("Fact-check passed.")
                    else:
                        st.error(f"Fact-check FAILED — unverified numbers: {output['fact_check']['flagged_numbers']}")
                    st.warning(output["status"])
                    if output.get("mode") == "draft":
                        st.text_area("Generated content", output.get("content", ""), height=150)
                    else:
                        st.markdown(f"**Angle:** {output.get('angle', '')}")
                        for dp in output.get("dot_points", []):
                            st.markdown(f"- {dp}")
                        st.markdown("**Prompting questions (for the drafter):**")
                        for q in output.get("prompting_questions", []):
                            st.markdown(f"- {q}")
                    with st.expander("Full raw output (JSON)"):
                        st.json(output)

# ---------------------------------------------------------------------------
# Tab: Sources
# ---------------------------------------------------------------------------
with tab_sources:
    library = load_library()
    st.markdown(f"**{len(library)} source(s) in the library** (`proof_library.json`)")
    for key, entry in library.items():
        with st.expander(f"{entry.get('customer_name')} — {entry.get('region')}, {entry.get('segment')} (`{key}`)"):
            st.json(entry)

# ---------------------------------------------------------------------------
# Tab: Add Source
# ---------------------------------------------------------------------------
with tab_add:
    st.markdown(
        "Add a real, already-published source — a customer story, a blog article, or an industry "
        "update (e.g. your own company's blog, a press release, anywhere real). Claude extracts only what's "
        "explicitly stated — nothing is saved until you review and confirm."
    )
    st.info(
        "📹 **Some customer stories are YouTube videos, not text** — this tool can only read text, "
        "it can't watch or listen to a video. If your source is a video: open it on YouTube, click "
        "**\"⋯\" → \"Show transcript\"** below the video, copy the transcript text, and paste it in below. "
        "That gives a far richer extraction than the video page's title/caption alone."
    )

    input_method = st.radio("Input method", ["Paste text", "Fetch from URL"], horizontal=True, key="add_method")

    raw_text = None
    source_url = None

    if input_method == "Paste text":
        raw_text = st.text_area("Paste story text here", height=150, key="add_text")
        source_url = st.text_input(
            "Source URL (optional, if you know it)", key="add_text_source_url",
            placeholder="https://example.com/..."
        ) or "(pasted text, no URL given)"
        fetch_ready = bool(raw_text and raw_text.strip())
    else:
        url = st.text_input("URL to fetch", key="add_url", placeholder="https://example.com/customer-stories/...")
        st.caption(
            "Best-effort fetch — many pages are JS-rendered and this won't see real content. "
            "If it warns the page looks empty, switch to 'Paste text' instead."
        )
        raw_text = None  # fetched on click, not here
        source_url = url
        fetch_ready = bool(url and url.strip())

    if "extracted" not in st.session_state:
        st.session_state.extracted = None

    button_label = "Preview extraction" if input_method == "Paste text" else "Fetch & preview extraction"
    if st.button(button_label, key="add_preview") and fetch_ready:
        if input_method == "Fetch from URL":
            with st.spinner("Fetching URL..."):
                try:
                    raw_text = _fetch_url_text(source_url.strip())
                except Exception as e:
                    st.error(f"Error fetching URL: {e}\nTry 'Paste text' instead.")
                    raw_text = None
            if raw_text is not None and len(raw_text) < 300:
                st.warning(
                    f"Fetched page returned very little visible text ({len(raw_text)} chars) — it may be "
                    "JS-rendered and this simple fetch can't see the real content. Switch to 'Paste text' instead."
                )
                raw_text = None

        if raw_text:
            with st.spinner("Extracting facts..."):
                try:
                    extracted, key = extract_proof_facts(raw_text.strip())
                    extracted["source_url"] = source_url.strip() if source_url else "(unknown)"
                    st.session_state.extracted = (extracted, key)
                except Exception as e:
                    st.error(f"Extraction failed: {e}")
                    st.session_state.extracted = None

    if st.session_state.extracted:
        extracted, suggested_key = st.session_state.extracted

        st.markdown("**Review and correct anything before saving — this is what ships as the source of truth.**")
        if not extracted.get("customer_name") and not extracted.get("topic"):
            st.warning(
                "No customer name or topic was found, so the entry can't be uniquely keyed automatically. "
                "This usually means the pasted text was a fragment rather than the full article/transcript. "
                "Fill in the fields below manually, or paste the fuller text and re-extract."
            )

        col1, col2 = st.columns(2)
        with col1:
            customer_name = st.text_input("Customer name (blank if not a customer testimonial)", value=extracted.get("customer_name") or "", key="ed_name")
            relationship = st.text_input("Relationship (e.g. how long they've been a customer)", value=extracted.get("relationship") or "", key="ed_rel")
            region = st.text_input("Location (free text, doesn't have to match a fixed region list)", value=extracted.get("region") or "", key="ed_region")
            topic = st.text_input("Topic (one-sentence gist, esp. for non-testimonial content)", value=extracted.get("topic") or "", key="ed_topic")
        with col2:
            segment_options = ["", "smb", "enterprise", "mixed"]
            segment_value = extracted.get("segment") or ""
            segment = st.selectbox(
                "Segment", options=segment_options,
                index=segment_options.index(segment_value) if segment_value in segment_options else 0,
                key="ed_segment",
            )
            account_size = st.text_input("Account size (number, blank if unstated)", value=str(extracted.get("account_size") or ""), key="ed_account_size")
            video_length_sec = st.text_input("Video length in seconds (blank if not a video)", value=str(extracted.get("video_length_sec") or ""), key="ed_video_len")

        quotes_text = st.text_area(
            "Quotes (one per line — edit, add, or remove any)",
            value="\n".join(extracted.get("quotes") or ([extracted["quote"]] if extracted.get("quote") else [])),
            height=100, key="ed_quotes",
        )
        key_facts_text = st.text_area(
            "Key facts / results (one per line)",
            value="\n".join(extracted.get("key_facts") or ([extracted["metric"]] if extracted.get("metric") else [])),
            height=100, key="ed_facts",
        )
        source_url_display = st.text_input("Source URL", value=extracted.get("source_url") or "", key="ed_url")

        suggested_key = _slugify(customer_name or topic or suggested_key)
        key = st.text_input("Save as (key) — edit if needed to keep it unique", value=suggested_key, key="add_key")

        library = load_library()
        already_exists = key in library
        if already_exists:
            st.warning(f"'{key}' already exists in the library.")
        overwrite = st.checkbox("Overwrite existing entry", key="add_overwrite") if already_exists else False

        if st.button("Confirm & Save to library", type="primary", key="add_confirm"):
            if not key.strip():
                st.error("Key can't be empty.")
            elif already_exists and not overwrite:
                st.error("Entry exists — check 'Overwrite existing entry' to replace it.")
            else:
                final_entry = {
                    "customer_name": customer_name.strip() or None,
                    "relationship": relationship.strip() or None,
                    "region": region.strip() or None,
                    "segment": segment or None,
                    "account_size": int(account_size) if account_size.strip().isdigit() else None,
                    "topic": topic.strip() or None,
                    "quotes": [q.strip() for q in quotes_text.splitlines() if q.strip()],
                    "key_facts": [f.strip() for f in key_facts_text.splitlines() if f.strip()],
                    "video_length_sec": int(video_length_sec) if video_length_sec.strip().isdigit() else None,
                    "source_url": source_url_display.strip() or None,
                }
                library[key.strip()] = final_entry
                save_library(library)
                st.success(f"Saved as '{key.strip()}' — permanently, to proof_library.json. Available in the Localize tab now.")
                st.session_state.extracted = None

# ---------------------------------------------------------------------------
# Tab: Session history (in-memory only, resets on restart - a real store is a later decision)
# ---------------------------------------------------------------------------
with tab_history:
    st.caption(
        "In-session only — resets when this app restarts. A real shared/persistent store is a "
        "deliberate later decision, once there's a known destination (see build log)."
    )
    if not st.session_state.history:
        st.info("Nothing generated yet this session.")
    else:
        for i, item in enumerate(st.session_state.history):
            output = item["output"]
            label = f"{item['type']} — {output.get('source')} / {output.get('audience')} / {output.get('region')} / {output.get('role')} / {output.get('platform')}"
            with st.expander(label):
                st.json(output)
