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
        "total_lectures_watched": 0,
        "practice_sessions": [],
        "status": "learning",
        "next_practice_date": None,
        "current_sheet_index": 0,
        "lecture_dates": [],
        "first_lecture_date": None,
        "maintenance_stage": 0,
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


def update_status_after_session(chapter, accuracy):
    sessions = chapter["practice_sessions"]
    if chapter["status"] == "maintenance" and accuracy < 65:
        chapter["status"] = "active"
        chapter["maintenance_stage"] = 0
        return
    if len(sessions) >= 3:
        recent = sessions[-3:]
        if all(s["accuracy"] >= 80 for s in recent) and len(sessions) <= 4:
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
    return (
        "<span class='status-badge' style='background:{};'>".format(color)
        + "{}".format(status.title())
        + "</span>"
    )


def inject_styles():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
        :root {
            --bg: #f6f4ef;
            --surface: #ffffff;
            --ink: #1f2933;
            --muted: #63727a;
            --border: #e6e2db;
            --accent: #0f766e;
            --accent-2: #b45309;
            --shadow: 0 14px 30px rgba(16, 24, 40, 0.08);
        }
        html, body, [class*="css"]  {
            font-family: 'Space Grotesk', sans-serif;
        }
        .stApp {
            background: radial-gradient(circle at top left, #fef3c7 0%, #f6f4ef 55%, #ecfeff 100%);
        }
        .hero {
            background: linear-gradient(120deg, #0f766e 0%, #115e59 55%, #1f2937 100%);
            color: #f9fafb;
            padding: 24px;
            border-radius: 18px;
            box-shadow: var(--shadow);
            margin-bottom: 18px;
        }
        .hero h1 {
            font-size: 30px;
            margin: 0 0 8px 0;
            font-weight: 700;
        }
        .hero p {
            margin: 0;
            color: #d1fae5;
            font-size: 15px;
        }
        .section-title {
            font-weight: 700;
            color: var(--ink);
            margin: 10px 0 12px 0;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 14px;
        }
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 14px;
            box-shadow: var(--shadow);
        }
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 6px;
        }
        .card-title {
            font-weight: 600;
            font-size: 16px;
            color: var(--ink);
        }
        .card-meta {
            color: var(--muted);
            font-size: 13px;
        }
        .status-badge {
            color: #fff;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 600;
        }
        .tag {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            font-weight: 600;
            padding: 4px 8px;
            border-radius: 999px;
            margin-top: 8px;
        }
        .tag.due {
            background: #dbeafe;
            color: #1d4ed8;
        }
        .tag.overdue {
            background: #fee2e2;
            color: #b91c1c;
        }
        .progress-track {
            width: 100%;
            height: 8px;
            background: #e5e7eb;
            border-radius: 999px;
            overflow: hidden;
            margin-top: 10px;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(120deg, #0f766e, #14b8a6);
        }
        .pill {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 12px;
            padding: 2px 8px;
            background: #fef3c7;
            border-radius: 999px;
            color: #92400e;
        }
        .form-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            box-shadow: var(--shadow);
        }
        @media (max-width: 740px) {
            .hero {
                padding: 18px;
            }
            .hero h1 {
                font-size: 24px;
            }
            .grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard(data):
    st.markdown("<div class='section-title'>Chapter Overview</div>", unsafe_allow_html=True)
    today = date.today()
    cards = []
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
        progress = min(len(chapter["practice_sessions"]) / 4, 1.0)
        tags = ""
        if overdue:
            tags += "<div class='tag overdue'>Overdue</div>"
        elif due:
            tags += "<div class='tag due'>Due today</div>"
        cards.append(
            f"""
            <div class='card'>
                <div class='card-header'>
                    <div class='card-title'>{chapter['chapter_name']}</div>
                    {status_badge}
                </div>
                <div class='card-meta'>
                    Last accuracy: <span class='pill'>{last_accuracy if last_accuracy is not None else '-'}</span>
                    &nbsp;|&nbsp; Next practice: <span class='pill'>{format_date(next_date)}</span>
                </div>
                {tags}
                <div class='progress-track'>
                    <div class='progress-fill' style='width:{int(progress * 100)}%'></div>
                </div>
            </div>
            """
        )
    if not cards:
        st.info("No chapters yet. Add lectures to get started.")
        return
    st.markdown("<div class='grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def render_maintenance_view(data):
    st.markdown("<div class='section-title'>Maintenance Cycle</div>", unsafe_allow_html=True)
    cards = []
    for chapter in data["chapters"]:
        if chapter["status"] != "maintenance":
            continue
        next_date = parse_date(chapter.get("next_practice_date"))
        cards.append(
            f"""
            <div class='card'>
                <div class='card-title'>{chapter['chapter_name']}</div>
                <div class='card-meta' style='margin-top:6px;'>Next maintenance: <span class='pill'>{format_date(next_date)}</span></div>
            </div>
            """
        )
    if not cards:
        st.info("No chapters in maintenance yet.")
        return
    st.markdown("<div class='grid'>" + "".join(cards) + "</div>", unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="SSC Maths & Reasoning Practice Tracker", layout="wide")
    inject_styles()
    st.markdown(
        """
        <div class='hero'>
            <h1>SSC Maths & Reasoning Practice Tracker</h1>
            <p>Practice cycles for skill stability: lectures, sessions, spacing, and maintenance.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    data = load_data()
    sort_chapters(data)

    tabs = st.tabs(["Dashboard", "Add / Update Lecture", "Log Practice", "Maintenance View"])

    with tabs[0]:
        render_dashboard(data)

    with tabs[1]:
        st.markdown("<div class='section-title'>Add / Update Lecture</div>", unsafe_allow_html=True)
        with st.container():
            st.markdown("<div class='form-card'>", unsafe_allow_html=True)
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
            st.markdown("</div>", unsafe_allow_html=True)

    with tabs[2]:
        st.markdown("<div class='section-title'>Log Practice</div>", unsafe_allow_html=True)
        if not data["chapters"]:
            st.info("Add a chapter first.")
        else:
            with st.container():
                st.markdown("<div class='form-card'>", unsafe_allow_html=True)
                chapter_name = st.selectbox("Chapter", [c["chapter_name"] for c in data["chapters"]])
                col_a, col_b = st.columns(2)
                with col_a:
                    questions = st.number_input("Questions attempted", min_value=1, max_value=50, value=15, step=1)
                with col_b:
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
                    chapter["current_sheet_index"] = chapter.get("current_sheet_index", 0) + 1
                    update_status_after_session(chapter, accuracy)
                    set_next_practice_date(chapter, accuracy)
                    save_data(data)
                    st.success(f"Logged session. Accuracy: {accuracy}%")
                st.markdown("</div>", unsafe_allow_html=True)

    with tabs[3]:
        render_maintenance_view(data)


if __name__ == "__main__":
    main()
