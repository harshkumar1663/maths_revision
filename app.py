from __future__ import annotations

import base64
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

REPO_NAME = "gk_revision_data"
DATA_PATH = "maths_data.json"
BRANCH = "main"
LOCAL_DATA_FILE = Path("maths_data.json")
PRACTICE_MODES = ["assisted_practice", "recall_practice"]


def _today() -> date:
    return date.today()


def _today_str() -> str:
    return _today().isoformat()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_question_list(values: Any, total_questions: int) -> List[int]:
    if not isinstance(values, list):
        return []
    cleaned: List[int] = []
    seen = set()
    for raw in values:
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number < 1 or number > total_questions or number in seen:
            continue
        seen.add(number)
        cleaned.append(number)
    return cleaned


def _default_data() -> Dict[str, Any]:
    return {"chapters": []}


def _safe_secrets() -> Dict[str, Any]:
    try:
        secrets_obj = st.secrets
        if hasattr(secrets_obj, "to_dict"):
            return secrets_obj.to_dict()
        return dict(secrets_obj)
    except Exception:
        return {}


def _get_github_config() -> Tuple[str, Optional[str]]:
    secrets = _safe_secrets()
    owner = str(secrets.get("GITHUB_OWNER", "harshkumar1663"))
    token = secrets.get("GITHUB_TOKEN")
    return owner, token


def _github_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
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
        "question_correct_streak": {},
    }


def _ensure_chapter_schema(chapter: Dict[str, Any]) -> None:
    name = str(chapter.get("chapter_name", "")).strip()
    legacy_sheet_total = int(chapter.get("sheet_total", 0) or 0)
    total_questions = int(chapter.get("total_questions", 0) or 0)
    if total_questions <= 1 and legacy_sheet_total > 1:
        total_questions = legacy_sheet_total
    total_questions = max(total_questions, 1)

    size = int(chapter.get("question_set_size", 10) or 10)
    defaults = _default_chapter(name, total_questions, size)
    for key, value in defaults.items():
        chapter.setdefault(key, value)

    chapter["chapter_name"] = name
    chapter["total_questions"] = total_questions
    chapter["question_set_size"] = max(1, min(int(chapter.get("question_set_size", 10)), total_questions))
    chapter["interval_days"] = max(float(chapter.get("interval_days", 1.0) or 1.0), 1.0)
    chapter["ease_factor"] = max(float(chapter.get("ease_factor", 2.5) or 2.5), 1.3)
    chapter["repetition_count"] = max(int(chapter.get("repetition_count", 0) or 0), 0)
    if not isinstance(chapter.get("recall_history"), list):
        chapter["recall_history"] = []
    chapter["weak_questions"] = _normalize_question_list(chapter.get("weak_questions", []), total_questions)
    chapter["used_question_numbers"] = _normalize_question_list(chapter.get("used_question_numbers", []), total_questions)
    chapter["current_question_set"] = _normalize_question_list(chapter.get("current_question_set", []), total_questions)

    question_last_seen = chapter.get("question_last_seen", {})
    if not isinstance(question_last_seen, dict):
        question_last_seen = {}
    normalized_seen: Dict[str, str] = {}
    for key, value in question_last_seen.items():
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= total_questions:
            normalized_seen[str(number)] = str(value)
    chapter["question_last_seen"] = normalized_seen

    if not isinstance(chapter.get("question_correct_streak"), dict):
        chapter["question_correct_streak"] = {}


def _normalize_data(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = _default_data()
    chapters = data.get("chapters", [])
    if not isinstance(chapters, list):
        chapters = []
    data["chapters"] = chapters
    for chapter in chapters:
        if isinstance(chapter, dict):
            _ensure_chapter_schema(chapter)
    return data


def _read_local_data() -> Dict[str, Any]:
    if not LOCAL_DATA_FILE.exists():
        return _default_data()
    try:
        return _normalize_data(json.loads(LOCAL_DATA_FILE.read_text(encoding="utf-8")))
    except Exception:
        return _default_data()


def _write_local_data(data: Dict[str, Any]) -> None:
    LOCAL_DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_from_github(owner: str, token: str) -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError("requests is unavailable") from exc

    url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}?ref={BRANCH}"
    response = requests.get(url, headers=_github_headers(token), timeout=20)
    if response.status_code == 404:
        return _default_data(), None
    response.raise_for_status()
    payload = response.json()
    encoded = payload.get("content", "")
    if not encoded:
        return _default_data(), payload.get("sha")
    content_text = base64.b64decode(encoded).decode("utf-8")
    return _normalize_data(json.loads(content_text)), payload.get("sha")


def _save_to_github(data: Dict[str, Any], owner: str, token: str, sha: Optional[str]) -> Optional[str]:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError("requests is unavailable") from exc

    url = f"https://api.github.com/repos/{owner}/{REPO_NAME}/contents/{DATA_PATH}"
    payload = {
        "message": f"Update {DATA_PATH}",
        "content": base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    response = requests.put(url, headers=_github_headers(token), json=payload, timeout=20)
    response.raise_for_status()
    result = response.json()
    return result.get("content", {}).get("sha")


def load_data() -> Dict[str, Any]:
    owner, token = _get_github_config()
    if token:
        try:
            data, sha = _load_from_github(owner, token)
            st.session_state["github_sha"] = sha
            st.session_state["data_source"] = "github"
            st.session_state["last_load_status"] = "Loaded from GitHub"
            st.session_state["last_load_at"] = _now_str()
            return data
        except Exception as exc:
            st.session_state["last_load_status"] = f"GitHub load failed: {exc}"
            st.session_state["data_source"] = "local-fallback"

    data = _read_local_data()
    st.session_state["last_load_status"] = "Loaded local data"
    st.session_state["last_load_at"] = _now_str()
    return data


def save_data(data: Dict[str, Any]) -> None:
    owner, token = _get_github_config()
    data = _normalize_data(data)
    if token:
        try:
            sha = st.session_state.get("github_sha")
            new_sha = _save_to_github(data, owner, token, sha)
            st.session_state["github_sha"] = new_sha
            st.session_state["data_source"] = "github"
            st.session_state["last_save_status"] = "Saved to GitHub"
            st.session_state["last_save_at"] = _now_str()
            return
        except Exception as exc:
            st.session_state["last_save_status"] = f"GitHub save failed: {exc}"
            st.session_state["data_source"] = "local-fallback"

    _write_local_data(data)
    st.session_state["last_save_status"] = "Saved locally"
    st.session_state["last_save_at"] = _now_str()


def _find_chapter(data: Dict[str, Any], chapter_name: str) -> Optional[Dict[str, Any]]:
    for chapter in data.get("chapters", []):
        if chapter.get("chapter_name", "").lower() == chapter_name.lower():
            return chapter
    return None


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
    data["chapters"].append(_default_chapter(chapter_name, total_questions, question_set_size))
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

    ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    chapter["repetition_count"] = repetition_count
    chapter["interval_days"] = interval_days
    chapter["ease_factor"] = ease_factor
    chapter["last_review_date"] = today.isoformat()
    chapter["next_review_date"] = (today + timedelta(days=max(1, int(round(interval_days))))).isoformat()
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
    seen_non_weak.sort(key=lambda q: chapter.get("question_last_seen", {}).get(str(q), "1900-01-01T00:00:00"))

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

    for q in pick_from(unseen_pool, new_target):
        selected.append(q)
        selected_set.add(q)
    for q in pick_from(list(weak), weak_target):
        selected.append(q)
        selected_set.add(q)
    for q in pick_from(seen_non_weak, old_target):
        selected.append(q)
        selected_set.add(q)
    if len(selected) < set_size:
        for q in pick_from(all_questions, set_size - len(selected)):
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
        streak_map[key] = int(streak_map.get(key, 0) or 0) + 1
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
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    chapter = _find_chapter(data, chapter_name)
    if not chapter:
        return False, "Chapter not found.", None
    if mode not in PRACTICE_MODES:
        return False, "Invalid practice mode.", None

    total = int(chapter["total_questions"])
    asked = _normalize_question_list(question_numbers, total)
    if not asked:
        return False, "No valid question numbers provided.", None

    incorrect = {q for q in _normalize_question_list(incorrect_questions, total) if q in asked}
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
        if accuracy < 60:
            tomorrow = _today() + timedelta(days=1)
            current_next = _parse_date(chapter.get("next_review_date", ""))
            if not current_next or current_next > tomorrow:
                chapter["next_review_date"] = tomorrow.isoformat()
        chapter["recall_history"].append(session_record)

    chapter["last_review_date"] = _today_str()
    chapter["current_question_set"] = []
    save_data(data)
    return True, "Session logged.", {"accuracy": round(accuracy, 2), "incorrect": sorted(incorrect)}


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


def _inject_responsive_styles(layout_mode: str) -> None:
    if layout_mode == "Compact":
        card_pad = "0.65rem"
        gap = "0.65rem"
    elif layout_mode == "Spacious":
        card_pad = "1.1rem"
        gap = "1rem"
    else:
        card_pad = "clamp(0.75rem, 1.2vw, 1rem)"
        gap = "clamp(0.75rem, 1.5vw, 1.25rem)"

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Cormorant+Garamond:wght@500;600;700&display=swap');

        :root {{
            --bg-1: #f4efe8;
            --bg-2: #eef5f1;
            --panel: rgba(255, 255, 255, 0.82);
            --panel-strong: #ffffff;
            --text: #14202b;
            --muted: #5f6b76;
            --accent: #115e59;
            --accent-2: #b45309;
            --accent-soft: rgba(17, 94, 89, 0.12);
            --border: rgba(20, 32, 43, 0.08);
            --shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
        }}

        html, body, [class*="stApp"] {{
            font-family: 'Inter', sans-serif;
            color: var(--text);
        }}

        .stApp {{
            background:
                radial-gradient(circle at 0% 0%, rgba(181, 83, 9, 0.11), transparent 34%),
                radial-gradient(circle at 100% 0%, rgba(17, 94, 89, 0.12), transparent 30%),
                linear-gradient(180deg, var(--bg-1) 0%, var(--bg-2) 100%);
            color: var(--text);
        }}

        [data-testid="stSidebar"] {{
            background: rgba(255, 255, 255, 0.74);
            border-right: 1px solid var(--border);
            backdrop-filter: blur(16px);
        }}

        h1, h2, h3, h4 {{
            font-family: 'Cormorant Garamond', serif;
            letter-spacing: 0.2px;
        }}

        h1 {{
            font-size: clamp(2.3rem, 5vw, 3.6rem) !important;
            line-height: 0.98;
            margin-bottom: 0.2rem;
        }}

        .app-shell {{
            max-width: 1240px;
            margin: 0 auto;
        }}

        .app-hero {{
            background: linear-gradient(135deg, rgba(17, 94, 89, 0.14), rgba(180, 83, 9, 0.10));
            border: 1px solid rgba(17, 94, 89, 0.12);
            border-radius: 24px;
            padding: 1.1rem 1.25rem;
            margin: 0.2rem 0 1rem 0;
            box-shadow: var(--shadow);
        }}

        .app-hero-title {{
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.22em;
            color: var(--accent);
            font-weight: 800;
            margin-bottom: 0.3rem;
        }}

        .app-hero-subtitle {{
            font-size: 1rem;
            color: var(--muted);
            max-width: 72ch;
            margin-top: 0.25rem;
        }}

        .app-panel {{
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 20px;
            box-shadow: var(--shadow);
            backdrop-filter: blur(12px);
        }}

        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.9rem;
            margin-bottom: 1rem;
        }}

        .metric-card {{
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.80));
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 1rem 1.05rem;
            box-shadow: var(--shadow);
            min-height: 108px;
        }}

        .metric-label {{
            color: var(--muted);
            font-size: 0.76rem;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-weight: 800;
        }}

        .metric-value {{
            font-size: 2.2rem;
            line-height: 1;
            margin-top: 0.35rem;
            font-weight: 800;
            color: var(--text);
        }}

        .metric-note {{
            margin-top: 0.35rem;
            color: var(--muted);
            font-size: 0.92rem;
        }}

        .section-shell {{
            margin-top: 0.8rem;
            margin-bottom: 1rem;
        }}

        .section-hero {{
            background: linear-gradient(135deg, rgba(17, 94, 89, 0.10), rgba(180, 83, 9, 0.08));
            border: 1px solid rgba(17, 94, 89, 0.12);
            border-radius: 18px;
            padding: 0.85rem 1rem;
            margin-bottom: 0.8rem;
        }}

        .section-hero-title {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.22em;
            color: var(--accent);
            font-weight: 800;
        }}

        .section-hero-sub {{
            color: var(--muted);
            margin-top: 0.2rem;
            font-size: 0.95rem;
        }}

        .chapter-card {{
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(255, 255, 255, 0.84));
            border: 1px solid var(--border);
            border-left: 4px solid var(--accent);
            border-radius: 18px;
            padding: {card_pad};
            box-shadow: var(--shadow);
            margin-bottom: {gap};
        }}

        .chapter-card h4 {{
            margin: 0 0 0.35rem 0;
            font-size: 1.35rem;
        }}

        .chapter-meta {{
            color: var(--muted);
            font-size: 0.92rem;
        }}

        .chapter-badges {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.65rem;
        }}

        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.32rem 0.62rem;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            font-size: 0.8rem;
            font-weight: 600;
        }}

        .empty-state {{
            background: rgba(255, 255, 255, 0.7);
            border: 1px dashed rgba(17, 94, 89, 0.22);
            color: var(--muted);
            border-radius: 18px;
            padding: 1rem;
        }}

        div[data-testid="stTabs"] {{
            background: rgba(255, 255, 255, 0.6);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 0.35rem 0.55rem 0.1rem 0.55rem;
            backdrop-filter: blur(14px);
        }}

        div[data-baseweb="tab-list"] {{
            gap: 0.25rem;
        }}

        button[kind="tab"] {{
            border-radius: 999px;
            font-weight: 700;
            color: var(--muted);
        }}

        button[kind="tab"][aria-selected="true"] {{
            color: var(--accent);
        }}

        button[kind="primary"] {{
            background: linear-gradient(135deg, var(--accent), #0f7c73);
            border: 0;
            color: white;
            border-radius: 12px;
            font-weight: 700;
            box-shadow: 0 12px 24px rgba(17, 94, 89, 0.24);
        }}

        @media (max-width: 700px) {{
            h1 {{
                font-size: 2rem !important;
            }}

            .metric-grid {{
                grid-template-columns: 1fr 1fr;
            }}

            .chapter-card {{
                border-radius: 14px;
                padding: 0.85rem;
            }}
        }}

        @media (max-width: 520px) {{
            .metric-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: Any, note: str) -> str:
    return (
        "<div class='metric-card'>"
        f"<div class='metric-label'>{label}</div>"
        f"<div class='metric-value'>{value}</div>"
        f"<div class='metric-note'>{note}</div>"
        "</div>"
    )


def _render_chapter_card(chapter: Dict[str, Any]) -> None:
    next_review = chapter.get('next_review_date', '-') or '-'
    interval_days = round(float(chapter.get('interval_days', 1.0)), 2)
    accuracy = _last_accuracy(chapter)
    retention = _retention_score(chapter)
    weak_count = len(chapter.get('weak_questions', []))
    current_set = len(chapter.get('current_question_set', []))
    state_label = _chapter_bucket(chapter).replace('_', ' ').title()
    card_html = f"""
    <div class='chapter-card'>
        <h4>{chapter['chapter_name']}</h4>
        <div class='chapter-meta'>Next review: {next_review} · Interval: {interval_days} days · Status: {state_label}</div>
        <div class='chapter-badges'>
            <span class='badge'>Accuracy: {accuracy}%</span>
            <span class='badge'>Retention: {retention}%</span>
            <span class='badge'>Weak: {weak_count}</span>
            <span class='badge'>Set: {current_set}</span>
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)
    st.progress(min(max(retention / 100.0, 0.0), 1.0))


def _render_dashboard(data: Dict[str, Any]) -> None:
    chapters = data.get("chapters", [])
    due_today = [c for c in chapters if _chapter_bucket(c) == "due_today"]
    overdue = [c for c in chapters if _chapter_bucket(c) == "overdue"]
    upcoming = [c for c in chapters if _chapter_bucket(c) == "upcoming"]

    total_questions = sum(int(c.get("total_questions", 0) or 0) for c in chapters)
    avg_retention = round(sum(_retention_score(c) for c in chapters) / len(chapters), 1) if chapters else 0.0

    st.markdown(
        """
        <div class='app-hero'>
            <div class='app-hero-title'>Memory-first revision cockpit</div>
            <div class='app-hero-subtitle'>Track overdue chapters, reinforce weak questions, and keep recall sessions moving without the lecture-style clutter.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_cols = st.columns(4)
    metric_cols[0].markdown(_metric_card("Total Chapters", len(chapters), "Active chapters in rotation"), unsafe_allow_html=True)
    metric_cols[1].markdown(_metric_card("Due Today", len(due_today), "Ready for recall practice"), unsafe_allow_html=True)
    metric_cols[2].markdown(_metric_card("Overdue", len(overdue), "Need immediate attention"), unsafe_allow_html=True)
    metric_cols[3].markdown(_metric_card("Avg Retention", f"{avg_retention}%", f"Across {total_questions} total questions"), unsafe_allow_html=True)

    summary_cols = st.columns(3)
    summary_cols[0].markdown(_metric_card("Upcoming", len(upcoming), "Waiting for the next interval"), unsafe_allow_html=True)
    summary_cols[1].markdown(_metric_card("Weak Questions", sum(len(c.get('weak_questions', [])) for c in chapters), "Questions marked for reinforcement"), unsafe_allow_html=True)
    summary_cols[2].markdown(_metric_card("Recent Accuracy", f"{round(sum(_last_accuracy(c) for c in chapters) / len(chapters), 1) if chapters else 0.0}%", "Last logged session average"), unsafe_allow_html=True)

    for title, items in [("Overdue", overdue), ("Due Today", due_today), ("Upcoming", upcoming)]:
        st.markdown(
            f"""
            <div class='section-hero'>
                <div class='section-hero-title'>{title}</div>
                <div class='section-hero-sub'>{len(items)} chapter(s) in this queue.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not items:
            st.markdown(f"<div class='empty-state'>No {title.lower()} chapters right now.</div>", unsafe_allow_html=True)
            continue
        for chapter in items:
            _render_chapter_card(chapter)


def _render_add_chapter_tab(data: Dict[str, Any]) -> None:
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


def _render_practice_tab(data: Dict[str, Any]) -> None:
    chapter_names = [c["chapter_name"] for c in data.get("chapters", [])]
    if not chapter_names:
        st.info("Add a chapter first.")
        return

    chapter_name = st.selectbox("Select chapter", chapter_names, key="practice_chapter")
    chapter = _find_chapter(data, chapter_name)
    if chapter is None:
        st.warning("Chapter not found.")
        return

    total_questions = max(1, int(chapter.get("total_questions", 1) or 1))
    saved_size = int(chapter.get("question_set_size", 10) or 10)
    safe_default_size = max(1, min(saved_size, total_questions))
    key_suffix = chapter_name.replace(" ", "_")

    mode = st.radio(
        "Practice mode",
        PRACTICE_MODES,
        horizontal=True,
        index=0 if chapter.get("last_generated_mode", "recall_practice") == "recall_practice" else 1,
        key=f"mode_{key_suffix}",
    )
    qsize = st.number_input(
        "Question set size",
        min_value=1,
        max_value=total_questions,
        value=safe_default_size,
        step=1,
        key=f"qsize_{key_suffix}",
    )

    gen_col, clear_col = st.columns([2, 1])
    with gen_col:
        if st.button("Generate / Refresh Set", key=f"gen_refresh_{key_suffix}"):
            chapter["question_set_size"] = int(qsize)
            generated = generate_question_set(chapter)
            chapter["last_generated_mode"] = mode
            save_data(data)
            st.success(f"Generated {len(generated)} questions for {mode}.")
            st.rerun()
    with clear_col:
        if st.button("Clear set", key=f"clearset_{key_suffix}"):
            chapter["current_question_set"] = []
            save_data(data)
            st.success("Cleared current question set.")
            st.rerun()

    current_set = _normalize_question_list(chapter.get("current_question_set", []), chapter["total_questions"])
    if not current_set:
        st.info("No question set generated. Use 'Generate / Refresh Set' to create one.")
        return

    st.caption("Current question set")
    st.write(current_set)
    incorrect = st.multiselect("Mark incorrect questions", options=current_set, default=[], key=f"incorrect_{key_suffix}")
    if st.button("Log Session", key=f"log_{key_suffix}"):
        ok, msg, details = log_practice_session(data, chapter_name, mode, current_set, [int(q) for q in incorrect])
        if ok:
            st.success(f"{msg} Accuracy: {details['accuracy']}%")
            st.rerun()
        else:
            st.error(msg)


def _render_manager_tab(data: Dict[str, Any]) -> None:
    chapter_names = [c["chapter_name"] for c in data.get("chapters", [])]
    if not chapter_names:
        st.info("No chapters yet.")
        return

    selected = st.selectbox("Select chapter", chapter_names, key="manage_chapter")
    chapter = _find_chapter(data, selected)
    if chapter is None:
        st.warning("Chapter not found.")
        return

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

    with st.expander("Edit chapter", expanded=True):
        key_suffix = selected.replace(" ", "_")
        new_name = st.text_input("Chapter name", value=chapter["chapter_name"], key=f"name_{key_suffix}")
        total_questions = st.number_input(
            "Total questions",
            min_value=1,
            step=1,
            value=int(chapter["total_questions"]),
            key=f"total_{key_suffix}",
        )
        question_set_size = st.number_input(
            "Question set size",
            min_value=1,
            step=1,
            value=int(chapter.get("question_set_size", 10)),
            max_value=int(total_questions),
            key=f"size_{key_suffix}",
        )
        default_next = _parse_date(chapter.get("next_review_date", "")) or _today()
        next_review = st.date_input("Next review date", value=default_next, key=f"next_{key_suffix}")
        interval_days = st.number_input(
            "Interval days",
            min_value=1.0,
            value=float(chapter.get("interval_days", 1.0)),
            format="%.1f",
            key=f"interval_{key_suffix}",
        )
        ease_factor = st.number_input(
            "Ease factor",
            min_value=1.0,
            value=float(chapter.get("ease_factor", 2.5)),
            format="%.2f",
            key=f"ease_{key_suffix}",
        )

        save_col, delete_col = st.columns([1, 1])
        with save_col:
            if st.button("Save changes", key=f"save_{key_suffix}"):
                if not new_name.strip():
                    st.error("Chapter name cannot be empty.")
                elif any(
                    other is not chapter and other.get("chapter_name", "").lower() == new_name.strip().lower()
                    for other in data.get("chapters", [])
                ):
                    st.error("Another chapter with that name already exists.")
                else:
                    chapter["chapter_name"] = new_name.strip()
                    chapter["total_questions"] = int(total_questions)
                    chapter["question_set_size"] = max(1, min(int(question_set_size), int(total_questions)))
                    chapter["next_review_date"] = next_review.isoformat()
                    chapter["interval_days"] = float(interval_days)
                    chapter["ease_factor"] = float(ease_factor)
                    _ensure_chapter_schema(chapter)
                    save_data(data)
                    st.success("Changes saved.")
                    st.rerun()
        with delete_col:
            if st.button("Confirm delete", key=f"confirm_del_{key_suffix}"):
                data["chapters"] = [c for c in data["chapters"] if c["chapter_name"] != chapter["chapter_name"]]
                save_data(data)
                st.success("Chapter deleted.")
                st.rerun()


def _display_sidebar_sync_status() -> None:
    owner, token = _get_github_config()
    st.sidebar.markdown("### GitHub Storage")
    st.sidebar.caption(f"Repo: {owner}/{REPO_NAME}")
    st.sidebar.caption(f"Path: {DATA_PATH} ({BRANCH})")
    st.sidebar.caption(f"Load: {st.session_state.get('last_load_status', 'Not loaded yet')}")
    st.sidebar.caption(f"Loaded at: {st.session_state.get('last_load_at', '-')}")
    st.sidebar.caption(f"Save: {st.session_state.get('last_save_status', 'No save yet')}")
    st.sidebar.caption(f"Saved at: {st.session_state.get('last_save_at', '-')}")

    if not token:
        st.sidebar.info("GITHUB_TOKEN is not configured. The app is using local file fallback.")

    if st.sidebar.button("Reload from GitHub", use_container_width=True):
        st.session_state["data"] = load_data()
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="SSC Maths SRS", page_icon="🧠", layout="wide")
    st.markdown(
        """
        <div class='app-shell'>
            <div class='app-hero'>
                <div class='app-hero-title'>SSC Maths spaced repetition</div>
                <h1>Revision that feels built for momentum.</h1>
                <div class='app-hero-subtitle'>A memory-first practice workspace with overdue tracking, weak-question reinforcement, and GitHub-backed persistence.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "data" not in st.session_state:
        st.session_state["data"] = load_data()

    st.sidebar.markdown("### View")
    layout_mode = st.sidebar.selectbox("Layout mode", ["Auto", "Compact", "Spacious"], index=0)
    _inject_responsive_styles(layout_mode)
    _display_sidebar_sync_status()

    data = st.session_state["data"]
    tabs = st.tabs(["Dashboard", "Add Chapter", "Practice", "Chapter Manager"])

    with tabs[0]:
        _render_dashboard(data)
    with tabs[1]:
        _render_add_chapter_tab(data)
    with tabs[2]:
        _render_practice_tab(data)
    with tabs[3]:
        _render_manager_tab(data)


if __name__ == "__main__":
    main()
