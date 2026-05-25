"""
CLI — Adaptive Document Preparation System
Commands:
  index        — index the PDF
  prep         — run a prep session
  scenario-b   — run full Scenario B evaluation (saves outputs)
  snapshot     — show KB snapshot
  history      — show session history
"""

import json
import sys
import logging
import random
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(message)s")


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    click.echo(f"  ✓ Saved → {path}")


def _print_results(sr):
    click.echo(f"\n{'='*60}")
    click.echo(f"SCORE: {sr.correct_count}/{sr.total_questions} ({sr.score_pct:.1f}%)")
    click.echo(f"Session: {sr.session_id[:16]}...")
    click.echo(f"{'='*60}")
    for i, r in enumerate(sr.results, 1):
        icon = "✓" if r.is_correct else "✗"
        click.echo(f"  {icon} Q{i} [Sec {r.section_id}|{r.topic_tag}]: "
                   f"You={r.user_label} Correct={r.correct_label}")
    wrong = [r for r in sr.results if not r.is_correct]
    if wrong:
        click.echo(f"\n--- Explanations for {len(wrong)} wrong answer(s) ---")
        for r in wrong:
            click.echo(f"\n  Q: {r.question}")
            click.echo(f"  ✗ You chose {r.user_label}, correct is {r.correct_label}")
            click.echo(f"  → {r.explanation}")


@click.group()
def cli():
    """Adaptive Document Preparation System — SLATEFALL Dossier"""
    pass


@cli.command()
@click.option("--force", is_flag=True, help="Re-index even if data exists")
def index(force):
    """Index the PDF into the chunk store."""
    from app.database import init_db
    from app.vector_store import index_pdf
    click.echo("Initialising database...")
    init_db()
    click.echo("Indexing PDF...")
    try:
        count = index_pdf(force=force)
        click.echo(f"✓ Indexed {count} chunks successfully.")
    except Exception as e:
        click.echo(f"✗ Indexing failed: {e}")
        sys.exit(1)


@cli.command()
@click.argument("sections")
@click.option("--mcq", default=5, show_default=True, help="MCQs per section")
@click.option("--simulate/--interactive", default=True, help="Simulate or manual answers")
@click.option("--wrong-pct", default=0.35, show_default=True)
def prep(sections, mcq, simulate, wrong_pct):
    """Run a prep session. SECTIONS: comma-separated section IDs (e.g. '3,7')"""
    from app.database import init_db
    from app.prep_engine import start_prep_session, submit_answers, simulate_answers as sim
    from app.models import UserAnswer

    init_db()
    try:
        section_ids = [int(s.strip()) for s in sections.split(",") if s.strip()]
    except ValueError:
        click.echo("Error: sections must be comma-separated integers"); sys.exit(1)

    click.echo(f"\nStarting prep for sections: {section_ids}")
    try:
        prep_resp = start_prep_session(section_ids, mcq)
    except EnvironmentError as e:
        click.echo(f"✗ {e}"); sys.exit(1)

    mode = "ADAPTIVE" if prep_resp.is_returning else "COLD START"
    click.echo(f"Mode: {mode} | Questions: {len(prep_resp.questions)}")

    if simulate:
        answers = sim(prep_resp.questions, wrong_pct=wrong_pct)
        result = submit_answers(prep_resp.session_id, answers)
        _print_results(result.session_result)
    else:
        answers = []
        for i, q in enumerate(prep_resp.questions, 1):
            click.echo(f"\nQ{i} (Section {q.section_id}): {q.question}")
            for c in q.choices:
                click.echo(f"  {c.label}. {c.text}")
            ans = click.prompt("Answer (A/B/C/D)").strip().upper()
            while ans not in ("A","B","C","D"):
                ans = click.prompt("Enter A, B, C, or D").strip().upper()
            answers.append(UserAnswer(question_id=q.question_id, chosen_label=ans))
        result = submit_answers(prep_resp.session_id, answers)
        _print_results(result.session_result)


@cli.command("scenario-b")
@click.option("--mcq", default=5, show_default=True, help="MCQs per section")
@click.option("--wrong-pct", default=0.35, show_default=True)
@click.option("--output-dir", default="outputs", show_default=True)
def scenario_b(mcq, wrong_pct, output_dir):
    """
    Run full Scenario B evaluation (3 iterations) and save outputs.

    \b
    Iter 1: sections 5, 8
    Iter 2: sections 6, 8, 9
    Iter 3: section 8
    """
    from app.database import init_db, get_kb_snapshot
    from app.prep_engine import start_prep_session, submit_answers, simulate_answers as sim

    init_db()
    out = Path(output_dir)

    iterations = [
        ([5, 8],    out / "scenario_b_iter1"),
        ([6, 8, 9], out / "scenario_b_iter2"),
        ([8],       out / "scenario_b_iter3"),
    ]

    click.echo("\n" + "="*60)
    click.echo("Scenario B — Adaptive Prep Evaluation")
    click.echo("="*60)

    for i, (section_ids, iter_dir) in enumerate(iterations, 1):
        click.echo(f"\n--- Iteration {i} | Sections: {section_ids} ---")
        try:
            prep_resp = start_prep_session(section_ids, mcq)
        except EnvironmentError as e:
            click.echo(f"✗ LLM error: {e}"); sys.exit(1)

        mode = "ADAPTIVE" if prep_resp.is_returning else "COLD START"
        click.echo(f"  Mode: {mode} | Questions: {len(prep_resp.questions)}")

        answers = sim(prep_resp.questions, wrong_pct=wrong_pct)
        result = submit_answers(prep_resp.session_id, answers)
        sr = result.session_result

        click.echo(f"  Score: {sr.correct_count}/{sr.total_questions} ({sr.score_pct:.1f}%)")

        questions_payload = {
            "iteration": i,
            "session_id": prep_resp.session_id,
            "sections": section_ids,
            "is_adaptive": prep_resp.is_returning,
            "total_questions": len(prep_resp.questions),
            "questions": [q.model_dump() for q in prep_resp.questions],
            "session_result": sr.model_dump(),
        }
        snapshot = get_kb_snapshot(top_n=5)
        snapshot_payload = snapshot.model_dump()
        snapshot_payload["iteration"] = i

        _save_json(iter_dir / f"questions_iter{i}.json", questions_payload)
        _save_json(iter_dir / f"kb_snapshot_iter{i}.json", snapshot_payload)

    click.echo(f"\n{'='*60}")
    click.echo(f"✓ Scenario B complete! Outputs in: {output_dir}/")
    click.echo("="*60)


@cli.command()
@click.option("--top-n", default=5, show_default=True)
def snapshot(top_n):
    """Print the current KB snapshot."""
    from app.database import init_db, get_kb_snapshot
    init_db()
    snap = get_kb_snapshot(top_n=top_n)
    if not snap.records:
        click.echo("No sessions in Knowledge Base yet."); return
    click.echo(f"\nKB Snapshot — {snap.snapshot_taken_at}")
    click.echo(f"{'─'*90}")
    click.echo(f"{'Session':<14} {'Timestamp':<22} {'Sections':<14} {'Score%':>7} {'Q':>4} {'✓':>4} {'✗':>4} {'Weak Topics'}")
    click.echo(f"{'─'*90}")
    for r in snap.records:
        weak = ", ".join(r.weak_topics[:3]) if r.weak_topics else "—"
        click.echo(f"{r.session_id[:12]+'...':<14} {r.timestamp[:19]:<22} "
                   f"{str(r.sections):<14} {r.score_pct:>7.1f} {r.total_questions:>4} "
                   f"{r.correct_count:>4} {r.wrong_count:>4} {weak}")


@cli.command()
@click.argument("sections")
def history(sections):
    """Show session history for SECTIONS (comma-separated IDs)."""
    from app.database import init_db, get_sessions_for_sections
    import json as _json
    init_db()
    try:
        section_ids = [int(s.strip()) for s in sections.split(",") if s.strip()]
    except ValueError:
        click.echo("Error: sections must be comma-separated integers"); sys.exit(1)
    sessions = get_sessions_for_sections(section_ids)
    if not sessions:
        click.echo(f"No history for sections {section_ids}."); return
    click.echo(f"\nHistory for sections {section_ids} ({len(sessions)} sessions)")
    click.echo(f"{'─'*70}")
    for s in sessions:
        click.echo(f"  {s['session_id'][:12]}... | {s['timestamp'][:19]} | "
                   f"Secs={_json.loads(s['sections_json'])} | Score={s['score_pct']:.1f}%")


if __name__ == "__main__":
    cli()
