"""
run_forecasts.py - ask Claude for probability forecasts on each question.

Usage examples
--------------
  # Preview the prompt for one question without calling the API
  python run_forecasts.py --ids 100 --dry-run

  # Run the urgent questions first (5 runs each, no context)
  python run_forecasts.py --ids 100,18,82,17,76,54,24,44

  # Run everything, both conditions (needs contexts.csv for the second one)
  python run_forecasts.py --condition both

  # Make a blank contexts.csv to fill in with neutral news briefs
  python run_forecasts.py --make-context-template

Setup
-----
  pip install anthropic
  export ANTHROPIC_API_KEY="sk-ant-..."   # never put the key in this file

Results are appended to forecasts.csv. Re-running skips any
(question, model, condition, run) that is already recorded, so you can
stop and restart safely. Commit forecasts.csv to GitHub right after each
batch: that timestamp proves the forecasts came before the outcomes.
"""

import argparse
import csv
import os
import re
import sys
import time
from datetime import date, datetime, timezone

DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = (
    "You are a careful, well-calibrated forecaster. You will be given a "
    "yes/no question about a future event, its resolution criteria, and "
    "today's date. Reason briefly about base rates and the key factors, "
    "then give your probability that the question resolves YES.\n\n"
    "End your answer with a final line in exactly this format:\n"
    "PROBABILITY: <integer from 0 to 100>"
)

FIELDS = [
    "question_id", "model", "condition", "run", "probability",
    "forecast_date", "timestamp_utc", "parse_ok", "response",
]


def build_prompt(q, today, brief=None):
    parts = [f"Today's date is {today}.", ""]
    if brief:
        parts += ["Background (recent news, for context):", brief.strip(), ""]
    parts += [
        f"Question: {q['question']}",
        f"Resolution criteria: {q['resolution_criteria']}",
        f"Resolution date: {q['resolution_date']}",
        "",
        "What is the probability that this question resolves YES?",
    ]
    return "\n".join(parts)


def parse_probability(text):
    m = re.findall(r"PROBABILITY:\s*(\d{1,3}(?:\.\d+)?)\s*%?", text, re.IGNORECASE)
    if not m:
        return None
    p = float(m[-1])
    return p if 0 <= p <= 100 else None


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_done(path):
    done = set()
    if os.path.exists(path):
        for r in load_csv(path):
            if r["parse_ok"] == "True":
                done.add((r["question_id"], r["model"], r["condition"], r["run"]))
    return done


def append_row(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def ask(client, model, prompt, max_tokens):
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--questions", default="questions_cleaned.csv")
    ap.add_argument("--contexts", default="contexts.csv",
                    help="CSV with columns id,brief (used for the with_context condition)")
    ap.add_argument("--out", default="forecasts.csv")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--runs", type=int, default=5, help="repeated forecasts per question")
    ap.add_argument("--condition", choices=["no_context", "with_context", "both"], default="no_context")
    ap.add_argument("--ids", help="comma-separated question ids to run (default: all)")
    ap.add_argument("--today", default=date.today().isoformat(), help="date shown to the model")
    ap.add_argument("--max-tokens", type=int, default=1000)
    ap.add_argument("--dry-run", action="store_true", help="print prompts, don't call the API")
    ap.add_argument("--make-context-template", action="store_true")
    args = ap.parse_args()

    questions = load_csv(args.questions)

    if args.make_context_template:
        if os.path.exists(args.contexts):
            sys.exit(f"{args.contexts} already exists; not overwriting.")
        with open(args.contexts, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "question", "brief"])
            for q in questions:
                w.writerow([q["id"], q["question"], ""])
        print(f"Wrote {args.contexts}. Fill in the 'brief' column with 2-3 neutral, factual sentences per question.")
        return

    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",")}
        questions = [q for q in questions if q["id"] in wanted]
        missing = wanted - {q["id"] for q in questions}
        if missing:
            sys.exit(f"Unknown question ids: {sorted(missing)}")

    conditions = ["no_context", "with_context"] if args.condition == "both" else [args.condition]

    briefs = {}
    if "with_context" in conditions:
        if not os.path.exists(args.contexts):
            sys.exit(f"{args.contexts} not found. Run with --make-context-template first.")
        briefs = {r["id"]: r["brief"] for r in load_csv(args.contexts) if r.get("brief", "").strip()}
        lacking = [q["id"] for q in questions if q["id"] not in briefs]
        if lacking:
            print(f"Note: no brief for ids {lacking}; skipping them in with_context.")

    client = None
    if not args.dry_run:
        try:
            import anthropic
        except ImportError:
            sys.exit("Install the SDK first: pip install anthropic")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("Set ANTHROPIC_API_KEY in your environment first.")
        client = anthropic.Anthropic(max_retries=5)

    done = load_done(args.out)
    total = ok = skipped = 0

    for q in questions:
        for cond in conditions:
            brief = briefs.get(q["id"]) if cond == "with_context" else None
            if cond == "with_context" and not brief:
                continue
            prompt = build_prompt(q, args.today, brief)

            if args.dry_run:
                print(f"--- Q{q['id']} [{cond}] ---\nSYSTEM:\n{SYSTEM_PROMPT}\n\nUSER:\n{prompt}\n")
                continue

            for run in range(1, args.runs + 1):
                key = (q["id"], args.model, cond, str(run))
                if key in done:
                    skipped += 1
                    continue
                total += 1
                text, prob = "", None
                for attempt in range(2):  # one retry if the probability can't be parsed
                    try:
                        text = ask(client, args.model, prompt, args.max_tokens)
                    except Exception as e:
                        text = f"API ERROR: {e}"
                        time.sleep(5)
                        continue
                    prob = parse_probability(text)
                    if prob is not None:
                        break
                append_row(args.out, {
                    "question_id": q["id"], "model": args.model, "condition": cond,
                    "run": run, "probability": "" if prob is None else prob,
                    "forecast_date": args.today,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "parse_ok": prob is not None, "response": text,
                })
                ok += prob is not None
                print(f"Q{q['id']} [{cond}] run {run}: {prob if prob is not None else 'PARSE FAILED'}")

    if not args.dry_run:
        print(f"\nDone. {ok}/{total} new forecasts parsed; {skipped} already recorded. Results in {args.out}.")
        if ok < total:
            print("Rows with parse_ok=False will be retried next time you run the same command.")


if __name__ == "__main__":
    main()
