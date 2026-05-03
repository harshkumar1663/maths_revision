import base64
import json
import random
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

import requests
import streamlit as st

REPO_NAME = "gk_revision_data"
DATA_PATH = "maths_data.json"
BRANCH = "main"
PRACTICE_MODES = ["assisted_practice", "recall_practice"]


# -----------------------------
# Persistence helpers
# -----------------------------
def _today() -> date:
    return date.today()


def _today_str() -> str:
    return _today().isoformat()


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_question_list(values: List[Any], total_questions: int) -> List[int]:
    cleaned: List[int] = []
    seen = set()
    for raw in values:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number < 1 or number > total_questions:
            continue
        if number in seen:
            continue
        seen.add(number)
        cleaned.append(number)
    return cleaned


def _default_data() -> Dict[str, Any]:
    return {"chapters": []}


def _get_github_config() -> Tuple[str, str | None]:
    token = st.secrets.get("GITHUB_TOKEN")
    owner = st.secrets.get("GITHUB_OWNER", "harshkumar1663")
    return owner, token


def _github_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def _default_chapter(name: str, total_questions: int, question_set_size: int) -> Dict[str, Any]:
    size = max(1, min(question_set_size, total_questions))
    return {
        "chapter_name": name,
        "total_questions": total_questions,
        "next_review_date": _today_str(),
        "last_review_date": "",
        "interval_days": 1.0,
        "ease_factor": 2.5,
        "repetition_count": 0,
        "recall_history": [],
        "weak_questions": [],
        "question_last_seen": {},
        "used_question_numbers": [],
        "current_question_set": [],
        "question_set_size": size,
        # Internal helper for optional weak-question removal.
        "question_correct_streak": {},
    }


def _ensure_chapter_schema(chapter: Dict[str, Any]) -> None:
    name = str(chapter.get("chapter_name", "")).strip()
    total_questions = int(chapter.get("total_questions", 0) or 0)
    total_questions = max(total_questions, 1)
    size = int(chapter.get("question_set_size", 10) or 10)

    defaults = _default_chapter(name, total_questions, size)
    for key, value in defaults.items():
        if key not in chapter:
            chapter[key] = value

    chapter["chapter_name"] = name
    chapter["total_questions"] = total_questions
    chapter["question_set_size"] = max(1, min(int(chapter.get("question_set_size", 10)), total_questions))

    chapter["interval_days"] = float(chapter.get("interval_days", 1.0) or 1.0)
    chapter["interval_days"] = max(chapter["interval_days"], 1.0)

    chapter["ease_factor"] = float(chapter.get("ease_factor", 2.5) or 2.5)
    chapter["ease_factor"] = max(chapter["ease_factor"], 1.3)

    chapter["repetition_count"] = int(chapter.get("repetition_count", 0) or 0)
    chapter["repetition_count"] = max(chapter["repetition_count"], 0)

    if not isinstance(chapter.get("recall_history"), list):
        chapter["recall_history"] = []

    chapter["weak_questions"] = _normalize_question_list(chapter.get("weak_questions", []), total_questions)
    chapter["used_question_numbers"] = _normalize_question_list(chapter.get("used_question_numbers", []), total_questions)
    chapter["current_question_set"] = _normalize_question_list(chapter.get("current_question_set", []), total_questions)

    if not isinstance(chapter.get("question_last_seen"), dict):
        chapter["question_last_seen"] = {}

    filtered_seen = {}
    for k, v in chapter["question_last_seen"].items():
        try:
            q = int(k)
        except (TypeError, ValueError):
            continue
        if 1 <= q <= total_questions:
            filtered_seen[str(q)] = str(v)
    chapter["question_last_seen"] = filtered_seen

    if not isinstance(chapter.get("question_correct_streak"), dict):
        chapter["question_correct_streak"] = {}


def load_data() -> Dict[str, Any]:
    owner, token = _get_github_config()
    if not token:
        st.error("Missing GITHUB_TOKEN in Streamlit secrets.")
        st.stop()

    url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}?ref={BRANCH}"
    response = requests.get(url, headers=_github_headers(token), timeout=20)

    if response.status_code == 200:
        payload = response.json()
        content = base64.b64decode(payload["content"]).decode("utf-8")
        st.session_state["github_sha"] = payload.get("sha")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = _default_data()
    elif response.status_code == 404:
        data = _default_data()
        save_data(data, creating=True)
    else:
        st.error(f"GitHub API error while loading data: {response.status_code}")
        st.stop()

    if "chapters" not in data or not isinstance(data["chapters"], list):
        data["chapters"] = []

    for chapter in data["chapters"]:
        _ensure_chapter_schema(chapter)

    save_data(data)
    return data


def save_data(data: Dict[str, Any], creating: bool = False) -> None:
    owner, token = _get_github_config()
    if not token:
        st.error("Missing GITHUB_TOKEN in Streamlit secrets.")
        st.stop()

    url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}"
    encoded = base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8")
    payload: Dict[str, Any] = {
        "message": "Update maths_data.json",
        "content": encoded,
        "branch": BRANCH,
    }

    if not creating:
        payload["sha"] = st.session_state.get("github_sha")

    response = requests.put(url, headers=_github_headers(token), json=payload, timeout=20)

    if response.status_code == 409 and not creating:
        latest_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}?ref={BRANCH}"
        latest = requests.get(latest_url, headers=_github_headers(token), timeout=20)
        if latest.status_code == 200:
            st.session_state["github_sha"] = latest.json().get("sha")
            payload["sha"] = st.session_state.get("github_sha")
            response = requests.put(url, headers=_github_headers(token), json=payload, timeout=20)

    if response.status_code in (200, 201):
        st.session_state["github_sha"] = response.json().get("content", {}).get("sha")
        st.session_state["data"] = data
        return

    st.error(f"Failed to save data to GitHub: {response.status_code}")
    st.stop()


def _find_chapter(data: Dict[str, Any], chapter_name: str) -> Dict[str, Any] | None:
    for chapter in data["chapters"]:
        if chapter["chapter_name"].lower() == chapter_name.lower():
            return chapter
    return None


# -----------------------------
# Core required functions
# -----------------------------
def create_chapter(
    data: Dict[str, Any],
    chapter_name: str,
    total_questions: int,
    question_set_size: int = 10,
) -> Tuple[bool, str]:
    chapter_name = chapter_name.strip()
    if not chapter_name:
        return False, "Chapter name cannot be empty."
    if total_questions < 1:
        return False, "Total questions must be at least 1."
    if _find_chapter(data, chapter_name):
        return False, "Chapter already exists."

    chapter = _default_chapter(chapter_name, total_questions, question_set_size)
    data["chapters"].append(chapter)
    save_data(data)
    return True, f"Created chapter '{chapter_name}'."


def _accuracy_to_quality(accuracy: float) -> int:
    if accuracy >= 90:
        return 5
    if accuracy >= 75:
        return 4
    if accuracy >= 60:
        return 3
    if accuracy >= 40:
        return 2
    return 1


def _apply_overdue_adjustment(chapter: Dict[str, Any], as_of: date) -> bool:
    next_review = _parse_date(chapter.get("next_review_date", ""))
    if not next_review:
        return False

    overdue_days = (as_of - next_review).days
    if overdue_days <= 0:
        return False

    # Overdue handling: reduce interval 30-50% and slightly reduce ease factor.
    reduction_factor = max(0.5, 0.7 - min(overdue_days, 10) * 0.02)
    chapter["interval_days"] = max(1.0, float(chapter["interval_days"]) * reduction_factor)
    chapter["ease_factor"] = max(1.3, float(chapter["ease_factor"]) - 0.05)
    return True


def update_spaced_repetition(chapter: Dict[str, Any], accuracy: float) -> Dict[str, Any]:
    today = _today()
    quality = _accuracy_to_quality(accuracy)

    _apply_overdue_adjustment(chapter, today)

    repetition_count = int(chapter["repetition_count"])
    interval_days = float(chapter["interval_days"])
    ease_factor = float(chapter["ease_factor"])

    if quality >= 3:
        repetition_count += 1
        if repetition_count == 1:
            interval_days = 1.0
        elif repetition_count == 2:
            interval_days = 3.0
        else:
            interval_days = interval_days * ease_factor
    else:
        repetition_count = 0
        interval_days = 1.0

    ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease_factor = max(1.3, ease_factor)

    chapter["repetition_count"] = repetition_count
    chapter["interval_days"] = interval_days
    chapter["ease_factor"] = ease_factor
    chapter["last_review_date"] = today.isoformat()

    schedule_days = max(1, int(round(interval_days)))
    chapter["next_review_date"] = (today + timedelta(days=schedule_days)).isoformat()

    chapter["recall_history"].append(
        {
            "date": today.isoformat(),
            "mode": "recall_practice",
            "accuracy": round(float(accuracy), 2),
            "quality": quality,
            "interval_days": round(interval_days, 2),
            "ease_factor": round(ease_factor, 3),
        }
    )

    return chapter


def generate_question_set(chapter: Dict[str, Any]) -> List[int]:
    total = int(chapter["total_questions"])
    set_size = max(1, min(int(chapter["question_set_size"]), total))

    all_questions = list(range(1, total + 1))
    used = set(_normalize_question_list(chapter.get("used_question_numbers", []), total))
    weak = set(_normalize_question_list(chapter.get("weak_questions", []), total))

    unseen_pool = [q for q in all_questions if q not in used and q not in weak]

    seen_non_weak = [q for q in all_questions if q not in weak]
    seen_non_weak.sort(
        key=lambda q: chapter.get("question_last_seen", {}).get(str(q), "1900-01-01T00:00:00")
    )
    old_pool = seen_non_weak

    weak_pool = list(weak)

    new_target = round(set_size * 0.5)
    weak_target = round(set_size * 0.3)
    old_target = set_size - new_target - weak_target

    selected: List[int] = []
    selected_set = set()

    def pick_from(pool: List[int], k: int) -> List[int]:
        available = [q for q in pool if q not in selected_set]
        if not available or k <= 0:
            return []
        if len(available) <= k:
            return available
        return random.sample(available, k)

    # 50% new/unseen
    for q in pick_from(unseen_pool, new_target):
        selected.append(q)
        selected_set.add(q)

    # 30% weak
    for q in pick_from(weak_pool, weak_target):
        selected.append(q)
        selected_set.add(q)

    # 20% old (not seen recently)
    for q in pick_from(old_pool, old_target):
        selected.append(q)
        selected_set.add(q)

    if len(selected) < set_size:
        remaining_pool = [q for q in all_questions if q not in selected_set]
        for q in pick_from(remaining_pool, set_size - len(selected)):
            selected.append(q)
            selected_set.add(q)

    selected = sorted(selected[:set_size])

    now_stamp = datetime.now().isoformat(timespec="seconds")
    for q in selected:
        chapter.setdefault("question_last_seen", {})[str(q)] = now_stamp

    chapter["current_question_set"] = selected
    return selected


def update_weak_questions(
    chapter: Dict[str, Any],
    incorrect_questions: List[int],
    correct_questions: List[int],
) -> Dict[str, Any]:
    total = int(chapter["total_questions"])
    weak_set = set(_normalize_question_list(chapter.get("weak_questions", []), total))

    incorrect = set(_normalize_question_list(incorrect_questions, total))
    correct = set(_normalize_question_list(correct_questions, total))

    streak_map = chapter.get("question_correct_streak", {})
    if not isinstance(streak_map, dict):
        streak_map = {}

    for q in incorrect:
        weak_set.add(q)
        streak_map[str(q)] = 0

    for q in correct:
        key = str(q)
        prev = int(streak_map.get(key, 0) or 0)
        streak_map[key] = prev + 1

        # Remove from weak pool after repeated correct recall.
        if q in weak_set and streak_map[key] >= 2:
            weak_set.discard(q)

    chapter["weak_questions"] = sorted(weak_set)
    chapter["question_correct_streak"] = streak_map
    return chapter


def log_practice_session(
    data: Dict[str, Any],
    chapter_name: str,
    mode: str,
    question_numbers: List[int],
    incorrect_questions: List[int],
) -> Tuple[bool, str, Dict[str, Any] | None]:
    chapter = _find_chapter(data, chapter_name)
    if not chapter:
        return False, "Chapter not found.", None

    if mode not in PRACTICE_MODES:
        return False, "Invalid practice mode.", None

    total = int(chapter["total_questions"])
    asked = _normalize_question_list(question_numbers, total)
    if not asked:
        return False, "No valid question numbers provided.", None

    incorrect = set(_normalize_question_list(incorrect_questions, total))
    incorrect = {q for q in incorrect if q in asked}
    correct = [q for q in asked if q not in incorrect]

    accuracy = (len(correct) / len(asked)) * 100.0

    update_weak_questions(chapter, list(incorrect), correct)

    used_set = set(_normalize_question_list(chapter.get("used_question_numbers", []), total))
    used_set.update(asked)
    chapter["used_question_numbers"] = sorted(used_set)

    session_record = {
        "date": _today_str(),
        "mode": mode,
        "questions": asked,
        "incorrect_questions": sorted(incorrect),
        "accuracy": round(accuracy, 2),
    }

    if mode == "recall_practice":
        update_spaced_repetition(chapter, accuracy)
    else:
        # Assisted practice has weak influence: only slight urgency bump on poor performance.
        if accuracy < 60:
            current_next = _parse_date(chapter.get("next_review_date", ""))
            tomorrow = _today() + timedelta(days=1)
            if not current_next or current_next > tomorrow:
                chapter["next_review_date"] = tomorrow.isoformat()

        chapter["recall_history"].append(session_record)

    chapter["last_review_date"] = _today_str()
    chapter["current_question_set"] = []

    save_data(data)
    return True, "Session logged.", {"accuracy": round(accuracy, 2), "incorrect": sorted(incorrect)}


# -----------------------------
# UI helpers
# -----------------------------
def _retention_score(chapter: Dict[str, Any]) -> float:
    recalls = [
        entry["accuracy"]
        for entry in chapter.get("recall_history", [])
        if isinstance(entry, dict) and entry.get("mode") == "recall_practice" and "accuracy" in entry
    ]
    if not recalls:
        return 0.0
    recent = recalls[-5:]
    return round(sum(recent) / len(recent), 2)


def _last_accuracy(chapter: Dict[str, Any]) -> float:
    history = chapter.get("recall_history", [])
    if not history:
        return 0.0
    last = history[-1]
    if isinstance(last, dict) and "accuracy" in last:
        return float(last["accuracy"])
    return 0.0


def _chapter_bucket(chapter: Dict[str, Any]) -> str:
    next_review = _parse_date(chapter.get("next_review_date", ""))
    if not next_review:
        return "upcoming"
    if next_review < _today():
        return "overdue"
    if next_review == _today():
        return "due_today"
    return "upcoming"


def _chapter_card(chapter: Dict[str, Any]) -> None:
    st.markdown(
        f"""
**{chapter['chapter_name']}**
- Next review: {chapter.get('next_review_date', '-')}
- Interval (days): {round(float(chapter.get('interval_days', 1.0)), 2)}
- Last accuracy: {_last_accuracy(chapter)}%
- Retention score (last 5 recalls): {_retention_score(chapter)}%
"""
    )


# -----------------------------
# Streamlit App
# -----------------------------
def main() -> None:
    st.set_page_config(page_title="SSC Maths SRS", page_icon="🧠", layout="wide")
    st.title("SSC Maths Spaced Repetition Practice App")
    st.caption("Memory-first engine: spaced repetition, active recall, and mistake reinforcement.")

    if "data" not in st.session_state:
        st.session_state["data"] = load_data()

    data = st.session_state["data"]

    tabs = st.tabs([
        "Dashboard",
        "Add Chapter",
        "Generate Practice",
        "Log Practice",
        "Chapter Manager",
    ])

    # 1) Dashboard
    with tabs[0]:
        chapters = data.get("chapters", [])
        due_today = [c for c in chapters if _chapter_bucket(c) == "due_today"]
        overdue = [c for c in chapters if _chapter_bucket(c) == "overdue"]
        upcoming = [c for c in chapters if _chapter_bucket(c) == "upcoming"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Due Today", len(due_today))
        c2.metric("Overdue", len(overdue))
        c3.metric("Upcoming", len(upcoming))

        st.subheader("Due Today")
        if due_today:
            for chapter in due_today:
                _chapter_card(chapter)
                st.divider()
        else:
            st.info("No chapters due today.")

        st.subheader("Overdue")
        if overdue:
            for chapter in overdue:
                _chapter_card(chapter)
                st.divider()
        else:
            st.info("No overdue chapters.")

        st.subheader("Upcoming")
        if upcoming:
            for chapter in upcoming:
                _chapter_card(chapter)
                st.divider()
        else:
            st.info("No upcoming chapters.")

    # 2) Add Chapter
    with tabs[1]:
        with st.form("add_chapter_form"):
            name = st.text_input("Chapter name")
            total_questions = st.number_input("Total questions", min_value=1, step=1, value=50)
            question_set_size = st.number_input("Question set size", min_value=1, step=1, value=10)
            submit = st.form_submit_button("Create Chapter")

        if submit:
            ok, msg = create_chapter(data, name, int(total_questions), int(question_set_size))
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    chapter_names = [c["chapter_name"] for c in data.get("chapters", [])]

    # 3) Generate Practice
    with tabs[2]:
        if not chapter_names:
            st.info("Add a chapter first.")
        else:
            chapter_name = st.selectbox("Select chapter", chapter_names, key="gen_chapter")
            chapter = _find_chapter(data, chapter_name)
            if chapter:
                new_size = st.slider(
                    "Question set size",
                    min_value=1,
                    max_value=chapter["total_questions"],
                    value=int(chapter["question_set_size"]),
                )
                mode = st.radio("Practice mode", PRACTICE_MODES, horizontal=True)

                if st.button("Generate Question Set"):
                    chapter["question_set_size"] = int(new_size)
                    generated = generate_question_set(chapter)
                    chapter["last_generated_mode"] = mode
                    save_data(data)
                    st.success(f"Generated {len(generated)} questions for {mode}.")
                    st.write("Questions:", generated)

                if chapter.get("current_question_set"):
                    st.caption("Current generated set")
                    st.write(chapter["current_question_set"])

    # 4) Log Practice
    with tabs[3]:
        if not chapter_names:
            st.info("Add a chapter first.")
        else:
            chapter_name = st.selectbox("Chapter", chapter_names, key="log_chapter")
            chapter = _find_chapter(data, chapter_name)

            if chapter is None:
                st.warning("Chapter not found.")
            else:
                default_mode = chapter.get("last_generated_mode", "recall_practice")
                mode = st.radio("Mode", PRACTICE_MODES, index=PRACTICE_MODES.index(default_mode), horizontal=True)

                default_questions = chapter.get("current_question_set", [])
                manual_questions = st.text_input(
                    "Question numbers (comma-separated, optional if a set is already generated)",
                    value=",".join(str(q) for q in default_questions),
                )

                parsed_questions = []
                for token in manual_questions.split(","):
                    token = token.strip()
                    if not token:
                        continue
                    if token.isdigit():
                        parsed_questions.append(int(token))

                parsed_questions = _normalize_question_list(parsed_questions, chapter["total_questions"])

                incorrect = st.multiselect(
                    "Incorrect questions",
                    options=parsed_questions,
                    default=[],
                )

                if parsed_questions:
                    accuracy_preview = round(((len(parsed_questions) - len(incorrect)) / len(parsed_questions)) * 100, 2)
                    st.caption(f"Computed accuracy: {accuracy_preview}%")

                if st.button("Log Session"):
                    ok, msg, details = log_practice_session(
                        data,
                        chapter_name,
                        mode,
                        parsed_questions,
                        [int(q) for q in incorrect],
                    )
                    if ok:
                        st.success(f"{msg} Accuracy: {details['accuracy']}%")
                        st.rerun()
                    else:
                        st.error(msg)

    # 5) Chapter Manager
    with tabs[4]:
        if not chapter_names:
            st.info("No chapters yet.")
        else:
            selected = st.selectbox("Select chapter", chapter_names, key="manage_chapter")
            chapter = _find_chapter(data, selected)

            if chapter:
                st.json(
                    {
                        "chapter_name": chapter["chapter_name"],
                        "total_questions": chapter["total_questions"],
                        "next_review_date": chapter["next_review_date"],
                        "last_review_date": chapter["last_review_date"],
                        "interval_days": round(float(chapter["interval_days"]), 2),
                        "ease_factor": round(float(chapter["ease_factor"]), 3),
                        "repetition_count": chapter["repetition_count"],
                        "weak_questions_count": len(chapter["weak_questions"]),
                        "used_questions_count": len(chapter["used_question_numbers"]),
                    }
                )

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Clear Current Question Set"):
                        chapter["current_question_set"] = []
                        save_data(data)
                        st.success("Cleared current question set.")
                        st.rerun()

                with c2:
                    if st.button("Delete Chapter", type="primary"):
                        data["chapters"] = [c for c in data["chapters"] if c["chapter_name"] != selected]
                        save_data(data)
                        st.success("Chapter deleted.")
                        st.rerun()


if __name__ == "__main__":
    main()
