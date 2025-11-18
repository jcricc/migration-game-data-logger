from flask import Flask, render_template, request, redirect
import os
import csv
import pandas as pd
from datetime import datetime

app = Flask(__name__)

LOG_FILE = "game_log.csv"

CATEGORIES = [
    "Civil Rights and Duties",
    "Historical Migration",
    "Local Migration",
    "Borders",
    "Migrant Experiences / Myths",
    "Statistics / Miscellaneous"
]

DIFFICULTIES = ["Easy", "Medium", "Hard"]
YEARS = ["Freshman", "Sophomore", "Junior", "Senior", "Grad", "Faculty"]

# =====================================================
# CREATE LOG FILE IF NEEDED
# =====================================================
def ensure_logfile():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "category", "difficulty", "correct", "year", "participant_id"])
ensure_logfile()

# =====================================================
# READ LOGFILE SAFELY
# =====================================================
def read_logfile(path):
    EXPECTED = ["timestamp", "category", "difficulty", "correct", "year", "participant_id"]

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=EXPECTED)

    df = pd.read_csv(path)

    # Fix columns if missing
    for col in EXPECTED:
        if col not in df.columns:
            df[col] = None

    # Clean participant_id
    df["participant_id"] = pd.to_numeric(df["participant_id"], errors="coerce").fillna(-1).astype(int)

    # Back-fill year within each participant
    df["year"] = (
        df["year"]
        .replace(["", "None", None], pd.NA)
        .groupby(df["participant_id"])
        .transform(lambda x: x.bfill().ffill())
    )

    return df

# =====================================================
# GET LAST PARTICIPANT ID
# =====================================================
def get_last_participant_id():
    df = read_logfile(LOG_FILE)
    if df.empty:
        return 0
    return int(df["participant_id"].max())

# =====================================================
# HOME REDIRECT
# =====================================================
@app.route("/")
def home():
    return redirect("/log")

# =====================================================
# LOGGING FORM
# =====================================================
@app.route("/log", methods=["GET", "POST"])
def log():
    if request.method == "GET":
        step = int(request.args.get("step", 1))
        step = min(max(step, 1), 4)

        last_pid = get_last_participant_id()
        active_pid = last_pid if last_pid > 0 else None

        return render_template(
            "log.html",
            categories=CATEGORIES,
            difficulties=DIFFICULTIES,
            years=YEARS,
            step=step,
            prev_category=None,
            prev_difficulty=None,
            prev_correct=None,
            prev_year=None,
            participant_id=active_pid,
            success=False,
            error=None
        )

    # POST REQUEST
    form = request.form
    step = int(form.get("step", 1))
    action = form.get("action", "next")

    prev_category = form.get("category")
    prev_difficulty = form.get("difficulty")
    prev_correct = form.get("correct")
    prev_year = form.get("year_new") or form.get("year") or None
    prev_pid = form.get("participant_id")

    # Identify current participant ID
    if prev_pid and prev_pid.isdigit():
        prev_pid = int(prev_pid)
    else:
        prev_pid = get_last_participant_id()
        if prev_pid == 0:
            prev_pid = 1

    # BACK BUTTON
    if action == "back":
        return render_template(
            "log.html",
            categories=CATEGORIES,
            difficulties=DIFFICULTIES,
            years=YEARS,
            step=max(1, step - 1),
            prev_category=prev_category,
            prev_difficulty=prev_difficulty,
            prev_correct=prev_correct,
            prev_year=prev_year,
            participant_id=prev_pid,
            success=False,
            error=None
        )

    # VALIDATION
    error = None
    if step == 1 and not (form.get("category_new") or prev_category):
        error = "Pick a category."
    if step == 2 and not (form.get("difficulty_new") or prev_difficulty):
        error = "Pick a difficulty."
    if step == 3 and (prev_correct not in ("0", "1")) and form.get("correct_new") not in ("0", "1"):
        error = "Select correct/incorrect."

    # Update if changed
    prev_category = form.get("category_new") or prev_category
    prev_difficulty = form.get("difficulty_new") or prev_difficulty
    prev_correct = form.get("correct_new") or prev_correct

    # HANDLE FINAL SUBMISSION
    if action == "submit" and not error:
        df = read_logfile(LOG_FILE)

        # Determine previous year
        if not df.empty and prev_pid in df["participant_id"].values:
            last_year = df[df["participant_id"] == prev_pid]["year"].dropna().iloc[-1]
        else:
            last_year = None

        # Autofill year if missing
        if prev_year is None:
            prev_year = last_year or "Unknown"

        # Decide participant switch based on year change
        if last_year is None or prev_year == last_year:
            pid_for_entry = prev_pid
        else:
            pid_for_entry = prev_pid + 1

        # Write to CSV
        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                prev_category,
                prev_difficulty,
                int(prev_correct),
                prev_year,
                pid_for_entry
            ])

        return render_template(
            "log.html",
            categories=CATEGORIES,
            difficulties=DIFFICULTIES,
            years=YEARS,
            step=1,
            prev_year=prev_year,
            participant_id=str(pid_for_entry),
            success=True,
            error=None
        )

    # HANDLE ERROR OR NEXT STEP
    return render_template(
        "log.html",
        categories=CATEGORIES,
        difficulties=DIFFICULTIES,
        years=YEARS,
        step=(step if error else min(step + 1, 4)),
        prev_category=prev_category,
        prev_difficulty=prev_difficulty,
        prev_correct=prev_correct,
        prev_year=prev_year,
        participant_id=prev_pid,
        success=False,
        error=error
    )

# =====================================================
# DASHBOARD
# =====================================================
@app.route("/dashboard")
def dashboard():
    df = read_logfile(LOG_FILE)

    if df.empty:
        return render_template(
            "dashboard.html",
            empty=True,
            grouped_entries=[],
            years=["All"] + YEARS,
            categories=["All"] + CATEGORIES,
            selected_year="All",
            selected_category="All",
            total=0,
            accuracy=0
        )

    selected_year = request.args.get("year", "All")
    selected_cat = request.args.get("category", "All")

    if selected_year != "All":
        df = df[df["year"] == selected_year]
    if selected_cat != "All":
        df = df[df["category"] == selected_cat]

    total = len(df)

    # SAFELY CALCULATE ACCURACY
    df["correct"] = pd.to_numeric(df["correct"], errors="coerce")
    valid_correct = df["correct"].dropna()
    accuracy = round(valid_correct.mean() * 100, 2) if not valid_correct.empty else 0

    # GROUP BY PARTICIPANT
    grouped_entries = []
    for pid, sub in df.groupby("participant_id"):
        grouped_entries.append({
            "participant_id": pid,
            "rows": sub.assign(
                correct_text=lambda x: x["correct"].map({1: "Correct", 0: "Incorrect"})
            )[
                ["timestamp", "year", "category", "difficulty", "correct_text"]
            ].to_dict(orient="records")
        })

    return render_template(
        "dashboard.html",
        empty=False,
        grouped_entries=grouped_entries,
        years=["All"] + YEARS,
        categories=["All"] + CATEGORIES,
        selected_year=selected_year,
        selected_category=selected_cat,
        total=total,
        accuracy=accuracy
    )

# =====================================================
# RUN FLASK APP
# =====================================================
if __name__ == "__main__":
    app.run(debug=True)
