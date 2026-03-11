import base64
import json
from datetime import date, datetime, timedelta
from textwrap import dedent

import requests
import streamlit as st

REPO_NAME = "gk_revision_data"
DATA_PATH = "maths_data.json"
BRANCH = "main"


def today_str():
    return date.today().strftime("%d-%m-%y")


def parse_date(value):
    if not value:
        return None
    for fmt in ("%d-%m-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def format_date(value):
    if not value:
        return "-"
    if isinstance(value, date):
        return value.strftime("%d-%m-%y")
    return str(value)


def get_github_config():
    token = st.secrets.get("GITHUB_TOKEN")
    owner = st.secrets.get("GITHUB_OWNER", "harshkumar1663")
    return owner, token


def github_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def empty_data():
    return {"chapters": []}


def ensure_chapter_fields(chapter):
    changed = False
    nullable_fields = {"next_practice_date", "first_lecture_date"}
    defaults = {
        "chapter_name": "",
        "total_lectures_watched": 0,
        "practice_sessions": [],
        "status": "learning",
        "next_practice_date": None,
        "current_sheet_index": 0,
        "lecture_dates": [],
        "first_lecture_date": None,
        "maintenance_stage": 0,
        "subject": "Maths",
        "sheet_total": 0,
        "questions_completed_total": 0,
    }
    for key, value in defaults.items():
        if key not in chapter:
            chapter[key] = value
            changed = True
        elif chapter[key] is None and key not in nullable_fields:
            chapter[key] = value
            changed = True
    if not chapter.get("subject"):
        chapter["subject"] = "Maths"
        changed = True
    if not isinstance(chapter.get("practice_sessions"), list):
        chapter["practice_sessions"] = []
        changed = True
    return changed


def load_data():
    owner, token = get_github_config()
    if not token:
        st.error("Missing GITHUB_TOKEN in Streamlit secrets.")
        st.stop()
    url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}?ref={BRANCH}"
    response = requests.get(url, headers=github_headers(token), timeout=20)
    if response.status_code == 200:
        payload = response.json()
        content = base64.b64decode(payload["content"]).decode("utf-8")
        st.session_state["github_sha"] = payload.get("sha")
        return json.loads(content)
    if response.status_code == 404:
        data = empty_data()
        save_data(data, creating=True)
        return data
    st.error(f"GitHub API error: {response.status_code}")
    st.stop()


def save_data(data, creating=False):
    owner, token = get_github_config()
    url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}"
    content = json.dumps(data, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": "Update maths_data.json",
        "content": encoded,
        "branch": BRANCH,
    }
    if not creating:
        payload["sha"] = st.session_state.get("github_sha")
    response = requests.put(url, headers=github_headers(token), json=payload, timeout=20)
    if response.status_code == 409 and not creating:
        latest_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}?ref={BRANCH}"
        latest = requests.get(latest_url, headers=github_headers(token), timeout=20)
        if latest.status_code == 200:
            st.session_state["github_sha"] = latest.json().get("sha")
            payload["sha"] = st.session_state.get("github_sha")
            response = requests.put(url, headers=github_headers(token), json=payload, timeout=20)
    if response.status_code in (200, 201):
        st.session_state["github_sha"] = response.json().get("content", {}).get("sha")
        # Keep in-memory state aligned with the latest successful save.
        st.session_state["data"] = data
        return
    st.error(f"Failed to save: {response.status_code}")
    st.stop()


def get_chapter(data, name):
    for chapter in data["chapters"]:
        if chapter["chapter_name"] == name:
            return chapter
    return None


def ensure_chapter(data, name):
    existing = get_chapter(data, name)
    if existing:
        ensure_chapter_fields(existing)
        return existing
    chapter = {
        "chapter_name": name,
        "total_lectures_watched": 0,
        "practice_sessions": [],
        "status": "learning",
        "next_practice_date": None,
        "current_sheet_index": 0,
        "lecture_dates": [],
        "first_lecture_date": None,
        "maintenance_stage": 0,
        "subject": "Maths",
        "sheet_total": 0,
        "questions_completed_total": 0,
    }
    data["chapters"].append(chapter)
    return chapter


def record_lecture(chapter, lectures):
    if lectures <= 0:
        return False
    chapter["total_lectures_watched"] += lectures
    today = today_str()
    if today not in chapter.get("lecture_dates", []):
        chapter.setdefault("lecture_dates", []).append(today)
    if not chapter.get("first_lecture_date"):
        chapter["first_lecture_date"] = today
    return True


def adjust_next_practice_for_lecture(chapter, lecture_logged):
    if not lecture_logged:
        return
    if chapter.get("status") not in ("learning", "active"):
        return
    next_date = parse_date(chapter.get("next_practice_date"))
    if not next_date:
        return
    today = date.today()
    days_until = (next_date - today).days
    if days_until <= 3:
        return
    shift_days = 2 if days_until >= 5 else 1
    tightened = next_date - timedelta(days=shift_days)
    if tightened < today:
        tightened = today
    chapter["next_practice_date"] = tightened.strftime("%d-%m-%y")


def has_consecutive_lecture_days(chapter):
    dates = [parse_date(d) for d in chapter.get("lecture_dates", [])]
    dates = sorted([d for d in dates if d])
    if len(dates) < 2:
        return False
    for i in range(1, len(dates)):
        if dates[i] - dates[i - 1] == timedelta(days=1):
            return True
    return False


def practice_unlocks(chapter):
    if chapter["practice_sessions"]:
        return True
    if has_consecutive_lecture_days(chapter):
        return True
    if chapter["total_lectures_watched"] >= 3:
        return True
    first_date = parse_date(chapter.get("first_lecture_date"))
    if first_date and (date.today() - first_date).days >= 5:
        return True
    return False


def spacing_days(accuracy):
    if accuracy > 80:
        return 9
    if accuracy >= 60:
        return 4
    return 2


def sheet_progress(chapter):
    sheet_total = int(chapter.get("sheet_total", 0) or 0)
    completed = int(chapter.get("questions_completed_total", 0) or 0)
    if sheet_total <= 0:
        return 0.0
    return min(completed / sheet_total, 1.0)


def sheet_completed(chapter):
    sheet_total = int(chapter.get("sheet_total", 0) or 0)
    completed = int(chapter.get("questions_completed_total", 0) or 0)
    return sheet_total > 0 and completed >= sheet_total


def update_status_after_session(chapter, accuracy):
    sessions = chapter["practice_sessions"]
    if chapter["status"] == "maintenance" and accuracy < 65:
        chapter["status"] = "active"
        chapter["maintenance_stage"] = 0
        return
    if len(sessions) >= 3 and accuracy >= 80 and sheet_progress(chapter) >= 0.7:
        chapter["status"] = "maintenance"
        chapter["maintenance_stage"] = 0
        return
    if chapter["status"] == "learning":
        chapter["status"] = "active"


def set_next_practice_date(chapter, accuracy):
    if chapter["status"] == "maintenance" and sheet_completed(chapter):
        stage = chapter.get("maintenance_stage", 0)
        if stage == 0:
            next_date = date.today() + timedelta(days=15)
            chapter["maintenance_stage"] = 1
        elif stage == 1:
            next_date = date.today() + timedelta(days=30)
            chapter["maintenance_stage"] = 2
        else:
            next_date = None
        chapter["next_practice_date"] = next_date.strftime("%d-%m-%y") if next_date else None
        return
    next_days = spacing_days(accuracy)
    next_date = date.today() + timedelta(days=next_days)
    chapter["next_practice_date"] = next_date.strftime("%d-%m-%y")


def sort_chapters(data):
    data["chapters"] = sorted(data["chapters"], key=lambda c: c["chapter_name"].lower())


def status_color(status):
    return {
        "learning": "#2f6feb",
        "active": "#f08800",
        "maintenance": "#2ea043",
    }.get(status, "#6e7781")


def render_status_badge(status):
    safe_status = str(status).strip().lower() or "learning"
    return f"<span class='status-pill status-{safe_status}'>{safe_status.title()}</span>"


def render_dashboard(data):
    st.subheader("Chapter Overview")
    today = date.today()

    total_chapters = len(data["chapters"])
    due_today_count = 0
    overdue_count = 0
    accuracy_values = []

    for chapter in data["chapters"]:
        if chapter["practice_sessions"]:
            accuracy_values.append(chapter["practice_sessions"][-1]["accuracy"])
        next_date = parse_date(chapter.get("next_practice_date"))
        if next_date:
            if next_date == today:
                due_today_count += 1
            elif next_date < today:
                overdue_count += 1
        elif practice_unlocks(chapter):
            due_today_count += 1

    avg_accuracy = round(sum(accuracy_values) / len(accuracy_values), 2) if accuracy_values else 0

    metric_cols = st.columns(4)
    metric_cols[0].markdown(
        f"<div class='metric-card'><div class='metric-label'>Total Chapters</div><div class='metric-value'>{total_chapters}</div></div>",
        unsafe_allow_html=True,
    )
    metric_cols[1].markdown(
        f"<div class='metric-card'><div class='metric-label'>Due Today</div><div class='metric-value'>{due_today_count}</div></div>",
        unsafe_allow_html=True,
    )
    metric_cols[2].markdown(
        f"<div class='metric-card'><div class='metric-label'>Overdue</div><div class='metric-value'>{overdue_count}</div></div>",
        unsafe_allow_html=True,
    )
    metric_cols[3].markdown(
        f"<div class='metric-card'><div class='metric-label'>Avg Accuracy</div><div class='metric-value'>{avg_accuracy}%</div></div>",
        unsafe_allow_html=True,
    )

    for chapter in data["chapters"]:
        last_accuracy = chapter["practice_sessions"][-1]["accuracy"] if chapter["practice_sessions"] else None
        next_date = parse_date(chapter.get("next_practice_date"))
        due = False
        overdue = False
        if next_date:
            due = next_date == today
            overdue = next_date < today
        elif practice_unlocks(chapter):
            due = True
        status_badge = render_status_badge(chapter["status"])
        due_badge = ""
        if overdue:
            due_badge = "<span class='due-pill due-overdue'>Overdue</span>"
        elif due:
            due_badge = "<span class='due-pill due-today'>Due Today</span>"

        sessions_done = len(chapter.get("practice_sessions", []))
        sheet_pct = round(sheet_progress(chapter) * 100)
        progress_pct = min(round((sessions_done / 4) * 100), 100)

        with st.container():
            st.markdown(
                dedent(
                    f"""
                    <div class='chapter-card chapter-card-compact'>
                        <div class='chapter-card-top'>
                            <div class='chapter-title'>{chapter['chapter_name']}</div>
                            <div class='chapter-pills'>{status_badge}{due_badge}</div>
                        </div>

                        <div class='chapter-grid'>
                            <div class='stat-chip'>
                                <span class='stat-label'>Last Accuracy</span>
                                <span class='stat-value'>{last_accuracy if last_accuracy is not None else '-'}%</span>
                            </div>
                            <div class='stat-chip'>
                                <span class='stat-label'>Next Practice</span>
                                <span class='stat-value'>{format_date(next_date)}</span>
                            </div>
                            <div class='stat-chip'>
                                <span class='stat-label'>Sessions Done</span>
                                <span class='stat-value'>{sessions_done}</span>
                            </div>
                            <div class='stat-chip'>
                                <span class='stat-label'>Sheet Progress</span>
                                <span class='stat-value'>{sheet_pct}%</span>
                            </div>
                        </div>

                        <div class='progress-row'>
                            <span class='progress-label'>Cycle Progress</span>
                            <span class='progress-value'>{progress_pct}%</span>
                        </div>
                        <div class='progress-track'>
                            <div class='progress-fill' style='width: {progress_pct}%;'></div>
                        </div>
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )


def render_maintenance_view(data):
    st.subheader("Maintenance Cycle")
    for chapter in data["chapters"]:
        if chapter["status"] != "maintenance":
            continue
        next_date = parse_date(chapter.get("next_practice_date"))
        st.markdown(
            f"""
            <div class='chapter-card'>
                <div style='font-weight:700;font-size:17px;'>{chapter['chapter_name']}</div>
                <div style='margin-top:8px;font-size:14px;color:#475569;'>
                    Next maintenance: <strong style='color:#0f172a;'>{format_date(next_date)}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_practice_history(chapter):
    st.markdown("### Practice History")
    sessions = chapter.get("practice_sessions", [])
    if not sessions:
        st.caption("No practice sessions logged yet for this chapter.")
        return

    for session in reversed(sessions):
        title = (
            f"{session.get('date', '-')} | "
            f"Accuracy: {session.get('accuracy', '-')}% | "
            f"Attempted: {session.get('questions_attempted', '-')}"
        )
        with st.expander(title):
            detail_cols = st.columns(3)
            detail_cols[0].write(f"Correct: {session.get('correct', '-')}")
            detail_cols[1].write(f"Attempted: {session.get('questions_attempted', '-')}")
            detail_cols[2].write(f"Accuracy: {session.get('accuracy', '-')}%")

            st.markdown("**Notes**")
            st.write(session.get("notes") or "No notes added.")


def render_chapter_table(data):
    st.subheader("Chapter Table")
    if "show_add_chapter" not in st.session_state:
        st.session_state["show_add_chapter"] = False
    if "edit_chapter" not in st.session_state:
        st.session_state["edit_chapter"] = None
    if "delete_chapter" not in st.session_state:
        st.session_state["delete_chapter"] = None

    if st.button("➕ Add Chapter"):
        st.session_state["show_add_chapter"] = True

    if st.session_state.get("show_add_chapter"):
        with st.form("add_chapter_form", clear_on_submit=True):
            new_name = st.text_input("Chapter name")
            new_subject = st.selectbox("Subject", ["Maths", "Reasoning"])
            new_sheet_total = st.number_input("Sheet size", min_value=1, step=1)
            new_lectures = st.number_input("Lectures watched", min_value=0, max_value=10, step=1)
            submitted = st.form_submit_button("Add")
            if submitted:
                if not new_name.strip():
                    st.error("Chapter name is required.")
                elif get_chapter(data, new_name.strip()):
                    st.error("Chapter already exists.")
                else:
                    chapter = ensure_chapter(data, new_name.strip())
                    chapter["subject"] = new_subject
                    chapter["sheet_total"] = int(new_sheet_total)
                    chapter["questions_completed_total"] = 0
                    chapter["total_lectures_watched"] = int(new_lectures)
                    sort_chapters(data)
                    save_data(data)
                    st.success("Chapter added.")
                    st.session_state["show_add_chapter"] = False
                    st.rerun()

    selected_subject = st.radio(
        "Show subject",
        ["MATHS", "REASONING"],
        horizontal=True,
        key="chapter_table_subject_filter",
    )
    subject_filter = selected_subject.title()
    filtered_chapters = [
        chapter for chapter in data["chapters"] if chapter.get("subject", "Maths") == subject_filter
    ]

    headers = [
        "Chapter",
        "Status",
        "Lectures",
        "Sheet",
        "Solved",
        "Remaining",
        "Progress %",
        "Last Accuracy",
        "Sessions",
        "Next",
        "Actions",
    ]
    header_cols = st.columns([2.2, 1.4, 0.95, 0.85, 0.85, 0.95, 1.05, 1.0, 0.85, 1.1, 1.4])
    for col, label in zip(header_cols, headers):
        col.markdown(f"<div class='table-header-cell'>{label}</div>", unsafe_allow_html=True)

    if not filtered_chapters:
        st.info(f"No chapters found for {selected_subject}.")
        return

    for chapter in filtered_chapters:
        chapter_name = chapter["chapter_name"]
        last_accuracy = chapter["practice_sessions"][-1]["accuracy"] if chapter["practice_sessions"] else None
        next_date = parse_date(chapter.get("next_practice_date"))
        sheet_total = int(chapter.get("sheet_total", 0) or 0)
        completed = int(chapter.get("questions_completed_total", 0) or 0)
        remaining = max(sheet_total - completed, 0)
        progress_pct = round(sheet_progress(chapter) * 100, 2)

        row_cols = st.columns([2.2, 1.4, 0.95, 0.85, 0.85, 0.95, 1.05, 1.0, 0.85, 1.1, 1.4])
        row_cols[0].markdown(f"<div class='table-row-cell chapter-cell'>{chapter_name}</div>", unsafe_allow_html=True)
        row_cols[1].markdown(f"<div class='table-row-cell'>{render_status_badge(chapter.get('status', 'learning'))}</div>", unsafe_allow_html=True)
        row_cols[2].markdown(f"<div class='table-row-cell'>{chapter.get('total_lectures_watched', 0)}</div>", unsafe_allow_html=True)
        row_cols[3].markdown(f"<div class='table-row-cell'>{sheet_total}</div>", unsafe_allow_html=True)
        row_cols[4].markdown(f"<div class='table-row-cell'>{completed}</div>", unsafe_allow_html=True)
        row_cols[5].markdown(f"<div class='table-row-cell'>{remaining}</div>", unsafe_allow_html=True)
        row_cols[6].markdown(f"<div class='table-row-cell'>{progress_pct}%</div>", unsafe_allow_html=True)
        row_cols[7].markdown(
            f"<div class='table-row-cell'>{last_accuracy if last_accuracy is not None else '-'}%</div>",
            unsafe_allow_html=True,
        )
        row_cols[8].markdown(
            f"<div class='table-row-cell'>{len(chapter.get('practice_sessions', []))}</div>",
            unsafe_allow_html=True,
        )
        row_cols[9].markdown(f"<div class='table-row-cell'>{format_date(next_date)}</div>", unsafe_allow_html=True)

        action_cell = row_cols[10].columns(2)
        if action_cell[0].button("✏️", key=f"edit_{chapter_name}"):
            st.session_state["edit_chapter"] = chapter_name
        if action_cell[1].button("🗑️", key=f"delete_{chapter_name}"):
            st.session_state["delete_chapter"] = chapter_name

        if st.session_state.get("edit_chapter") == chapter_name:
            with st.form(f"edit_form_{chapter_name}"):
                edit_name = st.text_input("Chapter name", value=chapter_name)
                edit_subject = st.selectbox("Subject", ["Maths", "Reasoning"],
                                           index=0 if chapter.get("subject") == "Maths" else 1)
                edit_sheet_total = st.number_input("Sheet size", min_value=1, step=1,
                                                   value=max(sheet_total, 1))
                edit_lectures = st.number_input("Lectures watched", min_value=0, max_value=999, step=1,
                                                value=int(chapter.get("total_lectures_watched", 0)))
                edit_questions = st.number_input("Questions solved correction", min_value=0, step=1,
                                                 value=completed)
                saved = st.form_submit_button("Save")
                if saved:
                    if not edit_name.strip():
                        st.error("Chapter name is required.")
                    elif edit_name.strip() != chapter_name and get_chapter(data, edit_name.strip()):
                        st.error("Chapter already exists.")
                    else:
                        chapter["chapter_name"] = edit_name.strip()
                        chapter["subject"] = edit_subject
                        chapter["sheet_total"] = int(edit_sheet_total)
                        chapter["total_lectures_watched"] = int(edit_lectures)
                        chapter["questions_completed_total"] = int(edit_questions)
                        sort_chapters(data)
                        save_data(data)
                        st.success("Chapter updated.")
                        st.session_state["edit_chapter"] = None
                        st.rerun()

        if st.session_state.get("delete_chapter") == chapter_name:
            st.warning(f"Delete '{chapter_name}'? This cannot be undone.")
            confirm_cols = st.columns(2)
            if confirm_cols[0].button("Confirm Delete", key=f"confirm_delete_{chapter_name}"):
                data["chapters"] = [c for c in data["chapters"] if c["chapter_name"] != chapter_name]
                save_data(data)
                st.success("Chapter deleted.")
                st.session_state["delete_chapter"] = None
                st.session_state["edit_chapter"] = None
                st.rerun()
            if confirm_cols[1].button("Cancel", key=f"cancel_delete_{chapter_name}"):
                st.session_state["delete_chapter"] = None

        st.markdown("<div class='table-row-divider'></div>", unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="SSC Maths & Reasoning Practice Tracker", layout="wide", initial_sidebar_state="collapsed")
    st.title("SSC Maths & Reasoning Practice Tracker")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,700&display=swap');

        :root {
            --bg-soft: #f8fafc;
            --card-bg: rgba(255, 255, 255, 0.88);
            --card-border: #dbe4ee;
            --ink: #0f172a;
            --muted: #475569;
            --brand: #0f766e;
            --brand-strong: #115e59;
            --accent: #0ea5e9;
        }

        html, body, [class*="stApp"] {
            font-family: 'Manrope', sans-serif;
            color: var(--ink);
            background:
                radial-gradient(circle at 0% 0%, rgba(14, 165, 233, 0.12), transparent 40%),
                radial-gradient(circle at 100% 0%, rgba(15, 118, 110, 0.12), transparent 35%),
                var(--bg-soft);
        }
        h1, h2, h3 {
            font-family: 'Fraunces', serif;
            letter-spacing: 0.2px;
        }

        div[data-testid="stTabs"] {
            background: linear-gradient(180deg, rgba(255,255,255,0.8), rgba(255,255,255,0.55));
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 10px;
            margin-bottom: 14px;
            backdrop-filter: blur(4px);
        }

        button[kind="primary"] {
            background: linear-gradient(135deg, var(--brand), var(--accent));
            border: 0;
            color: white;
            border-radius: 10px;
            font-weight: 700;
        }

        .metric-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 12px 14px;
            margin-bottom: 8px;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
        }

        .metric-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--muted);
            font-weight: 700;
        }

        .metric-value {
            font-size: 26px;
            line-height: 1.15;
            color: var(--ink);
            font-weight: 800;
            margin-top: 4px;
        }

        .chapter-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 14px;
            margin-bottom: 10px;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
        }

        .chapter-table-card {
            background: var(--card-bg);
            border: 1px solid #d5e3ef;
            border-radius: 14px;
            padding: 14px;
            margin-bottom: 8px;
            box-shadow: 0 10px 24px rgba(14, 30, 66, 0.08);
        }

        .chapter-card-compact {
            border-color: #d5e3ef;
            box-shadow: 0 10px 24px rgba(14, 30, 66, 0.08);
        }

        .chapter-card-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 10px;
        }

        .chapter-title {
            font-weight: 800;
            font-size: 17px;
            color: #0b1220;
            letter-spacing: 0.1px;
        }

        .chapter-pills {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }

        .status-pill,
        .due-pill {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }

        .table-header-cell {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: #475569;
            font-weight: 800;
            background: rgba(226, 232, 240, 0.45);
            border: 1px solid #dbe4ee;
            border-radius: 8px;
            padding: 8px 10px;
            margin-bottom: 6px;
            text-align: center;
        }

        .table-row-cell {
            font-size: 13px;
            color: #0f172a;
            font-weight: 600;
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 7px 10px;
            text-align: center;
            min-height: 34px;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .chapter-cell {
            justify-content: flex-start;
            font-weight: 800;
            color: #0b1220;
        }

        .table-row-divider {
            height: 8px;
        }

        .status-learning {
            background: rgba(47, 111, 235, 0.14);
            color: #1d4ed8;
            border: 1px solid rgba(47, 111, 235, 0.3);
        }

        .status-active {
            background: rgba(240, 136, 0, 0.16);
            color: #b45309;
            border: 1px solid rgba(240, 136, 0, 0.35);
        }

        .status-maintenance {
            background: rgba(46, 160, 67, 0.15);
            color: #166534;
            border: 1px solid rgba(46, 160, 67, 0.35);
        }

        .due-today {
            background: rgba(14, 165, 233, 0.15);
            color: #0369a1;
            border: 1px solid rgba(14, 165, 233, 0.32);
        }

        .due-overdue {
            background: rgba(239, 68, 68, 0.15);
            color: #b91c1c;
            border: 1px solid rgba(239, 68, 68, 0.32);
        }

        .chapter-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 10px;
        }

        .stat-chip {
            background: rgba(248, 250, 252, 0.9);
            border: 1px solid #e2e8f0;
            border-radius: 10px;
            padding: 8px 10px;
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 8px;
        }

        .stat-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #64748b;
            font-weight: 700;
        }

        .stat-value {
            font-size: 14px;
            color: #0f172a;
            font-weight: 800;
        }

        .progress-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }

        .progress-label {
            color: #475569;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .progress-value {
            color: #0f172a;
            font-size: 12px;
            font-weight: 800;
        }

        .progress-track {
            height: 8px;
            width: 100%;
            border-radius: 999px;
            background: #e2e8f0;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #0f766e, #0ea5e9);
        }

        @media (max-width: 900px) {
            .chapter-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "data" not in st.session_state:
        st.session_state["data"] = load_data()
    data = st.session_state["data"]
    updated = False
    for chapter in data["chapters"]:
        if ensure_chapter_fields(chapter):
            updated = True
    if updated:
        save_data(data)
    sort_chapters(data)

    tabs = st.tabs(["Dashboard", "Add / Update Lecture", "Log Practice", "Maintenance View", "Chapter Table"])

    with tabs[0]:
        render_dashboard(data)

    with tabs[1]:
        st.subheader("Add / Update Lecture")
        names = [c["chapter_name"] for c in data["chapters"]]
        selection = st.selectbox("Chapter", ["New chapter..."] + names, key="lecture_chapter_selection")
        chapter_name = st.text_input("New chapter name", key="lecture_new_chapter_name") if selection == "New chapter..." else selection
        lectures = st.number_input("Lectures watched today", min_value=0, max_value=10, value=0, step=1, key="lecture_count")
        if st.button("Update lectures", key="update_lectures_button"):
            if not chapter_name:
                st.error("Chapter name is required.")
            else:
                chapter = ensure_chapter(data, chapter_name)
                lecture_logged = record_lecture(chapter, int(lectures))
                adjust_next_practice_for_lecture(chapter, lecture_logged)
                save_data(data)
                st.success("Lecture count updated.")
                st.rerun()

    with tabs[2]:
        st.subheader("Log Practice")
        if not data["chapters"]:
            st.info("Add a chapter first.")
        else:
            chapter_name = st.selectbox(
                "Chapter",
                [c["chapter_name"] for c in data["chapters"]],
                key="practice_selected_chapter",
            )
            with st.form("log_practice_form"):
                questions = st.number_input("Questions attempted", min_value=1, value=15, step=1)
                correct = st.number_input("Correct answers", min_value=0, value=10, step=1)
                notes = st.text_area("Notes (optional)")
                submit_practice = st.form_submit_button("Log session")
                if submit_practice:
                    chapter = get_chapter(data, chapter_name)
                    if correct > questions:
                        st.error("Correct answers cannot exceed questions attempted.")
                        st.stop()
                    accuracy = round((correct / questions) * 100, 2)
                    chapter["practice_sessions"].append(
                        {
                            "date": today_str(),
                            "questions_attempted": int(questions),
                            "correct": int(correct),
                            "accuracy": accuracy,
                            "notes": notes.strip() or None,
                        }
                    )
                    chapter["questions_completed_total"] = int(chapter.get("questions_completed_total", 0) or 0) + int(questions)
                    chapter["current_sheet_index"] = chapter.get("current_sheet_index", 0) + 1
                    update_status_after_session(chapter, accuracy)
                    set_next_practice_date(chapter, accuracy)
                    save_data(data)
                    st.success(f"Logged session. Accuracy: {accuracy}%")
                    st.rerun()

            st.divider()
            selected_chapter = get_chapter(data, chapter_name)
            if selected_chapter:
                render_practice_history(selected_chapter)

    with tabs[3]:
        render_maintenance_view(data)

    with tabs[4]:
        render_chapter_table(data)


if __name__ == "__main__":
    main()
