import base64
import json
from datetime import date, datetime, timedelta

import requests
import streamlit as st

REPO_NAME = "gk_revision_data"
DATA_PATH = "maths_data.json"
BRANCH = "main"
SUBJECT_OPTIONS = ["Maths", "Reasoning"]
MIN_MAINTENANCE_SHEET_PROGRESS = 0.75
MIN_MAINTENANCE_SESSIONS = 3
MIN_MAINTENANCE_ACCURACY = 80
POST_SHEET_SESSIONS_REQUIRED = 2


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
        return existing
    chapter = {
        "chapter_name": name,
        "subject": "Maths",
        "total_lectures_watched": 0,
        "practice_sessions": [],
        "status": "learning",
        "next_practice_date": None,
        "current_sheet_index": 0,
        "lecture_dates": [],
        "first_lecture_date": None,
        "maintenance_stage": 0,
        "sheet_total": 0,
        "questions_completed_total": 0,
        "sheet_completed_at_session": None,
    }
    data["chapters"].append(chapter)
    return chapter


def normalize_chapter(chapter):
    chapter.setdefault("subject", "Maths")
    chapter.setdefault("total_lectures_watched", 0)
    chapter.setdefault("practice_sessions", [])
    chapter.setdefault("status", "learning")
    chapter.setdefault("next_practice_date", None)
    chapter.setdefault("current_sheet_index", 0)
    chapter.setdefault("lecture_dates", [])
    chapter.setdefault("first_lecture_date", None)
    chapter.setdefault("maintenance_stage", 0)
    chapter.setdefault("sheet_total", 0)
    chapter.setdefault("questions_completed_total", 0)
    chapter.setdefault("sheet_completed_at_session", None)


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


def update_status_after_session(chapter, accuracy):
    sessions = chapter["practice_sessions"]
    sheet_total = chapter.get("sheet_total", 0)
    completed = chapter.get("questions_completed_total", 0)
    sheet_progress = (completed / sheet_total) if sheet_total > 0 else 0

    if sheet_total > 0 and completed >= sheet_total and chapter.get("sheet_completed_at_session") is None:
        chapter["sheet_completed_at_session"] = len(sessions)

    if chapter["status"] == "maintenance" and accuracy < 65:
        chapter["status"] = "active"
        chapter["maintenance_stage"] = 0
        return

    allow_maintenance = False
    if (
        len(sessions) >= MIN_MAINTENANCE_SESSIONS
        and accuracy >= MIN_MAINTENANCE_ACCURACY
        and sheet_progress >= MIN_MAINTENANCE_SHEET_PROGRESS
    ):
        if sheet_total > 0 and completed >= sheet_total:
            completed_at = chapter.get("sheet_completed_at_session")
            sessions_since = len(sessions) - completed_at if completed_at is not None else 0
            if sessions_since >= POST_SHEET_SESSIONS_REQUIRED:
                allow_maintenance = True
        else:
            allow_maintenance = True

    if allow_maintenance:
        chapter["status"] = "maintenance"
        chapter["maintenance_stage"] = 0
        return

    if chapter["status"] == "learning":
        chapter["status"] = "active"


def set_next_practice_date(chapter, accuracy):
    if chapter["status"] == "maintenance":
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


def sheet_stats(chapter):
    total = int(chapter.get("sheet_total", 0) or 0)
    completed = int(chapter.get("questions_completed_total", 0) or 0)
    if total <= 0:
        return total, completed, None, None
    remaining = max(total - completed, 0)
    progress = min(completed / total, 1.0)
    return total, completed, remaining, progress


def due_state(chapter):
    today = date.today()
    next_date = parse_date(chapter.get("next_practice_date"))
    due = False
    overdue = False
    if next_date:
        due = next_date == today
        overdue = next_date < today
    elif practice_unlocks(chapter):
        due = True
    return next_date, due, overdue


def render_table_header():
    cols = st.columns([2.2, 1.1, 1.1, 1.0, 1.0, 1.2, 1.2, 1.4, 1.0, 1.0, 1.3, 1.4])
    labels = [
        "Chapter Name",
        "Subject",
        "Status",
        "Lectures",
        "Sheet Size",
        "Solved",
        "Remaining",
        "Sheet Progress",
        "Last Accuracy",
        "Sessions",
        "Next Practice",
        "Actions",
    ]
    for col, label in zip(cols, labels):
        col.markdown(f"**{label}**")


def render_chapter_row(chapter, index):
    total, completed, remaining, progress = sheet_stats(chapter)
    last_accuracy = chapter["practice_sessions"][-1]["accuracy"] if chapter["practice_sessions"] else None
    next_date, due, overdue = due_state(chapter)
    status_badge = render_status_badge(chapter["status"])

    cols = st.columns([2.2, 1.1, 1.1, 1.0, 1.0, 1.2, 1.2, 1.4, 1.0, 1.0, 1.3, 1.4])
    due_label = ""
    if overdue:
        due_label = "🔴 Overdue"
    elif due:
        due_label = "🟠 Due"

    with cols[0]:
        st.markdown(f"**{chapter['chapter_name']}**")
        if due_label:
            st.caption(due_label)
    with cols[1]:
        st.markdown(chapter.get("subject", "Maths"))
    with cols[2]:
        st.markdown(status_badge, unsafe_allow_html=True)
    with cols[3]:
        st.markdown(str(chapter.get("total_lectures_watched", 0)))
    with cols[4]:
        st.markdown(str(total) if total > 0 else "-")
    with cols[5]:
        st.markdown(str(completed))
    with cols[6]:
        st.markdown(str(remaining) if remaining is not None else "-")
    with cols[7]:
        if progress is None:
            st.markdown("-")
        else:
            st.markdown(f"{round(progress * 100, 1)}%")
            st.progress(progress)
    with cols[8]:
        st.markdown(str(last_accuracy) if last_accuracy is not None else "-")
    with cols[9]:
        st.markdown(str(len(chapter["practice_sessions"])))
    with cols[10]:
        st.markdown(format_date(next_date))
    with cols[11]:
        if st.button("Edit", key=f"edit_{index}"):
            st.session_state["edit_chapter"] = chapter["chapter_name"]
        if st.button("Reset", key=f"reset_{index}"):
            st.session_state["reset_chapter"] = chapter["chapter_name"]
        if st.button("Delete", key=f"delete_{index}"):
            st.session_state["delete_chapter"] = chapter["chapter_name"]


def render_add_chapter(data):
    if st.button("➕ Add Chapter"):
        st.session_state["show_add_chapter"] = True

    if not st.session_state.get("show_add_chapter"):
        return

    with st.form("add_chapter_form"):
        chapter_name = st.text_input("Chapter name")
        subject = st.selectbox("Subject", SUBJECT_OPTIONS)
        sheet_total = st.number_input("Sheet size (required)", min_value=1, value=50, step=1)
        lectures = st.number_input("Lectures watched", min_value=0, max_value=50, value=0, step=1)
        submitted = st.form_submit_button("Create")
        if submitted:
            if not chapter_name.strip():
                st.error("Chapter name is required.")
                return
            if get_chapter(data, chapter_name.strip()):
                st.error("Chapter already exists.")
                return
            chapter = ensure_chapter(data, chapter_name.strip())
            chapter["subject"] = subject
            chapter["sheet_total"] = int(sheet_total)
            record_lecture(chapter, int(lectures))
            save_data(data)
            st.session_state["show_add_chapter"] = False
            st.success("Chapter added.")


def render_edit_form(data):
    name = st.session_state.get("edit_chapter")
    if not name:
        return
    chapter = get_chapter(data, name)
    if not chapter:
        st.session_state["edit_chapter"] = None
        return

    st.subheader("Edit Chapter")
    with st.form("edit_chapter_form"):
        new_name = st.text_input("Chapter name", value=chapter["chapter_name"])
        current_subject = chapter.get("subject", "Maths")
        subject_index = SUBJECT_OPTIONS.index(current_subject) if current_subject in SUBJECT_OPTIONS else 0
        subject = st.selectbox("Subject", SUBJECT_OPTIONS, index=subject_index)
        sheet_total = st.number_input("Sheet size", min_value=1, value=int(chapter.get("sheet_total", 0) or 1), step=1)
        lectures = st.number_input("Lectures watched", min_value=0, max_value=200, value=int(chapter.get("total_lectures_watched", 0)), step=1)
        solved_correction = st.number_input(
            "Solved count correction",
            min_value=0,
            value=int(chapter.get("questions_completed_total", 0)),
            step=1,
        )
        submitted = st.form_submit_button("Save changes")
        if submitted:
            new_name = new_name.strip()
            if not new_name:
                st.error("Chapter name is required.")
                return
            if new_name != chapter["chapter_name"] and get_chapter(data, new_name):
                st.error("Chapter name already exists.")
                return
            chapter["chapter_name"] = new_name
            chapter["subject"] = subject
            chapter["sheet_total"] = int(sheet_total)
            chapter["total_lectures_watched"] = int(lectures)
            chapter["questions_completed_total"] = int(solved_correction)
            save_data(data)
            st.session_state["edit_chapter"] = None
            st.success("Chapter updated.")


def render_reset_confirm(data):
    name = st.session_state.get("reset_chapter")
    if not name:
        return
    chapter = get_chapter(data, name)
    if not chapter:
        st.session_state["reset_chapter"] = None
        return
    st.warning(f"Reset progress for {name}?")
    col_yes, col_no = st.columns([1, 1])
    with col_yes:
        if st.button("Confirm reset"):
            chapter["practice_sessions"] = []
            chapter["status"] = "learning"
            chapter["next_practice_date"] = None
            chapter["maintenance_stage"] = 0
            chapter["questions_completed_total"] = 0
            chapter["sheet_completed_at_session"] = None
            save_data(data)
            st.session_state["reset_chapter"] = None
            st.success("Progress reset.")
    with col_no:
        if st.button("Cancel", key="cancel_reset"):
            st.session_state["reset_chapter"] = None


def render_delete_confirm(data):
    name = st.session_state.get("delete_chapter")
    if not name:
        return
    chapter = get_chapter(data, name)
    if not chapter:
        st.session_state["delete_chapter"] = None
        return
    st.warning(f"Delete {name}? This cannot be undone.")
    col_yes, col_no = st.columns([1, 1])
    with col_yes:
        if st.button("Confirm delete"):
            data["chapters"] = [c for c in data["chapters"] if c["chapter_name"] != name]
            save_data(data)
            st.session_state["delete_chapter"] = None
            st.success("Chapter deleted.")
    with col_no:
        if st.button("Cancel", key="cancel_delete"):
            st.session_state["delete_chapter"] = None


def main():
    st.set_page_config(page_title="SSC Maths & Reasoning Practice Tracker", layout="wide")
    st.title("SSC Maths & Reasoning Practice Tracker")

    data = load_data()
    for chapter in data["chapters"]:
        normalize_chapter(chapter)
    sort_chapters(data)
    render_add_chapter(data)

    st.subheader("Chapter Table")
    if not data["chapters"]:
        st.info("Add a chapter to get started.")
    else:
        render_table_header()
        for index, chapter in enumerate(data["chapters"]):
            render_chapter_row(chapter, index)
            st.divider()

    render_edit_form(data)
    render_reset_confirm(data)
    render_delete_confirm(data)

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
            if chapter.get("sheet_total", 0) <= 0:
                st.error("Sheet size is required before logging practice.")
                st.stop()
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
            chapter["questions_completed_total"] = chapter.get("questions_completed_total", 0) + int(questions)
            chapter["current_sheet_index"] = chapter.get("current_sheet_index", 0) + 1
            update_status_after_session(chapter, accuracy)
            set_next_practice_date(chapter, accuracy)
            save_data(data)
            st.success(f"Logged session. Accuracy: {accuracy}%")


if __name__ == "__main__":
    main()
