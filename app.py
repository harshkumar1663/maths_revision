import base64
import json
from datetime import date, datetime, timedelta

import requests
import streamlit as st

REPO_NAME = "gk_revision_data"
DATA_PATH = "maths_data.json"
BRANCH = "main"


def today_str():
    return date.today().isoformat()


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_date(value):
    if not value:
        return "-"
    if isinstance(value, date):
        return value.isoformat()
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
        if key not in chapter or chapter[key] is None:
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
    if response.status_code in (200, 201):
        st.session_state["github_sha"] = response.json().get("content", {}).get("sha")
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
        return
    chapter["total_lectures_watched"] += lectures
    today = today_str()
    if today not in chapter.get("lecture_dates", []):
        chapter.setdefault("lecture_dates", []).append(today)
    if not chapter.get("first_lecture_date"):
        chapter["first_lecture_date"] = today


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
        chapter["next_practice_date"] = next_date.isoformat() if next_date else None
        return
    next_days = spacing_days(accuracy)
    next_date = date.today() + timedelta(days=next_days)
    chapter["next_practice_date"] = next_date.isoformat()


def sort_chapters(data):
    data["chapters"] = sorted(data["chapters"], key=lambda c: c["chapter_name"].lower())


def status_color(status):
    return {
        "learning": "#2f6feb",
        "active": "#f08800",
        "maintenance": "#2ea043",
    }.get(status, "#6e7781")


def render_status_badge(status):
    color = status_color(status)
    return f"<span style='background:{color};color:white;padding:2px 8px;border-radius:999px;font-size:12px;'>" \
           f"{status.title()}</span>"


def render_dashboard(data):
    st.subheader("Chapter Overview")
    today = date.today()
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
        with st.container():
            st.markdown(
                f"""
                <div style='border:1px solid #e5e7eb;border-radius:12px;padding:12px;margin-bottom:10px;'>
                    <div style='display:flex;justify-content:space-between;align-items:center;'>
                        <div style='font-weight:600;font-size:16px;'>{chapter['chapter_name']}</div>
                        <div>{status_badge}</div>
                    </div>
                    <div style='margin-top:6px;font-size:14px;'>
                        Last accuracy: <strong>{last_accuracy if last_accuracy is not None else '-'}</strong>
                        &nbsp;|&nbsp; Next practice: <strong>{format_date(next_date)}</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if due:
                st.info("Due today")
            if overdue:
                st.warning("Overdue")
            progress = min(len(chapter["practice_sessions"]) / 4, 1.0)
            st.progress(progress)


def render_maintenance_view(data):
    st.subheader("Maintenance Cycle")
    for chapter in data["chapters"]:
        if chapter["status"] != "maintenance":
            continue
        next_date = parse_date(chapter.get("next_practice_date"))
        st.markdown(
            f"""
            <div style='border:1px solid #e5e7eb;border-radius:12px;padding:12px;margin-bottom:10px;'>
                <div style='font-weight:600;font-size:16px;'>{chapter['chapter_name']}</div>
                <div style='margin-top:6px;font-size:14px;'>Next maintenance: <strong>{format_date(next_date)}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


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

    headers = [
        "Chapter Name",
        "Subject",
        "Status",
        "Lectures Watched",
        "Sheet Size",
        "Questions Solved",
        "Remaining",
        "Sheet Progress %",
        "Last Accuracy",
        "Sessions Done",
        "Next Practice Date",
        "Actions",
    ]
    header_cols = st.columns(len(headers))
    for col, label in zip(header_cols, headers):
        col.markdown(f"<span style='font-weight:600;color:#374151;'>{label}</span>", unsafe_allow_html=True)

    for chapter in data["chapters"]:
        chapter_name = chapter["chapter_name"]
        last_accuracy = chapter["practice_sessions"][-1]["accuracy"] if chapter["practice_sessions"] else None
        next_date = parse_date(chapter.get("next_practice_date"))
        sheet_total = int(chapter.get("sheet_total", 0) or 0)
        completed = int(chapter.get("questions_completed_total", 0) or 0)
        remaining = max(sheet_total - completed, 0)
        progress_pct = round(sheet_progress(chapter) * 100, 2)
        row_cols = st.columns(len(headers))
        row_cols[0].write(chapter_name)
        row_cols[1].write(chapter.get("subject", "Maths"))
        row_cols[2].write(chapter.get("status", "learning"))
        row_cols[3].write(chapter.get("total_lectures_watched", 0))
        row_cols[4].write(sheet_total)
        row_cols[5].write(completed)
        row_cols[6].write(remaining)
        row_cols[7].write(progress_pct)
        row_cols[8].write(last_accuracy if last_accuracy is not None else "-")
        row_cols[9].write(len(chapter.get("practice_sessions", [])))
        row_cols[10].write(format_date(next_date))

        if row_cols[11].button("✏️", key=f"edit_{chapter_name}"):
            st.session_state["edit_chapter"] = chapter_name

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

            if st.button("Delete", key=f"delete_{chapter_name}"):
                st.session_state["delete_chapter"] = chapter_name

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


def main():
    st.set_page_config(page_title="SSC Maths & Reasoning Practice Tracker", layout="wide")
    st.title("SSC Maths & Reasoning Practice Tracker")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600&family=Source+Serif+4:wght@500;600&display=swap');
        html, body, [class*="stApp"] {
            font-family: 'Source Sans 3', sans-serif;
            color: #0f172a;
        }
        h1, h2, h3 {
            font-family: 'Source Serif 4', serif;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    data = load_data()
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
        selection = st.selectbox("Chapter", ["New chapter..."] + names)
        chapter_name = st.text_input("New chapter name") if selection == "New chapter..." else selection
        lectures = st.number_input("Lectures watched today", min_value=0, max_value=10, value=0, step=1)
        if st.button("Update lectures"):
            if not chapter_name:
                st.error("Chapter name is required.")
            else:
                chapter = ensure_chapter(data, chapter_name)
                record_lecture(chapter, int(lectures))
                save_data(data)
                st.success("Lecture count updated.")
                st.rerun()

    with tabs[2]:
        st.subheader("Log Practice")
        if not data["chapters"]:
            st.info("Add a chapter first.")
        else:
            chapter_name = st.selectbox("Chapter", [c["chapter_name"] for c in data["chapters"]])
            questions = st.number_input("Questions attempted", min_value=1, max_value=50, value=15, step=1)
            correct = st.number_input("Correct answers", min_value=0, max_value=50, value=10, step=1)
            notes = st.text_area("Notes (optional)")
            if st.button("Log session"):
                chapter = get_chapter(data, chapter_name)
                if questions < 15 or questions > 25:
                    st.warning("Practice sessions should be 15-25 questions.")
                    st.stop()
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

    with tabs[3]:
        render_maintenance_view(data)

    with tabs[4]:
        render_chapter_table(data)


if __name__ == "__main__":
    main()
