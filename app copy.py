import base64
import json
import random
from datetime import date, datetime, timedelta

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
    nullable_fields = {
        "next_practice_date",
        "first_lecture_date",
        "last_overdue_enforced_on",
    }
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
        "force_maintenance": False,
        "used_question_numbers": [],
        "current_question_set": [],
        "question_set_size": 15,
        "last_overdue_enforced_on": None,
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

    # Normalize sheet counters so lifecycle checks are consistent for legacy/corrected data.
    try:
        sheet_total = int(chapter.get("sheet_total", 0) or 0)
    except (TypeError, ValueError):
        sheet_total = 0
    if sheet_total < 0:
        sheet_total = 0
    if chapter.get("sheet_total") != sheet_total:
        chapter["sheet_total"] = sheet_total
        changed = True

    try:
        completed = int(chapter.get("questions_completed_total", 0) or 0)
    except (TypeError, ValueError):
        completed = 0
    if completed < 0:
        completed = 0
    if sheet_total == 0:
        normalized_completed = 0
    else:
        normalized_completed = min(completed, sheet_total)
    if chapter.get("questions_completed_total") != normalized_completed:
        chapter["questions_completed_total"] = normalized_completed
        changed = True

    if not isinstance(chapter.get("force_maintenance"), bool):
        chapter["force_maintenance"] = bool(chapter.get("force_maintenance"))
        changed = True

    try:
        set_size = int(chapter.get("question_set_size", 15) or 15)
    except (TypeError, ValueError):
        set_size = 15
    set_size = max(set_size, 1)
    if chapter.get("question_set_size") != set_size:
        chapter["question_set_size"] = set_size
        changed = True

    def sanitize_question_numbers(values):
        cleaned = []
        seen = set()
        if not isinstance(values, list):
            return cleaned
        for raw in values:
            try:
                number = int(raw)
            except (TypeError, ValueError):
                continue
            if number < 1:
                continue
            if sheet_total > 0 and number > sheet_total:
                continue
            if number in seen:
                continue
            seen.add(number)
            cleaned.append(number)
        return cleaned

    normalized_used = sanitize_question_numbers(chapter.get("used_question_numbers", []))
    if chapter.get("used_question_numbers") != normalized_used:
        chapter["used_question_numbers"] = normalized_used
        changed = True

    normalized_current = sanitize_question_numbers(chapter.get("current_question_set", []))
    if chapter.get("current_question_set") != normalized_current:
        chapter["current_question_set"] = normalized_current
        changed = True

    if sheet_total == 0:
        if chapter.get("used_question_numbers"):
            chapter["used_question_numbers"] = []
            changed = True
        if chapter.get("current_question_set"):
            chapter["current_question_set"] = []
            changed = True

    # PART 1: Remove ghost/invalid dates from chapters with no activity.
    # If no practice sessions AND no lecture dates exist, reset scheduling.
    has_practice_sessions = bool(chapter.get("practice_sessions"))
    has_lecture_dates = bool(chapter.get("lecture_dates"))
    if not has_practice_sessions and not has_lecture_dates:
        if chapter.get("next_practice_date") is not None:
            chapter["next_practice_date"] = None
            changed = True
    
    # Also validate next_practice_date format if it exists.
    next_date_str = chapter.get("next_practice_date")
    if next_date_str is not None and isinstance(next_date_str, str):
        # Try to parse it; if invalid, reset to None.
        if parse_date(next_date_str) is None:
            chapter["next_practice_date"] = None
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
        "next_practice_date": (date.today() + timedelta(days=1)).strftime("%d-%m-%y"),
        "current_sheet_index": 0,
        "lecture_dates": [],
        "first_lecture_date": None,
        "maintenance_stage": 0,
        "subject": "Maths",
        "sheet_total": 0,
        "questions_completed_total": 0,
        "force_maintenance": False,
        "used_question_numbers": [],
        "current_question_set": [],
        "question_set_size": 15,
        "last_overdue_enforced_on": None,
    }
    data["chapters"].append(chapter)
    return chapter


def normalized_sheet_counts(chapter):
    sheet_total = int(chapter.get("sheet_total", 0) or 0)
    completed = int(chapter.get("questions_completed_total", 0) or 0)
    sheet_total = max(sheet_total, 0)
    completed = max(completed, 0)
    if sheet_total == 0:
        completed = 0
    else:
        completed = min(completed, sheet_total)
    return sheet_total, completed


def generate_question_set(chapter):
    sheet_total, completed = normalized_sheet_counts(chapter)
    if sheet_total <= 0:
        return False, "Set sheet size before generating a question set."

    try:
        set_size = int(chapter.get("question_set_size", 15) or 15)
    except (TypeError, ValueError):
        set_size = 15
    set_size = max(1, min(set_size, sheet_total))
    chapter["question_set_size"] = set_size

    # Legacy progress means questions 1..completed were already solved before random sets existed.
    base_used = set(range(1, completed + 1)) if 0 < completed < sheet_total else set()

    # `used_question_numbers` tracks only questions from logged sessions.
    # Generating a set should not consume them.
    used = []
    for value in chapter.get("used_question_numbers", []):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= sheet_total:
            used.append(number)

    used_lookup = set(used).union(base_used)
    remaining = [number for number in range(1, sheet_total + 1) if number not in used_lookup]

    if len(remaining) < set_size:
        used = []
        remaining = [number for number in range(1, sheet_total + 1) if number not in base_used]

    if set_size <= 0 or not remaining:
        return False, "No unused questions available for this chapter."

    selected = sorted(random.sample(remaining, set_size))
    chapter["current_question_set"] = selected
    return True, None


def apply_overdue_enforcement(chapter):
    next_date = parse_date(chapter.get("next_practice_date"))
    if not next_date:
        return False

    today = date.today()
    overdue_days = (today - next_date).days
    if overdue_days <= 0:
        return False
    if overdue_days <= 7:
        return False

    overdue_marker = next_date.strftime("%d-%m-%y")
    if chapter.get("last_overdue_enforced_on") == overdue_marker:
        return False

    # PART 5: Apply overdue punishment/consequences.
    # Force back to active status and reset maintenance.
    if chapter.get("status") == "maintenance":
        chapter["status"] = "active"
        chapter["maintenance_stage"] = 0
    
    # Harsh penalty: If overdue > 14 days, reset questions progress to force relearning.
    if overdue_days > 14:
        chapter["questions_completed_total"] = 0
        chapter["used_question_numbers"] = []
    
    # Reschedule for tomorrow and record enforcement.
    chapter["next_practice_date"] = (today + timedelta(days=1)).strftime("%d-%m-%y")
    chapter["last_overdue_enforced_on"] = overdue_marker
    return True


def record_lecture(chapter, lectures):
    if lectures <= 0:
        return False
    chapter["total_lectures_watched"] += lectures
    today = today_str()
    if today not in chapter.get("lecture_dates", []):
        chapter.setdefault("lecture_dates", []).append(today)
    if not chapter.get("first_lecture_date"):
        chapter["first_lecture_date"] = today
    
    # PART 2: Auto-schedule chapter when practice unlocks after logging lecture.
    # If practice is now unlocked and chapter has no next_practice_date, schedule it.
    if practice_unlocks(chapter) and chapter.get("next_practice_date") is None:
        tomorrow = (date.today() + timedelta(days=1)).strftime("%d-%m-%y")
        chapter["next_practice_date"] = tomorrow
    
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


def ensure_initial_schedule(chapter):
    """
    PART 3: Guarantee scheduling consistency.
    Every chapter must have a next_practice_date.
    If missing, schedule for tomorrow immediately.
    This ensures no chapter remains unscheduled.
    """
    if chapter.get("next_practice_date") is None:
        tomorrow = (date.today() + timedelta(days=1)).strftime("%d-%m-%y")
        chapter["next_practice_date"] = tomorrow
        return True
    return False


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


def projected_future_practice_dates(chapter, count=3):
    next_date = parse_date(chapter.get("next_practice_date"))
    if not next_date or count <= 0:
        return []

    projections = [next_date]
    status = chapter.get("status", "learning")

    if status == "maintenance":
        stage = int(chapter.get("maintenance_stage", 0) or 0)
        cursor = next_date
        simulated_stage = stage
        while len(projections) < count:
            if simulated_stage <= 0:
                cursor = cursor + timedelta(days=15)
                simulated_stage = 1
            elif simulated_stage == 1:
                cursor = cursor + timedelta(days=30)
                simulated_stage = 2
            else:
                break
            projections.append(cursor)
        return projections

    cursor = next_date
    optimistic_gap = spacing_days(100)
    while len(projections) < count:
        cursor = cursor + timedelta(days=optimistic_gap)
        projections.append(cursor)
    return projections


def sheet_progress(chapter):
    sheet_total, completed = normalized_sheet_counts(chapter)
    if sheet_total <= 0:
        return 0.0
    return min(completed / sheet_total, 1.0)


def sheet_completed(chapter):
    sheet_total, completed = normalized_sheet_counts(chapter)
    return sheet_total > 0 and completed >= sheet_total


def update_status_after_session(chapter, accuracy):
    sessions = chapter["practice_sessions"]
    if chapter["status"] == "maintenance" and accuracy < 65:
        chapter["status"] = "active"
        chapter["maintenance_stage"] = 0
        return

    if chapter.get("force_maintenance"):
        chapter["status"] = "maintenance"
        chapter["maintenance_stage"] = 0
        return

    if (
        len(sessions) >= 3
        and sheet_completed(chapter)
        and len(sessions) >= 2
        and sessions[-1]["accuracy"] >= 80
        and sessions[-2]["accuracy"] >= 80
    ):
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

        detail_grid = (
            "<div class='chapter-grid chapter-grid-details'>"
            "<div class='stat-chip'>"
            "<span class='stat-label'>Last Accuracy</span>"
            f"<span class='stat-value'>{last_accuracy if last_accuracy is not None else '-'}%</span>"
            "</div>"
            "<div class='stat-chip'>"
            "<span class='stat-label'>Next Practice</span>"
            f"<span class='stat-value'>{format_date(next_date)}</span>"
            "</div>"
            "<div class='stat-chip'>"
            "<span class='stat-label'>Sessions Done</span>"
            f"<span class='stat-value'>{sessions_done}</span>"
            "</div>"
            "<div class='stat-chip'>"
            "<span class='stat-label'>Sheet Progress</span>"
            f"<span class='stat-value'>{sheet_pct}%</span>"
            "</div>"
            "</div>"
        )

        card_html = (
            "<div class='chapter-card chapter-card-compact'>"
            "<div class='chapter-card-top'>"
            f"<div class='chapter-title'>{chapter['chapter_name']}</div>"
            f"<div class='chapter-pills'>{status_badge}{due_badge}<span class='status-pill next-practice-pill'>Next: {format_date(next_date)}</span></div>"
            "</div>"
            "<div class='hover-details'>"
            f"{detail_grid}"
            "</div>"
            "<div class='progress-row'>"
            "<span class='progress-label'>Cycle Progress</span>"
            f"<span class='progress-value'>{progress_pct}%</span>"
            "</div>"
            "<div class='progress-track'>"
            f"<div class='progress-fill' style='width: {progress_pct}%;'></div>"
            "</div>"
            "</div>"
        )
        st.markdown(card_html, unsafe_allow_html=True)
    
    # PART 6: Optional debug display for scheduling (if toggle is active).
    if st.session_state.get("debug_schedule", False):
        st.divider()
        with st.expander("🔍 Debug: Scheduling Details"):
            debug_data = []
            for chapter in data["chapters"]:
                next_date = parse_date(chapter.get("next_practice_date"))
                overdue_days = None
                if next_date and next_date < today:
                    overdue_days = (today - next_date).days
                debug_data.append({
                    "Chapter": chapter["chapter_name"],
                    "Next Practice": format_date(next_date),
                    "Status": chapter.get("status", "learning").title(),
                    "Overdue Days": overdue_days if overdue_days else "-",
                    "Unlocked": "Yes" if practice_unlocks(chapter) else "No",
                    "Sessions": len(chapter.get("practice_sessions", [])),
                })
            st.dataframe(debug_data, use_container_width=True)


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
        st.markdown(
            """
            <div class='history-empty'>
                No practice sessions logged yet for this chapter.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for session in reversed(sessions):
        notes_value = session.get("notes") or "No notes added."
        st.markdown(
            f"""
            <div class='history-card history-card-compact'>
                <div class='history-top'>
                    <div class='history-date'>{session.get('date', '-')}</div>
                    <div class='chapter-pills'>
                        <span class='status-pill history-pill'>Accuracy: {session.get('accuracy', '-')}%</span>
                        <span class='status-pill history-pill'>Attempted: {session.get('questions_attempted', '-')}</span>
                        <span class='status-pill history-pill'>Correct: {session.get('correct', '-')}</span>
                    </div>
                </div>
                <div class='hover-details history-notes-wrapper'>
                    <div class='history-notes-label'>Notes</div>
                    <div class='history-notes'>{notes_value}</div>
                </div>
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
        practice_items = "".join(
            f"<li>{session.get('date', '-')} ({session.get('accuracy', '-')}%)</li>"
            for session in chapter.get("practice_sessions", [])
        )
        if not practice_items:
            practice_items = "<li>No sessions yet</li>"

        projected_items = "".join(
            f"<li>{format_date(future_date)}</li>"
            for future_date in projected_future_practice_dates(chapter, count=3)
        )
        if not projected_items:
            projected_items = "<li>No upcoming dates</li>"

        maintenance_meta = ""
        if chapter.get("status") == "maintenance":
            maintenance_meta = f"<div>Maintenance Stage: {int(chapter.get('maintenance_stage', 0) or 0)}</div>"

        timeline_html = (
            "<div class='next-hover-wrapper'>"
            f"{format_date(next_date)}"
            "<div class='timeline-hover'>"
            f"<div><strong>First Lecture:</strong> {format_date(parse_date(chapter.get('first_lecture_date')))}</div>"
            "<div style='margin-top:6px;'><strong>Practice Sessions:</strong></div>"
            f"<ul>{practice_items}</ul>"
            "<div style='margin-top:6px;'><strong>Projected Next Dates:</strong></div>"
            f"<ul>{projected_items}</ul>"
            f"<div><strong>Status:</strong> {chapter.get('status', 'learning').title()}</div>"
            f"{maintenance_meta}"
            "</div>"
            "</div>"
        )
        row_cols[9].markdown(f"<div class='table-row-cell'>{timeline_html}</div>", unsafe_allow_html=True)

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
                edit_force_maintenance = st.checkbox(
                    "Force maintenance",
                    value=bool(chapter.get("force_maintenance", False)),
                    help="Manually keep this chapter in maintenance mode.",
                )
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
                        chapter["force_maintenance"] = bool(edit_force_maintenance)
                        ensure_chapter_fields(chapter)
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

        .section-hero {
            background: linear-gradient(135deg, rgba(15, 118, 110, 0.1), rgba(14, 165, 233, 0.1));
            border: 1px solid #c8d9ea;
            border-radius: 12px;
            padding: 10px 12px;
            margin-bottom: 12px;
        }

        .section-hero-title {
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.7px;
            color: #0f766e;
            font-weight: 800;
            margin-bottom: 2px;
        }

        .section-hero-sub {
            font-size: 13px;
            color: #334155;
            font-weight: 600;
        }

        .section-inline-card {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 10px;
        }

        .mini-chip {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 5px 10px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: 0.4px;
            text-transform: uppercase;
            color: #0f172a;
            background: rgba(248, 250, 252, 0.95);
            border: 1px solid #dbe4ee;
        }

        .history-empty {
            border: 1px dashed #cbd5e1;
            color: #64748b;
            background: rgba(248, 250, 252, 0.6);
            border-radius: 10px;
            padding: 12px;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 8px;
        }

        .history-card {
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid #dbe4ee;
            border-radius: 12px;
            padding: 10px 12px;
            margin-bottom: 8px;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.05);
        }

        .history-card-compact {
            cursor: pointer;
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
        }

        .history-card-compact:hover {
            transform: translateY(-1px);
            border-color: #93c5fd;
            box-shadow: 0 10px 24px rgba(14, 30, 66, 0.1);
        }

        .history-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }

        .history-date {
            font-size: 13px;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: 0.2px;
        }

        .history-pill {
            background: rgba(14, 165, 233, 0.09);
            color: #075985;
            border: 1px solid rgba(14, 165, 233, 0.24);
        }

        .history-notes-label {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: #475569;
            font-weight: 800;
            margin-bottom: 4px;
        }

        .history-notes-wrapper {
            margin-top: 8px;
        }

        .history-card-compact:hover .history-notes-wrapper,
        .history-card-compact:focus-within .history-notes-wrapper {
            max-height: 200px;
            opacity: 1;
            transform: translateY(0);
        }

        .history-notes {
            background: rgba(248, 250, 252, 0.95);
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 8px 10px;
            color: #0f172a;
            font-size: 13px;
            line-height: 1.45;
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
            cursor: pointer;
            transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease;
        }

        .chapter-card-compact:hover {
            transform: translateY(-1px);
            border-color: #93c5fd;
            box-shadow: 0 14px 28px rgba(14, 30, 66, 0.12);
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

        .next-practice-pill {
            background: rgba(15, 23, 42, 0.06);
            color: #334155;
            border: 1px solid rgba(148, 163, 184, 0.4);
            transition: opacity 200ms ease, transform 200ms ease, max-width 220ms ease, padding 200ms ease, margin 200ms ease;
            max-width: 240px;
            overflow: hidden;
            white-space: nowrap;
        }

        .chapter-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 10px;
        }

        .chapter-grid-summary {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .chapter-grid-details {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .hover-details {
            max-height: 0;
            opacity: 0;
            overflow: hidden;
            transform: translateY(-4px);
            transition: max-height 240ms ease, opacity 220ms ease, transform 220ms ease;
        }

        .chapter-card-compact:hover .hover-details,
        .chapter-card-compact:focus-within .hover-details {
            max-height: 220px;
            opacity: 1;
            transform: translateY(0);
        }

        .chapter-card-compact:hover .next-practice-pill,
        .chapter-card-compact:focus-within .next-practice-pill {
            opacity: 0;
            transform: translateY(-3px);
            max-width: 0;
            padding-left: 0;
            padding-right: 0;
            margin: 0;
            border-width: 0;
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

        .question-pill-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(64px, 1fr));
            gap: 8px;
            margin-bottom: 10px;
        }

        .question-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 12px;
            font-weight: 800;
            color: #0f172a;
            background: rgba(240, 249, 255, 0.95);
            border: 1px solid #bae6fd;
        }

        .next-hover-wrapper {
            position: relative;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 70px;
        }

        .timeline-hover {
            display: none;
            position: absolute;
            top: 22px;
            left: 0;
            width: 260px;
            max-width: 260px;
            text-align: left;
            background: white;
            border: 1px solid #dbe4ee;
            border-radius: 10px;
            padding: 10px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
            z-index: 999;
        }

        .timeline-hover ul {
            margin: 6px 0;
            padding-left: 16px;
        }

        .next-hover-wrapper:hover .timeline-hover {
            display: block;
        }

        @media (max-width: 900px) {
            .chapter-grid {
                grid-template-columns: 1fr;
            }

            .hover-details {
                max-height: 220px;
                opacity: 1;
                transform: none;
            }

            .next-practice-pill {
                display: none;
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
    enforced = False
    for chapter in data["chapters"]:
        if ensure_chapter_fields(chapter):
            updated = True
        if apply_overdue_enforcement(chapter):
            enforced = True
    if updated or enforced:
        save_data(data)
    sort_chapters(data)
    
    # PART 3: Ensure all chapters are scheduled after initial load + sort.
    all_scheduled = False
    for chapter in data["chapters"]:
        if ensure_initial_schedule(chapter):
            all_scheduled = True
    if all_scheduled:
        save_data(data)
    
    # PART 4: Show visibility warning if overdue enforcement was triggered.
    if enforced:
        st.warning("⚠️  **Overdue Enforcement Triggered!** Chapters past due date have been rescheduled. If overdue >14 days, progress was reset. Check Dashboard for details.")
    
    # Optional: Add debug toggle for scheduling visibility (PART 6).
    if "debug_schedule" not in st.session_state:
        st.session_state["debug_schedule"] = False
    debug_mode = st.sidebar.checkbox("🔍 Debug: Show Scheduling Info", value=st.session_state["debug_schedule"])
    st.session_state["debug_schedule"] = debug_mode

    tabs = st.tabs(["Dashboard", "Add / Update Lecture", "Log Practice", "Maintenance View", "Chapter Table"])

    with tabs[0]:
        render_dashboard(data)

    with tabs[1]:
        st.subheader("Add / Update Lecture")
        st.markdown(
            """
            <div class='section-hero'>
                <div class='section-hero-title'>Lecture Tracker</div>
                <div class='section-hero-sub'>Choose a chapter and quickly log today's lecture count.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        names = [c["chapter_name"] for c in data["chapters"]]
        top_cols = st.columns([2, 1])
        with top_cols[0]:
            selection = st.selectbox("Chapter", ["New chapter..."] + names, key="lecture_chapter_selection")
            chapter_name = st.text_input("New chapter name", key="lecture_new_chapter_name") if selection == "New chapter..." else selection
        with top_cols[1]:
            lectures = st.number_input("Lectures watched today", min_value=0, max_value=10, value=0, step=1, key="lecture_count")

        chapter_preview = get_chapter(data, chapter_name) if chapter_name and selection != "New chapter..." else None
        if chapter_preview:
            preview_next = format_date(parse_date(chapter_preview.get("next_practice_date")))
            st.markdown(
                f"""
                <div class='section-inline-card'>
                    <span class='mini-chip'>Status: {chapter_preview.get('status', 'learning').title()}</span>
                    <span class='mini-chip'>Total lectures: {chapter_preview.get('total_lectures_watched', 0)}</span>
                    <span class='mini-chip'>Next practice: {preview_next}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

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
        st.markdown(
            """
            <div class='section-hero'>
                <div class='section-hero-title'>Practice Logger</div>
                <div class='section-hero-sub'>Log attempts, accuracy, and notes to keep revision spaced and consistent. Scroll down to see your logged practices.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not data["chapters"]:
            st.info("Add a chapter first.")
        else:
            chapter_name = st.selectbox(
                "Chapter",
                [c["chapter_name"] for c in data["chapters"]],
                key="practice_selected_chapter",
            )

            selected_chapter = get_chapter(data, chapter_name)
            if selected_chapter:
                last_acc = selected_chapter["practice_sessions"][-1]["accuracy"] if selected_chapter["practice_sessions"] else "-"
                next_practice = format_date(parse_date(selected_chapter.get("next_practice_date")))
                sheet_total, _ = normalized_sheet_counts(selected_chapter)
                solved_sequential = int(selected_chapter.get("questions_completed_total", 0) or 0)
                solved_sequential = max(0, min(solved_sequential, sheet_total)) if sheet_total > 0 else 0
                used_count = len(selected_chapter.get("used_question_numbers", [])) if sheet_total > 0 else 0
                effective_used = max(used_count, solved_sequential)
                coverage_pct = round((effective_used / sheet_total) * 100, 2) if sheet_total > 0 else 0
                remaining_unused = max(sheet_total - effective_used, 0)
                st.markdown(
                    f"""
                    <div class='section-inline-card'>
                        <span class='mini-chip'>Status: {selected_chapter.get('status', 'learning').title()}</span>
                        <span class='mini-chip'>Last accuracy: {last_acc}%</span>
                        <span class='mini-chip'>Sessions: {len(selected_chapter.get('practice_sessions', []))}</span>
                        <span class='mini-chip'>Next practice: {next_practice}</span>
                        <span class='mini-chip'>Coverage: {coverage_pct}%</span>
                        <span class='mini-chip'>Unused questions: {remaining_unused}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                st.markdown("#### Generate Question Set")
                max_set_size = sheet_total if sheet_total > 0 else 1
                configured_default = min(
                    int(selected_chapter.get("question_set_size", 15) or 15),
                    max_set_size,
                )
                configured_set_size = st.number_input(
                    "Question set size",
                    min_value=1,
                    max_value=max_set_size,
                    value=configured_default,
                    step=1,
                    key=f"question_set_size_{chapter_name}",
                    disabled=sheet_total <= 0,
                )
                if sheet_total > 0 and int(selected_chapter.get("question_set_size", 15) or 15) != int(configured_set_size):
                    selected_chapter["question_set_size"] = int(configured_set_size)
                    save_data(data)
                    st.rerun()

                action_cols = st.columns([1, 1, 2])
                if action_cols[0].button("Generate Practice Set", key=f"generate_set_{chapter_name}"):
                    selected_chapter["question_set_size"] = int(configured_set_size)
                    ok, message = generate_question_set(selected_chapter)
                    if not ok:
                        st.error(message)
                    else:
                        save_data(data)
                        st.success("Practice set generated.")
                        st.rerun()

                if action_cols[1].button(
                    "Regenerate Set",
                    key=f"regenerate_set_{chapter_name}",
                    disabled=not bool(selected_chapter.get("current_question_set")),
                ):
                    selected_chapter["question_set_size"] = int(configured_set_size)
                    ok, message = generate_question_set(selected_chapter)
                    if not ok:
                        st.error(message)
                    else:
                        save_data(data)
                        st.success("Practice set regenerated.")
                        st.rerun()

                current_set = selected_chapter.get("current_question_set", [])
                if current_set:
                    pills = "".join(f"<span class='question-pill'>Q{num}</span>" for num in current_set)
                    st.markdown(f"<div class='question-pill-grid'>{pills}</div>", unsafe_allow_html=True)
                else:
                    st.info("Generate a practice set to start logging this session.")

            st.markdown("#### Log Results")
            current_set = selected_chapter.get("current_question_set", []) if selected_chapter else []
            attempted = len(current_set)
            if attempted:
                st.caption(f"Questions attempted are fixed to the generated set size: {attempted}")
            with st.form("log_practice_form"):
                correct = st.number_input(
                    "Correct answers",
                    min_value=0,
                    max_value=attempted if attempted else 0,
                    value=min(10, attempted) if attempted else 0,
                    step=1,
                    disabled=attempted == 0,
                )
                notes = st.text_area(
                    "Notes (optional)",
                    placeholder="Weak topics, mistakes, trick notes, or reminders for next session...",
                    disabled=attempted == 0,
                )
                st.caption("Tip: Keep notes short and actionable so you can revise them quickly later.")
                submit_practice = st.form_submit_button("Log session", disabled=attempted == 0)
                if submit_practice:
                    chapter = get_chapter(data, chapter_name)
                    accuracy = round((correct / attempted) * 100, 2) if attempted else 0
                    existing_used = []
                    for value in chapter.get("used_question_numbers", []):
                        try:
                            number = int(value)
                        except (TypeError, ValueError):
                            continue
                        if number > 0:
                            existing_used.append(number)
                    consumed_questions = [
                        int(q)
                        for q in chapter.get("current_question_set", [])
                        if isinstance(q, int) or (isinstance(q, str) and q.isdigit())
                    ]
                    chapter["practice_sessions"].append(
                        {
                            "date": today_str(),
                            "questions_attempted": attempted,
                            "correct": int(correct),
                            "accuracy": accuracy,
                            "notes": notes.strip() or None,
                        }
                    )
                    chapter["used_question_numbers"] = sorted(
                        set(existing_used).union(consumed_questions)
                    )
                    chapter["questions_completed_total"] = int(chapter.get("questions_completed_total", 0) or 0) + attempted
                    chapter["current_question_set"] = []
                    update_status_after_session(chapter, accuracy)
                    set_next_practice_date(chapter, accuracy)
                    save_data(data)
                    st.success(f"Logged session. Accuracy: {accuracy}%")
                    st.rerun()

            st.divider()
            if selected_chapter:
                render_practice_history(selected_chapter)

    with tabs[3]:
        render_maintenance_view(data)

    with tabs[4]:
        render_chapter_table(data)


if __name__ == "__main__":
    main()
