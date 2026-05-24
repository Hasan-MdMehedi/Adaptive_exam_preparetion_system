import sys
import logging
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from app.config import VALID_SECTIONS, SECTION_TITLES
from app.database import init_db, get_section_stats, get_kb_snapshot, get_weak_topics
from app.prep_engine import start_prep_session, submit_answers, simulate_answers
from app.vector_store import index_pdf
from app.models import UserAnswer

logging.basicConfig(level=logging.WARNING)

# Page config
st.set_page_config(
    page_title="Adaptive Prep — SLATEFALL",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

#One-time init
@st.cache_resource(show_spinner="Starting up…")
def _init():
    init_db()
    try:
        index_pdf()
    except Exception:
        pass
    return True

_init()


def _default(key, val):
    if key not in st.session_state:
        st.session_state[key] = val

_default("page", "start")          # current page: start | exam | results | kb
_default("prep", None)             # StartPrepResponse object
_default("answers", {})            # {question_id: chosen_label}
_default("result", None)           # SubmitAnswersResponse object
_default("simulate_mode", False)   # True = AI answers, False = user answers

#Sidebar navigation 
st.sidebar.title("Adaptive Preparetion System")
st.sidebar.caption("SLATEFALL Dossier Study ")
st.sidebar.divider()

nav = st.sidebar.radio(
    "Go to",
    ["Start Prep", "Exam", "Results", "Knowledge Base"],
    index=["start", "exam", "results", "kb"].index(st.session_state.page)
    if st.session_state.page in ["start", "exam", "results", "kb"] else 0,
)

page_map = {
    "Start Prep": "start",
    "Exam": "exam",
    "Results": "results",
    "Knowledge Base": "kb",
}

st.session_state.page = page_map[nav]

# Status indicators in sidebar
if st.session_state.prep:
    st.sidebar.success(f"{len(st.session_state.prep.questions)} questions ready")
    answered = len(st.session_state.answers)
    total = len(st.session_state.prep.questions)
    st.sidebar.progress(
        answered / total if total else 0,
        text=f"Answered {answered}/{total}"
    )
if st.session_state.result:
    sr = st.session_state.result.session_result
    st.sidebar.info(f"Last score: {sr.score_pct:.1f}%")


#  PAGE 1 — Start Preparetion
if st.session_state.page == "start":
    st.title("Start a Preparetion Session")
    st.markdown(
        "Pick your sections → Questions are generated → Take the exam → View your score"
    )
    st.divider()

    #Section picker
    st.subheader("Step 1 — Which sections do you want to study?")
    selected = []
    col_a, col_b = st.columns(2)
    for i, sid in enumerate(VALID_SECTIONS):
        stats = get_section_stats([sid])
        col = col_a if i % 2 == 0 else col_b
        has_hist = stats["sessions"] > 0
        badge = (
            f" 🔄 Attended :{stats['sessions']} Times · avg {stats['avg_score_pct']:.0f}%"
            if has_hist else " 🆕 New"
        )
        if col.checkbox(f"{sid}. {SECTION_TITLES[sid]}{badge}", key=f"chk_{sid}"):
            selected.append(sid)

    st.divider()

    # ── Options ──────────────────────────────────────────────────
    st.subheader("Step 2 — Options")
    c1, c2 = st.columns(2)
    mcq_n = c1.number_input(
        "How many questions per section?",
        min_value=1, max_value=15, value=5
    )
    simulate = c2.toggle(
        "Demo mode (AI answers automatically)",
        value=False,
        help="Keep this OFF so you can answer the questions yourself"
    )

    if not simulate:
        st.success("**Interactive mode** — you will answer the questions yourself")
    else:
        st.warning("⚠️ **Demo mode** — AI will simulate answers. Turn OFF to take the exam yourself.")

    st.divider()

    # Generate button
    st.subheader("Step 3 — Generate questions")
    if not selected:
        st.info("Please tick at least one section above")
    else:
        st.markdown(
            f"Selected: **{selected}** — {len(selected)} section(s), "
            f"**{len(selected) * int(mcq_n)} questions** total"
        )

        if st.button(
            "Generate Questions & Start Exam",
            type="primary",
            use_container_width=True
        ):
            with st.spinner("Generating questions with Gemini AI…"):
                try:
                    prep = start_prep_session(selected, mcq_per_section=int(mcq_n))
                    st.session_state.prep = prep
                    st.session_state.answers = {}
                    st.session_state.result = None
                    st.session_state.simulate_mode = simulate

                    if simulate:
                        # Auto-simulate answers and jump straight to results
                        from app.prep_engine import simulate_answers as sim_ans
                        ans = sim_ans(prep.questions, wrong_pct=0.35)
                        res = submit_answers(prep.session_id, ans)
                        st.session_state.result = res
                        st.session_state.prep = None
                        st.session_state.page = "results"
                        st.rerun()
                    else:
                        # Go to exam page so user can answer
                        st.session_state.page = "exam"
                        st.rerun()

                except EnvironmentError as e:
                    st.error(f"API Key error: {e}")
                except Exception as e:
                    st.error(f"Unexpected error: {e}")


#  PAGE 2 — Exam (Interactive)
elif st.session_state.page == "exam":

    if st.session_state.prep is None:
        st.warning("No active session found.")
        if st.button("← Go back to Start Prep"):
            st.session_state.page = "start"
            st.rerun()
        st.stop()

    prep = st.session_state.prep
    questions = prep.questions
    total = len(questions)
    answered = len(st.session_state.answers)


    st.title("Exam")
    mode_badge = "🔄 Adaptive" if prep.is_returning else "Cold Start"
    st.markdown(
        f"**Sections:** {prep.sections} &nbsp;|&nbsp; "
        f"**Questions:** {total} &nbsp;|&nbsp; "
        f"**Mode:** {mode_badge}"
    )
    st.progress(
        answered / total if total else 0,
        text=f"{answered}/{total} answered"
    )
    st.divider()

    for i, q in enumerate(questions):
        already = st.session_state.answers.get(q.question_id)
        choices_text = {c.label: c.text for c in q.choices}
        labels = list(choices_text.keys())

        with st.container(border=True):
            # Question header with answered indicator
            status_icon = "" if already else f"Q{i + 1}"
            st.markdown(
                f"##### {status_icon} &nbsp; Section {q.section_id} — *{q.topic_tag}*"
            )
            st.markdown(f"**{q.question}**")

            # Radio button — pre-select if already answered
            default_idx = labels.index(already) if already in labels else None

            chosen = st.radio(
                "Choose your answer:",
                labels,
                format_func=lambda x: f"**{x}.** {choices_text[x]}",
                index=default_idx,
                key=f"radio_{q.question_id}",
                horizontal=False,
            )

            # Save answer immediately when user clicks
            if chosen and chosen != already:
                st.session_state.answers[q.question_id] = chosen
                st.rerun()

        st.write("")  # spacing between questions

    st.divider()

    # ── Submit section ────────────────────────────────────────────
    answered_now = len(st.session_state.answers)
    remaining = total - answered_now

    if remaining > 0:
        st.warning(
            f"You still have **{remaining} question(s)** unanswered. "
            f"Answer all questions to enable the Submit button."
        )
    else:
        st.success("All questions answered! Click Submit to see your results.")

        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button(
                "Submit & See Results",
                type="primary",
                use_container_width=True
            ):
                ua_list = [
                    UserAnswer(question_id=qid, chosen_label=label)
                    for qid, label in st.session_state.answers.items()
                ]
                with st.spinner("Scoring your answers…"):
                    try:
                        res = submit_answers(prep.session_id, ua_list)
                        st.session_state.result = res
                        st.session_state.prep = None
                        st.session_state.answers = {}
                        st.session_state.page = "results"
                        st.rerun()
                    except Exception as e:
                        st.error(f"Submit error: {e}")
        with col2:
            if st.button("🔄 Reset Answers", use_container_width=True):
                st.session_state.answers = {}
                st.rerun()


#  PAGE 3 — Results
elif st.session_state.page == "results":

    if st.session_state.result is None:
        st.warning("No results found. Please complete an exam first.")
        if st.button("← Go to Start Prep"):
            st.session_state.page = "start"
            st.rerun()
        st.stop()

    sr = st.session_state.result.session_result

    st.title("Results")

    # Score banner
    if sr.score_pct >= 70:
        st.success(
            f"## 🎉 {sr.correct_count}/{sr.total_questions} correct — {sr.score_pct:.1f}%"
        )
    elif sr.score_pct >= 40:
        st.warning(
            f"## {sr.correct_count}/{sr.total_questions} correct — {sr.score_pct:.1f}%"
        )
    else:
        st.error(
            f"## {sr.correct_count}/{sr.total_questions} correct — {sr.score_pct:.1f}%"
        )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Correct", sr.correct_count)
    c2.metric("Wrong", sr.wrong_count)
    c3.metric("Score", f"{sr.score_pct:.1f}%")
    c4.metric("Total", sr.total_questions)

    st.divider()

    #Per-question breakdown
    st.subheader("Question-by-question breakdown")

    wrong_list = [r for r in sr.results if not r.is_correct]
    correct_list = [r for r in sr.results if r.is_correct]

    if wrong_list:
        st.markdown(
            f"### ❌ Wrong answers ({len(wrong_list)}) — review these topics"
        )
        for r in wrong_list:
            with st.container(border=True):
                st.markdown(f"**Q: {r.question}**")
                for c in r.choices:
                    if c.label == r.correct_label:
                        st.markdown(f"✅ **{c.label}. {c.text}** ← correct answer")
                    elif c.label == r.user_label:
                        st.markdown(f"❌ {c.label}. {c.text} ← your answer")
                    else:
                        st.markdown(f"&nbsp;&nbsp;&nbsp;{c.label}. {c.text}")
                st.info(f"💡 **Explanation:** {r.explanation}")

    if correct_list:
        st.markdown(f"### ✅ Correct answers ({len(correct_list)})")
        for r in correct_list:
            with st.expander(f"✅ {r.question[:80]}…"):
                st.markdown(f"**Your answer:** {r.user_label} — correct!")
                st.markdown(f"*{r.explanation}*")

    st.divider()

    #  Action buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button(
            "🔁 Take exam again (Adaptive)",
            type="primary",
            use_container_width=True
        ):
            # Keep result in state but go back to start
            # Next run on same sections will be adaptive
            st.session_state.result = None
            st.session_state.page = "start"
            st.rerun()
    with col2:
        if st.button("🗄️ View Knowledge Base", use_container_width=True):
            st.session_state.page = "kb"
            st.rerun()
    with col3:
        if st.button("🏠 Start a new session", use_container_width=True):
            st.session_state.result = None
            st.session_state.prep = None
            st.session_state.answers = {}
            st.session_state.page = "start"
            st.rerun()


#  PAGE 4 — Knowledge Base
elif st.session_state.page == "kb":
    st.title("🗄️ Knowledge Base")
    st.markdown(
        "Full history of all your sessions, scores, and weak topics."
    )

    top_n = st.slider("How many sessions to display?", 3, 20, 5)
    snap = get_kb_snapshot(top_n=top_n)

    if not snap.records:
        st.info("No sessions recorded yet. Complete at least one exam first.")
        if st.button("← Go take an exam"):
            st.session_state.page = "start"
            st.rerun()
        st.stop()

    # Sessions table 
    st.subheader(f"Recent {len(snap.records)} sessions")
    import pandas as pd
    rows = [{
        "Session": r.session_id[:10] + "…",
        "Timestamp": r.timestamp[:19],
        "Sections": str(r.sections),
        "Score %": f"{r.score_pct:.1f}",
        "Correct ✅": r.correct_count,
        "Wrong ❌": r.wrong_count,
        "Total": r.total_questions,
        "Weak Topics": ", ".join(r.weak_topics[:2]) if r.weak_topics else "—",
    } for r in snap.records]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    #Section overview
    st.subheader("Progress by section")
    sec_rows = []
    for sid in VALID_SECTIONS:
        stats = get_section_stats([sid])
        sec_rows.append({
            "Section": f"§{sid}. {SECTION_TITLES[sid][:35]}…",
            "Sessions": stats["sessions"],
            "Avg Score %": stats["avg_score_pct"] or 0,
            "Status": "✅ Studied" if stats["sessions"] > 0 else "🆕 Not yet studied",
        })
    st.dataframe(pd.DataFrame(sec_rows), use_container_width=True, hide_index=True)

    #Weak topics chart
    st.subheader("Weak topics (where you make the most mistakes)")
    all_weak = get_weak_topics(VALID_SECTIONS, top_n=15)
    if all_weak:
        wdf = pd.DataFrame(all_weak)
        wdf = wdf.rename(columns={
            "topic_tag": "Topic",
            "error_rate": "Error Rate %",
            "wrong_count": "Wrong Count",
            "attempts": "Attempts",
        })
        st.bar_chart(wdf.set_index("Topic")["Error Rate %"])
        st.dataframe(
            wdf[["Topic", "Error Rate %", "Wrong Count", "Attempts"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No weak topic data yet — get some wrong answers first "
            "and they will appear here."
        )

    if st.button("← Start a new exam", type="primary"):
        st.session_state.page = "start"
        st.rerun()