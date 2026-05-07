from flask import Flask, render_template, request, redirect, session, url_for, jsonify, has_request_context
from flask_mysqldb import MySQL
from datetime import datetime
import base64
import secrets
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

app = Flask(__name__)

# Secret key
app.secret_key = os.getenv("SECRET_KEY", "gmtech_dev_secret")

# MySQL configuration
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'gmtech')

mysql = MySQL(app)

PASS_PERCENTAGE = 50
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_FALLBACK_MODELS = [
    GEMINI_MODEL,
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite"
]
JUDGE0_API_KEY = os.getenv("JUDGE0_API_KEY")
JUDGE0_API_HOST = os.getenv("JUDGE0_API_HOST", "judge0-ce.p.rapidapi.com" if JUDGE0_API_KEY else "")
JUDGE0_URL = os.getenv(
    "JUDGE0_URL",
    "https://judge0-ce.p.rapidapi.com" if JUDGE0_API_KEY else "https://ce.judge0.com"
).rstrip("/")
LOCAL_CODE_RUNNER = os.getenv("LOCAL_CODE_RUNNER", "1") == "1"
LOCAL_RUN_ROOT = os.getenv("LOCAL_RUN_ROOT", os.path.join(os.getcwd(), "local_code_runs"))
JUDGE0_LANGUAGES = {
    "python": {"id": 71, "label": "Python 3"},
    "java": {"id": 62, "label": "Java"},
    "c": {"id": 50, "label": "C"},
    "cpp": {"id": 54, "label": "C++"}
}
LOCAL_RUN_LANGUAGES = {
    key: value for key, value in JUDGE0_LANGUAGES.items()
    if key in ("python", "java")
}


def ai_is_configured():
    if AI_PROVIDER == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))

    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def coding_is_configured():
    return bool(LOCAL_CODE_RUNNER or JUDGE0_API_KEY or os.getenv("JUDGE0_ALLOW_PUBLIC") == "1")


def call_openai_text(instructions, input_text, max_output_tokens=900):
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return None, "OPENAI_API_KEY is not configured."

    payload = {
        "model": OPENAI_MODEL,
        "instructions": instructions,
        "input": input_text,
        "max_output_tokens": max_output_tokens
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        return None, f"AI request failed: {exc.code} {details[:250]}"
    except Exception as exc:
        return None, f"AI request failed: {exc}"

    if body.get("output_text"):
        return body["output_text"].strip(), None

    chunks = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])

    if chunks:
        return "\n".join(chunks).strip(), None

    return None, "AI response did not include text output."


def call_gemini_text(instructions, input_text, max_output_tokens=900):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if not api_key:
        return None, "GEMINI_API_KEY is not configured."

    prompt = f"{instructions}\n\nUser request:\n{input_text}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": 0.4
        }
    }

    data = json.dumps(payload).encode("utf-8")
    last_error = None

    for model in dict.fromkeys(GEMINI_FALLBACK_MODELS):
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            last_error = f"Gemini request failed with {model}: {exc.code} {details[:250]}"
            if exc.code not in (400, 404):
                return None, last_error
        except Exception as exc:
            return None, f"Gemini request failed: {exc}"
    else:
        return None, last_error or "Gemini request failed."

    candidates = body.get("candidates", [])
    if not candidates:
        return None, "Gemini response did not include candidates."

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [part.get("text", "") for part in parts if part.get("text")]

    if text_parts:
        return "\n".join(text_parts).strip(), None

    return None, "Gemini response did not include text output."


def call_ai_text(instructions, input_text, max_output_tokens=900):
    if AI_PROVIDER == "openai":
        return call_openai_text(instructions, input_text, max_output_tokens)

    return call_gemini_text(instructions, input_text, max_output_tokens)


def active_ai_label():
    if AI_PROVIDER == "openai":
        return f"OpenAI / {OPENAI_MODEL}"

    return f"Gemini / {GEMINI_MODEL}"


def parse_ai_json(text):
    if not text:
        return None

    cleaned = text.strip()

    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min(
            [pos for pos in [cleaned.find("["), cleaned.find("{")] if pos != -1],
            default=-1
        )
        end = max(cleaned.rfind("]"), cleaned.rfind("}"))

        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None

    return None


def judge0_headers():
    headers = {"Content-Type": "application/json"}

    if JUDGE0_API_KEY:
        headers["X-RapidAPI-Key"] = JUDGE0_API_KEY

    if JUDGE0_API_HOST:
        headers["X-RapidAPI-Host"] = JUDGE0_API_HOST

    return headers


def encode_judge0_value(value):
    return base64.b64encode((value or "").encode("utf-8")).decode("ascii")


def decode_judge0_value(value):
    if not value:
        return ""

    try:
        return base64.b64decode(value).decode("utf-8", errors="replace")
    except Exception:
        return value


def run_code_with_judge0(source_code, language_id, stdin="", expected_output=None):
    payload = {
        "source_code": encode_judge0_value(source_code),
        "language_id": language_id,
        "stdin": encode_judge0_value(stdin)
    }

    if expected_output is not None:
        payload["expected_output"] = encode_judge0_value(expected_output)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{JUDGE0_URL}/submissions?base64_encoded=true&wait=true",
        data=data,
        headers=judge0_headers(),
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")

        if exc.code == 403 and "1010" in details:
            return None, (
                "Code runner setup needed: the free Judge0 public endpoint blocked this request. "
                "Restart the app with start_coding.ps1, or enter a Judge0 RapidAPI key in "
                "start_ai.ps1 so coding questions can run."
            )

        if exc.code == 401 or exc.code == 403:
            return None, (
                "Judge0 rejected the request. Check your JUDGE0_URL, JUDGE0_API_KEY, "
                "and JUDGE0_API_HOST settings."
            )

        return None, f"Judge0 request failed: {exc.code} {details[:250]}"
    except Exception as exc:
        return None, f"Judge0 request failed: {exc}"

    for field in ["stdout", "stderr", "compile_output", "message"]:
        result[field] = decode_judge0_value(result.get(field))

    return result, None


def language_key_from_id(language_id):
    for key, language in JUDGE0_LANGUAGES.items():
        if language["id"] == language_id:
            return key

    return "python"


def language_label_from_id(language_id):
    language_key = language_key_from_id(language_id)
    return JUDGE0_LANGUAGES.get(language_key, JUDGE0_LANGUAGES["python"])["label"]


def language_id_from_form(value, default_language_id=None):
    default_language_id = default_language_id or JUDGE0_LANGUAGES["python"]["id"]
    language = LOCAL_RUN_LANGUAGES.get(value)
    return language["id"] if language else default_language_id


def output_matches_expected(output, expected_output):
    actual = normalize_output(output)
    expected = normalize_output(expected_output)

    if actual == expected:
        return True

    if actual.casefold() == expected.casefold():
        return True

    actual_lines = [line.strip() for line in actual.split("\n") if line.strip()]
    if actual_lines:
        last_line = actual_lines[-1]
        if last_line.casefold() == expected.casefold():
            return True

        if ":" in last_line and last_line.rsplit(":", 1)[-1].strip().casefold() == expected.casefold():
            return True

    actual_tokens = re.findall(r"[A-Za-z0-9_.-]+", actual)
    return bool(actual_tokens and actual_tokens[-1].casefold() == expected.casefold())


def local_status(returncode, stdout="", expected_output=None):
    if returncode != 0:
        return {"description": "Runtime Error"}

    if expected_output is not None and not output_matches_expected(stdout, expected_output):
        return {"description": "Wrong Answer"}

    return {"description": "Accepted"}


def run_code_locally(source_code, language_id, stdin="", expected_output=None):
    language_key = language_key_from_id(language_id)

    if language_key not in ("python", "java"):
        return None, "Local compiler supports Python and Java only."

    os.makedirs(LOCAL_RUN_ROOT, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="gmtech_code_", dir=LOCAL_RUN_ROOT) as temp_dir:
        try:
            if language_key == "python":
                source_path = os.path.join(temp_dir, "solution.py")
                with open(source_path, "w", encoding="utf-8") as source_file:
                    source_file.write(source_code)

                completed = subprocess.run(
                    [sys.executable, source_path],
                    input=stdin or "",
                    text=True,
                    capture_output=True,
                    timeout=5
                )

                return {
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "compile_output": "",
                    "message": "",
                    "status": local_status(completed.returncode, completed.stdout, expected_output)
                }, None

            java_file = os.path.join(temp_dir, "Main.java")
            with open(java_file, "w", encoding="utf-8") as source_file:
                source_file.write(source_code)

            compile_result = subprocess.run(
                ["javac", java_file],
                text=True,
                capture_output=True,
                timeout=8
            )

            if compile_result.returncode != 0:
                return {
                    "stdout": "",
                    "stderr": "",
                    "compile_output": compile_result.stderr or compile_result.stdout,
                    "message": "",
                    "status": {"description": "Compilation Error"}
                }, None

            completed = subprocess.run(
                ["java", "-cp", temp_dir, "Main"],
                input=stdin or "",
                text=True,
                capture_output=True,
                timeout=5
            )

            return {
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "compile_output": "",
                "message": "",
                "status": local_status(completed.returncode, completed.stdout, expected_output)
            }, None
        except FileNotFoundError as exc:
            return None, f"Local compiler not found: {exc.filename}"
        except subprocess.TimeoutExpired:
            return None, "Code execution timed out."


def run_code_submission(source_code, language_id, stdin="", expected_output=None):
    if LOCAL_CODE_RUNNER:
        return run_code_locally(source_code, language_id, stdin, expected_output)

    return run_code_with_judge0(source_code, language_id, stdin, expected_output)


def normalize_output(value):
    return (value or "").replace("\r\n", "\n").strip()


def grade_coding_question(source_code, language_id, test_cases):
    passed = 0
    details = []

    for test_case in test_cases:
        result, error = run_code_submission(
            source_code=source_code,
            language_id=language_id,
            stdin=test_case["input_data"],
            expected_output=test_case["expected_output"]
        )

        if error:
            details.append({
                "input": test_case["input_data"],
                "expected": test_case["expected_output"],
                "passed": False,
                "output": "",
                "status": error
            })
            continue

        output = result.get("stdout") or ""
        accepted = output_matches_expected(output, test_case["expected_output"])
        status = result.get("status", {}).get("description", "Unknown")

        if accepted:
            passed += 1

        details.append({
            "input": test_case["input_data"],
            "expected": test_case["expected_output"],
            "passed": accepted,
            "output": output,
            "status": status
        })

    return passed, details


def normalize_ai_mcq_questions(questions):
    if isinstance(questions, dict):
        questions = questions.get("questions", [])

    if not isinstance(questions, list):
        return None

    cleaned = []
    for item in questions:
        if not isinstance(item, dict):
            continue

        question = str(item.get("question", "")).strip()
        options = [str(item.get(f"option{index}", "")).strip() for index in range(1, 5)]

        try:
            correct_option = int(item.get("correct_option"))
        except (TypeError, ValueError):
            correct_option = 0

        if question and all(options) and correct_option in (1, 2, 3, 4):
            cleaned.append({
                "question": question,
                "option1": options[0],
                "option2": options[1],
                "option3": options[2],
                "option4": options[3],
                "correct_option": correct_option
            })

    return cleaned or None


def normalize_ai_coding_questions(questions, language_key):
    if isinstance(questions, dict):
        questions = questions.get("questions", [])

    if not isinstance(questions, list):
        return None

    cleaned = []
    for item in questions:
        if not isinstance(item, dict):
            continue

        question = str(item.get("question", "")).strip()
        starter_code = str(item.get("starter_code", "")).strip()
        test_cases = []

        for test_case in item.get("test_cases", []):
            if not isinstance(test_case, dict):
                continue

            input_data = str(test_case.get("input_data", "")).strip()
            expected_output = str(test_case.get("expected_output", "")).strip()
            is_hidden = bool(test_case.get("is_hidden", False))

            if input_data or expected_output:
                test_cases.append({
                    "input_data": input_data,
                    "expected_output": expected_output,
                    "is_hidden": is_hidden
                })

        if question and starter_code and len(test_cases) >= 2:
            cleaned.append({
                "question": question,
                "language_key": language_key,
                "language_label": JUDGE0_LANGUAGES.get(language_key, JUDGE0_LANGUAGES["python"])["label"],
                "starter_code": starter_code,
                "test_cases": test_cases[:5]
            })

    return cleaned or None


def generate_ai_questions(topic, difficulty, count, question_type="mcq", language_key="python"):
    if question_type == "coding":
        language = JUDGE0_LANGUAGES.get(language_key, JUDGE0_LANGUAGES["python"])
        instructions = (
            "You create practical coding assessment questions for a technical training platform. "
            "Return only valid JSON. Use this schema: "
            "[{\"question\":\"problem statement with input/output requirements\","
            "\"starter_code\":\"...\","
            "\"test_cases\":[{\"input_data\":\"...\",\"expected_output\":\"...\",\"is_hidden\":false}]}]. "
            "Each question needs 3-5 test cases. At least one test case must be visible and at least one must be hidden. "
            "Use simple stdin/stdout programs, no external packages, and keep solutions suitable for timed assessments."
        )
        input_text = (
            f"Create {count} {difficulty} level coding questions about: {topic}. "
            f"Language: {language['label']}. Starter code must be valid for that language. "
            "For Java, use public class Main."
        )
        text, error = call_ai_text(instructions, input_text, max_output_tokens=2600)
        questions = normalize_ai_coding_questions(parse_ai_json(text), language_key)
        return questions, text, error

    instructions = (
        "You create high-quality multiple-choice assessment questions for a technical training platform. "
        "Return only valid JSON. Use this schema: "
        "[{\"question\":\"...\",\"option1\":\"...\",\"option2\":\"...\",\"option3\":\"...\",\"option4\":\"...\",\"correct_option\":1}]. "
        "Avoid duplicate questions, vague wording, and trick answers."
    )
    input_text = (
        f"Create {count} {difficulty} level MCQ questions about: {topic}. "
        "Each question must have exactly four options and one correct_option number from 1 to 4."
    )
    text, error = call_ai_text(instructions, input_text, max_output_tokens=1800)
    questions = normalize_ai_mcq_questions(parse_ai_json(text))
    return questions, text, error

def cleanup_ai_question(raw_question):
    instructions = (
        "Clean and structure messy MCQ content for an admin. Return only valid JSON with keys: "
        "question, option1, option2, option3, option4, correct_option. correct_option must be 1, 2, 3, or 4."
    )
    text, error = call_ai_text(instructions, raw_question, max_output_tokens=800)
    cleaned = parse_ai_json(text)
    return cleaned, text, error


def rule_based_result_feedback(score, total, percentage):
    if total == 0:
        return "No questions were available in this quiz, so there is no performance feedback yet."

    if percentage >= 85:
        return "Excellent performance. You have a strong grasp of this quiz area; revise lightly and move to harder practice."
    if percentage >= 60:
        return "Good progress. Review the missed concepts once, then retake a similar quiz to improve accuracy."
    return "This topic needs more practice. Revisit the basics, make short notes, and attempt a smaller practice set before retrying."


def generate_result_feedback(quiz_title, score, total, percentage):
    fallback = rule_based_result_feedback(score, total, percentage)

    if not ai_is_configured():
        return fallback

    instructions = (
        "You are a supportive assessment coach. Give concise, practical feedback in 3-4 sentences. "
        "Do not invent question-level details that were not provided."
    )
    input_text = f"Quiz: {quiz_title}\nScore: {score}/{total}\nPercentage: {percentage}%"
    text, error = call_ai_text(instructions, input_text, max_output_tokens=350)
    return text if text and not error else fallback


def rule_based_weak_topic_analysis(attempts):
    if not attempts:
        return "No attempts yet. Complete a few quizzes and this section will highlight weak areas to practice."

    weak = []
    for quiz_title, score, total in attempts:
        percentage = round((score / total) * 100, 1) if total else 0
        if percentage < 70:
            weak.append(f"{quiz_title} ({percentage}%)")

    if weak:
        return "Focus areas: " + ", ".join(weak[:4]) + ". Start with the lowest-scoring quiz and retake after revision."

    return "No major weak areas detected from recent quiz scores. Try a harder quiz or timed retake to keep improving."


def generate_weak_topic_analysis(attempts):
    fallback = rule_based_weak_topic_analysis(attempts)

    if not ai_is_configured() or not attempts:
        return fallback

    compact_attempts = [
        {
            "quiz": quiz_title,
            "score": score,
            "total": total,
            "percentage": round((score / total) * 100, 1) if total else 0
        }
        for quiz_title, score, total in attempts[:12]
    ]
    instructions = (
        "You analyze student assessment history. Identify weak topic areas from quiz titles and scores only. "
        "Return one short paragraph plus 3 bullet-style practice actions. Do not claim access to individual answers."
    )
    text, error = call_ai_text(instructions, json.dumps(compact_attempts), max_output_tokens=600)
    return text if text and not error else fallback

def get_table_columns(table_name):
    cur = mysql.connection.cursor()
    cur.execute(f"SHOW COLUMNS FROM {table_name}")
    columns = {row[0] for row in cur.fetchall()}
    cur.close()
    return columns


def has_column(table_name, column_name):
    try:
        return column_name in get_table_columns(table_name)
    except Exception:
        return False


def has_table(table_name):
    try:
        cur = mysql.connection.cursor()
        cur.execute("SHOW TABLES LIKE %s", (table_name,))
        exists = cur.fetchone() is not None
        cur.close()
        return exists
    except Exception:
        return False


def supports_coding_questions():
    return (
        has_column("questions", "question_type")
        and has_column("questions", "language_id")
        and has_column("questions", "starter_code")
        and has_table("coding_test_cases")
    )


def get_question_test_cases(question_id):
    if not has_table("coding_test_cases"):
        return []

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT input_data, expected_output, is_hidden
        FROM coding_test_cases
        WHERE question_id=%s
        ORDER BY id ASC
        """,
        (question_id,)
    )
    rows = cur.fetchall()
    cur.close()

    return [
        {
            "input_data": row[0] or "",
            "expected_output": row[1] or "",
            "is_hidden": bool(row[2])
        }
        for row in rows
    ]


def supports_answer_review():
    return has_table("result_answers")


def save_result_answer(result_id, question_id, question_type, selected_option=None, code_answer=None, is_correct=False):
    if not supports_answer_review():
        return

    cur = mysql.connection.cursor()
    cur.execute(
        """
        INSERT INTO result_answers(result_id,question_id,question_type,selected_option,code_answer,is_correct)
        VALUES(%s,%s,%s,%s,%s,%s)
        """,
        (result_id, question_id, question_type, selected_option, code_answer, 1 if is_correct else 0)
    )
    mysql.connection.commit()
    cur.close()


def ensure_anti_cheat_table():
    cur = mysql.connection.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS anti_cheat_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(255) NOT NULL,
            quiz_id INT NOT NULL,
            event_type VARCHAR(80) NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    mysql.connection.commit()
    cur.close()


def certificate_context(result_id):
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT results.username, quizzes.title, results.score, results.total, users.email
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        LEFT JOIN users ON users.name = results.username
        WHERE results.id=%s
        """,
        (result_id,)
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return None

    username, quiz_title, score, total, email = row
    percentage = round((score / total) * 100, 1) if total else 0

    return {
        "username": username,
        "quiz_title": quiz_title,
        "score": score,
        "total": total,
        "email": email,
        "percentage": percentage
    }


def certificate_url(result_id):
    if not has_request_context():
        base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
        return f"{base_url}/certificate/{result_id}"

    return url_for("certificate", result_id=result_id, _external=True)


def quiz_select_fields():
    fields = ["id", "title", "description", "time_limit"]

    if has_column("quizzes", "status"):
        fields.append("status")

    if has_column("quizzes", "max_attempts"):
        fields.append("max_attempts")

    if has_column("quizzes", "proctoring_required"):
        fields.append("proctoring_required")

    return fields


def map_row_to_dict(row, fields):
    data = {}

    for index, field in enumerate(fields):
        data[field] = row[index]

    return data


def fetch_quiz(quiz_id):
    fields = quiz_select_fields()
    cur = mysql.connection.cursor()
    cur.execute(
        f"SELECT {', '.join(fields)} FROM quizzes WHERE id=%s",
        (quiz_id,)
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return None

    quiz = map_row_to_dict(row, fields)
    quiz.setdefault("status", "active")
    quiz.setdefault("max_attempts", None)
    quiz.setdefault("proctoring_required", 0)
    return quiz


def fetch_all_quizzes():
    fields = quiz_select_fields()
    cur = mysql.connection.cursor()
    cur.execute(f"SELECT {', '.join(fields)} FROM quizzes ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()

    quizzes = []

    for row in rows:
        quiz = map_row_to_dict(row, fields)
        quiz.setdefault("status", "active")
        quiz.setdefault("max_attempts", None)
        quiz.setdefault("proctoring_required", 0)
        quizzes.append(quiz)

    return quizzes


def get_attempt_count(username, quiz_id):
    cur = mysql.connection.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM results WHERE username=%s AND quiz_id=%s",
        (username, quiz_id)
    )
    count = cur.fetchone()[0]
    cur.close()
    return count


def enrich_quizzes_for_user(quizzes, username, role):
    quiz_cards = []

    for quiz in quizzes:
        attempts_used = get_attempt_count(username, quiz["id"]) if role == "student" else 0
        max_attempts = quiz.get("max_attempts")
        can_start = (
                role == "student"
                and quiz.get("status", "active") == "active"
                and (max_attempts is None or attempts_used < max_attempts)
        )

        quiz_cards.append({
            "id": quiz["id"],
            "title": quiz["title"],
            "description": quiz.get("description") or "No description provided.",
            "time_limit": quiz["time_limit"],
            "status": quiz.get("status", "active"),
            "max_attempts": max_attempts,
            "attempts_used": attempts_used,
            "attempts_left": None if max_attempts is None else max(max_attempts - attempts_used, 0),
            "can_start": can_start
        })

    return quiz_cards


def student_profile_summary(username):
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT quizzes.title, results.score, results.total
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        WHERE results.username=%s
        ORDER BY results.id DESC
        """,
        (username,)
    )
    attempts = cur.fetchall()
    cur.close()

    total_attempts = len(attempts)
    best_score = max((row[1] for row in attempts), default=0)

    percentages = []
    for _, score, total in attempts:
        if total:
            percentages.append((score / total) * 100)

    average_percentage = round(sum(percentages) / len(percentages), 1) if percentages else 0

    return {
        "attempts": attempts,
        "total_attempts": total_attempts,
        "best_score": best_score,
        "average_percentage": average_percentage
    }


def format_issue_date():
    return datetime.now().strftime("%d %B %Y")


def student_certificates(username):
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT results.id, quizzes.title, results.score, results.total
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        WHERE results.username=%s
        ORDER BY results.id DESC
        """,
        (username,)
    )
    rows = cur.fetchall()
    cur.close()

    certificates = []

    for result_id, quiz_title, score, total in rows:
        percentage = round((score / total) * 100, 1) if total else 0

        if percentage >= PASS_PERCENTAGE:
            certificates.append({
                "result_id": result_id,
                "quiz_title": quiz_title,
                "score": score,
                "total": total,
                "percentage": percentage
            })

    return certificates


# HOME
@app.route('/')
def home():
    return render_template("index.html")


# REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():

    error = None

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        role = "student"   # 🔥 FIXED (always student)

        cur = mysql.connection.cursor()

        # Check if user already exists
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        existing_user = cur.fetchone()

        if existing_user:
            error = "Email already exists."
        else:
            cur.execute(
                "INSERT INTO users(name,email,password,role) VALUES(%s,%s,%s,%s)",
                (name, email, password, role)
            )
            mysql.connection.commit()
            cur.close()

            return redirect('/login')

        cur.close()

    return render_template("register.html", error=error)

# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():

    error = None

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT id, name, role FROM users WHERE email=%s AND password=%s",
            (email, password)
        )

        user = cur.fetchone()
        cur.close()

        if user:
            session['user_id'] = user[0]
            session['user'] = user[1]
            session['role'] = (user[2] or "student").strip().lower()

            return redirect('/dashboard')
        else:
            error = "Invalid email or password"

    return render_template("login.html", error=error)


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    message = None
    error = None
    reset_link = None

    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        user = cur.fetchone()

        if user:
            token = secrets.token_urlsafe(24)
            expires_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if has_table("password_reset_tokens"):
                cur.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", (user[0],))
                cur.execute(
                    """
                    INSERT INTO password_reset_tokens(user_id,token,expires_at)
                    VALUES(%s,%s,DATE_ADD(%s, INTERVAL 30 MINUTE))
                    """,
                    (user[0], token, expires_at)
                )
                mysql.connection.commit()
                reset_link = url_for('reset_password', token=token, _external=True)
                message = "Reset link generated. Use it within 30 minutes."
            else:
                error = "Password reset table is missing. Run database/password_features.sql first."
        else:
            message = "If that email exists, a reset link can be generated."

        cur.close()

    return render_template(
        "forgot_password.html",
        message=message,
        error=error,
        reset_link=reset_link
    )


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if not has_table("password_reset_tokens"):
        return render_template(
            "reset_password.html",
            error="Password reset table is missing. Run database/password_features.sql first.",
            token=token
        )

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT user_id
        FROM password_reset_tokens
        WHERE token=%s AND expires_at > NOW()
        """,
        (token,)
    )
    reset_row = cur.fetchone()

    if not reset_row:
        cur.close()
        return render_template(
            "reset_password.html",
            error="This reset link is invalid or expired.",
            token=token
        )

    message = None
    error = None

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            cur.execute("UPDATE users SET password=%s WHERE id=%s", (password, reset_row[0]))
            cur.execute("DELETE FROM password_reset_tokens WHERE token=%s", (token,))
            mysql.connection.commit()
            message = "Password updated. You can login now."

    cur.close()

    return render_template(
        "reset_password.html",
        token=token,
        message=message,
        error=error
    )


@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect('/login')

    message = None
    error = None

    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        cur = mysql.connection.cursor()
        cur.execute("SELECT password FROM users WHERE id=%s", (session['user_id'],))
        user = cur.fetchone()

        if not user or user[0] != current_password:
            error = "Current password is incorrect."
        elif len(new_password) < 6:
            error = "New password must be at least 6 characters."
        elif new_password != confirm_password:
            error = "New passwords do not match."
        else:
            cur.execute("UPDATE users SET password=%s WHERE id=%s", (new_password, session['user_id']))
            mysql.connection.commit()
            message = "Password changed successfully."

        cur.close()

    return render_template(
        "change_password.html",
        message=message,
        error=error
    )

# DASHBOARD
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect('/login')

    quizzes = enrich_quizzes_for_user(
        fetch_all_quizzes(),
        session['user'],
        session['role']
    )
    profile = student_profile_summary(session['user']) if session['role'] == 'student' else None
    certificates = student_certificates(session['user']) if session['role'] == 'student' else []

    return render_template(
        "dashboard.html",
        user=session['user'],
        role=session['role'],
        quizzes=quizzes,
        profile=profile,
        certificates=certificates
    )


# CREATE QUIZ (ADMIN ONLY)
@app.route('/create_quiz', methods=['GET', 'POST'])
def create_quiz():
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    supports_max_attempts = has_column("quizzes", "max_attempts")
    supports_proctoring = has_column("quizzes", "proctoring_required")

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        time_limit = request.form['time_limit']
        status = request.form.get('status', 'active')

        columns = ["title", "description", "time_limit", "status"]
        values = [title, description, time_limit, status]

        if supports_max_attempts:
            columns.append("max_attempts")
            values.append(request.form.get('max_attempts', '1'))

        if supports_proctoring:
            columns.append("proctoring_required")
            values.append(1 if request.form.get('proctoring_required') else 0)

        cur = mysql.connection.cursor()
        placeholders = ",".join(["%s"] * len(values))
        cur.execute(
            f"INSERT INTO quizzes ({','.join(columns)}) VALUES({placeholders})",
            tuple(values)
        )
        mysql.connection.commit()
        cur.close()

        return redirect('/dashboard')

    return render_template(
        "create_quiz.html",
        supports_max_attempts=supports_max_attempts,
        supports_proctoring=supports_proctoring
    )


# EDIT QUIZ (ADMIN ONLY)
@app.route('/edit_quiz/<int:quiz_id>', methods=['GET', 'POST'])
def edit_quiz(quiz_id):
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    quiz = fetch_quiz(quiz_id)

    if not quiz:
        return redirect('/dashboard')

    supports_max_attempts = has_column("quizzes", "max_attempts")
    supports_proctoring = has_column("quizzes", "proctoring_required")

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        time_limit = request.form['time_limit']
        status = request.form.get('status', 'active')

        updates = ["title=%s", "description=%s", "time_limit=%s", "status=%s"]
        values = [title, description, time_limit, status]

        if supports_max_attempts:
            updates.append("max_attempts=%s")
            values.append(request.form.get('max_attempts', '1'))

        if supports_proctoring:
            updates.append("proctoring_required=%s")
            values.append(1 if request.form.get('proctoring_required') else 0)

        values.append(quiz_id)

        cur = mysql.connection.cursor()
        cur.execute(
            f"UPDATE quizzes SET {', '.join(updates)} WHERE id=%s",
            tuple(values)
        )
        mysql.connection.commit()
        cur.close()

        return redirect('/dashboard')

    return render_template(
        "edit_quiz.html",
        quiz=quiz,
        supports_max_attempts=supports_max_attempts,
        supports_proctoring=supports_proctoring
    )


# ADD QUESTION (ADMIN ONLY)
@app.route('/add_question', methods=['GET', 'POST'])
def add_question():
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()
    cur.execute("SELECT id,title FROM quizzes ORDER BY id DESC")
    quizzes = cur.fetchall()
    cleaned_question = None
    ai_error = None
    raw_question = ""
    coding_supported = supports_coding_questions()

    if request.method == 'POST':
        if request.form.get("action") == "cleanup":
            raw_question = request.form.get("raw_question", "").strip()

            if raw_question:
                cleaned_question, _, ai_error = cleanup_ai_question(raw_question)
            else:
                ai_error = "Paste a rough question before using AI cleanup."

            cur.close()
            return render_template(
                "add_question.html",
                quizzes=quizzes,
                cleaned_question=cleaned_question,
                ai_error=ai_error,
                raw_question=raw_question,
                ai_configured=ai_is_configured(),
                coding_supported=coding_supported,
                languages=JUDGE0_LANGUAGES
            )

        if request.form.get("action") == "save_bulk_mcq":
            quiz_id = request.form.get("quiz_id")
            question_count = int(request.form.get("question_count", 1))
            saved_count = 0

            for index in range(1, question_count + 1):
                question = request.form.get(f"question_{index}", "").strip()
                option1 = request.form.get(f"option1_{index}", "").strip()
                option2 = request.form.get(f"option2_{index}", "").strip()
                option3 = request.form.get(f"option3_{index}", "").strip()
                option4 = request.form.get(f"option4_{index}", "").strip()
                correct_option = request.form.get(f"correct_option_{index}", "").strip()

                if not all([question, option1, option2, option3, option4, correct_option]):
                    continue

                if coding_supported:
                    cur.execute(
                        """
                        INSERT INTO questions
                        (quiz_id,question,option1,option2,option3,option4,correct_option,question_type)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (quiz_id, question, option1, option2, option3, option4, correct_option, "mcq")
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO questions
                        (quiz_id,question,option1,option2,option3,option4,correct_option)
                        VALUES(%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (quiz_id, question, option1, option2, option3, option4, correct_option)
                    )
                saved_count += 1

            mysql.connection.commit()
            cur.close()
            if saved_count:
                return redirect('/dashboard')

            return render_template(
                "add_question.html",
                quizzes=quizzes,
                cleaned_question=cleaned_question,
                ai_error="Add at least one complete MCQ before saving.",
                raw_question=raw_question,
                ai_configured=ai_is_configured(),
                coding_supported=coding_supported,
                languages=JUDGE0_LANGUAGES
            )

        quiz_id = request.form['quiz_id']
        question_type = request.form.get("question_type", "mcq")
        question = request.form['question']

        if question_type == "coding" and coding_supported:
            language_key = request.form.get("language_key", "python")
            language_id = JUDGE0_LANGUAGES.get(language_key, JUDGE0_LANGUAGES["python"])["id"]
            starter_code = request.form.get("starter_code", "")

            cur.execute(
                """
                INSERT INTO questions
                (quiz_id,question,option1,option2,option3,option4,correct_option,question_type,language_id,starter_code)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (quiz_id, question, "", "", "", "", 1, "coding", language_id, starter_code)
            )
            question_id = cur.lastrowid

            for index in range(1, 6):
                input_data = request.form.get(f"test_input_{index}", "").strip()
                expected_output = request.form.get(f"test_output_{index}", "").strip()
                is_hidden = 1 if request.form.get(f"test_hidden_{index}") else 0

                if input_data or expected_output:
                    cur.execute(
                        """
                        INSERT INTO coding_test_cases(question_id,input_data,expected_output,is_hidden)
                        VALUES(%s,%s,%s,%s)
                        """,
                        (question_id, input_data, expected_output, is_hidden)
                    )
        else:
            option1 = request.form['option1']
            option2 = request.form['option2']
            option3 = request.form['option3']
            option4 = request.form['option4']
            correct_option = request.form['correct_option']

            if coding_supported:
                cur.execute(
                    """
                    INSERT INTO questions
                    (quiz_id,question,option1,option2,option3,option4,correct_option,question_type)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (quiz_id, question, option1, option2, option3, option4, correct_option, "mcq")
                )
            else:
                cur.execute(
                    """
                    INSERT INTO questions
                    (quiz_id,question,option1,option2,option3,option4,correct_option)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (quiz_id, question, option1, option2, option3, option4, correct_option)
                )

        mysql.connection.commit()
        cur.close()
        return redirect('/dashboard')

    cur.close()
    return render_template(
        "add_question.html",
        quizzes=quizzes,
        cleaned_question=cleaned_question,
        ai_error=ai_error,
        raw_question=raw_question,
        ai_configured=ai_is_configured(),
        coding_supported=coding_supported,
        languages=JUDGE0_LANGUAGES
    )


# MANAGE QUESTIONS (ADMIN ONLY)
@app.route('/manage_questions/<int:quiz_id>')
def manage_questions(quiz_id):
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    coding_supported = supports_coding_questions()
    cur = mysql.connection.cursor()
    cur.execute("SELECT title FROM quizzes WHERE id=%s", (quiz_id,))
    quiz = cur.fetchone()

    if coding_supported:
        cur.execute(
            """
            SELECT id, question, option1, option2, option3, option4, correct_option, question_type
            FROM questions
            WHERE quiz_id=%s
            ORDER BY id DESC
            """,
            (quiz_id,)
        )
    else:
        cur.execute(
            """
            SELECT id, question, option1, option2, option3, option4, correct_option
            FROM questions
            WHERE quiz_id=%s
            ORDER BY id DESC
            """,
            (quiz_id,)
        )
    questions = cur.fetchall()
    cur.close()

    if not quiz:
        return redirect('/dashboard')

    return render_template(
        "manage_questions.html",
        quiz_id=quiz_id,
        quiz_title=quiz[0],
        questions=questions,
        coding_supported=coding_supported
    )


# EDIT QUESTION (ADMIN ONLY)
@app.route('/edit_question/<int:question_id>', methods=['GET', 'POST'])
def edit_question(question_id):
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT id, quiz_id, question, option1, option2, option3, option4, correct_option
        FROM questions
        WHERE id=%s
        """,
        (question_id,)
    )
    question = cur.fetchone()

    if not question:
        cur.close()
        return redirect('/dashboard')

    if request.method == 'POST':
        cur.execute(
            """
            UPDATE questions
            SET question=%s, option1=%s, option2=%s, option3=%s, option4=%s, correct_option=%s
            WHERE id=%s
            """,
            (
                request.form['question'],
                request.form['option1'],
                request.form['option2'],
                request.form['option3'],
                request.form['option4'],
                request.form['correct_option'],
                question_id
            )
        )
        mysql.connection.commit()
        quiz_id = question[1]
        cur.close()
        return redirect(url_for('manage_questions', quiz_id=quiz_id))

    cur.close()
    return render_template("edit_question.html", question=question)


# DELETE QUESTION (ADMIN ONLY)
@app.route('/delete_question/<int:question_id>')
def delete_question(question_id):
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()
    cur.execute("SELECT quiz_id FROM questions WHERE id=%s", (question_id,))
    question = cur.fetchone()

    if not question:
        cur.close()
        return redirect('/dashboard')

    quiz_id = question[0]
    cur.execute("DELETE FROM questions WHERE id=%s", (question_id,))
    mysql.connection.commit()
    cur.close()

    return redirect(url_for('manage_questions', quiz_id=quiz_id))


# START QUIZ
@app.route('/start_quiz/<int:quiz_id>')
def start_quiz(quiz_id):
    if 'user' not in session:
        return redirect('/login')

    if session['role'] != 'student':
        return redirect('/dashboard')

    quiz = fetch_quiz(quiz_id)

    if not quiz:
        return redirect('/dashboard')

    if quiz.get("status", "active") != "active":
        return render_template(
            "quiz_unavailable.html",
            message=f"This quiz is currently {quiz.get('status', 'unavailable')}.",
            back_url='/dashboard'
        )

    max_attempts = quiz.get("max_attempts")
    attempts_used = get_attempt_count(session['user'], quiz_id)

    if max_attempts is not None and attempts_used >= max_attempts:
        return render_template(
            "quiz_unavailable.html",
            message="You have reached the maximum number of attempts for this quiz.",
            back_url='/dashboard'
        )

    cur = mysql.connection.cursor()
    coding_supported = supports_coding_questions()

    if coding_supported:
        cur.execute(
            """
            SELECT id, quiz_id, question, option1, option2, option3, option4, correct_option,
                   question_type, language_id, starter_code
            FROM questions
            WHERE quiz_id=%s
            ORDER BY RAND()
            """,
            (quiz_id,)
        )
    else:
        cur.execute(
            """
            SELECT * FROM questions
            WHERE quiz_id=%s
            ORDER BY RAND()
            """,
            (quiz_id,)
        )
    questions = cur.fetchall()
    cur.close()

    processed_questions = []

    for q in questions:
        question_type = q[8] if coding_supported and len(q) > 8 and q[8] else "mcq"

        if question_type == "coding":
            language_id = q[9] or JUDGE0_LANGUAGES["python"]["id"]
            visible_test_cases = [
                test_case for test_case in get_question_test_cases(q[0])
                if not test_case["is_hidden"]
            ]
            processed_questions.append({
                "id": q[0],
                "question": q[2],
                "question_type": "coding",
                "language_id": language_id,
                "language_key": language_key_from_id(language_id),
                "language_label": language_label_from_id(language_id),
                "language_options": LOCAL_RUN_LANGUAGES,
                "starter_code": q[10] or "",
                "visible_test_cases": visible_test_cases,
                "options": []
            })
            continue

        options = [(1, q[3]), (2, q[4]), (3, q[5]), (4, q[6])]

        random.shuffle(options)
        processed_questions.append({
            "id": q[0],
            "question": q[2],
            "question_type": "mcq",
            "options": options
        })

    return render_template(
        "quiz.html",
        questions=processed_questions,
        quiz_id=quiz_id,
        quiz_title=quiz["title"],
        time_limit=quiz["time_limit"] * 60,
        coding_enabled=coding_supported and coding_is_configured(),
        proctoring_required=bool(quiz.get("proctoring_required"))
    )


# SUBMIT QUIZ
@app.route('/submit_quiz/<int:quiz_id>', methods=['POST'])
def submit_quiz(quiz_id):
    if 'user' not in session:
        return redirect('/login')

    if session['role'] != 'student':
        return redirect('/dashboard')

    quiz = fetch_quiz(quiz_id)

    if not quiz:
        return redirect('/dashboard')

    max_attempts = quiz.get("max_attempts")
    username = session['user']

    if max_attempts is not None and get_attempt_count(username, quiz_id) >= max_attempts:
        return render_template(
            "quiz_unavailable.html",
            message="Attempt limit reached. This submission was not accepted.",
            back_url='/dashboard'
        )

    cur = mysql.connection.cursor()
    coding_supported = supports_coding_questions()

    if coding_supported:
        cur.execute(
            """
            SELECT id, quiz_id, question, option1, option2, option3, option4, correct_option,
                   question_type, language_id, starter_code
            FROM questions
            WHERE quiz_id=%s
            """,
            (quiz_id,)
        )
    else:
        cur.execute("SELECT * FROM questions WHERE quiz_id=%s", (quiz_id,))
    questions = cur.fetchall()

    score = 0
    total = len(questions)

    for q in questions:
        question_id = q[0]
        question_type = q[8] if coding_supported and len(q) > 8 and q[8] else "mcq"

        if question_type == "coding":
            source_code = request.form.get(f"code_q{question_id}", "")
            language_id = language_id_from_form(
                request.form.get(f"language_q{question_id}", ""),
                q[9] or JUDGE0_LANGUAGES["python"]["id"]
            )
            test_cases = get_question_test_cases(question_id)

            if coding_is_configured() and source_code.strip() and test_cases:
                passed, _ = grade_coding_question(
                    source_code=source_code,
                    language_id=language_id,
                    test_cases=test_cases
                )

                if passed == len(test_cases):
                    score += 1

            continue

        correct_answer = q[7]
        user_answer = request.form.get(f"q{question_id}")

        if user_answer and int(user_answer) == correct_answer:
            score += 1

    cur.execute(
        "INSERT INTO results(username,quiz_id,score,total) VALUES(%s,%s,%s,%s)",
        (username, quiz_id, score, total)
    )
    mysql.connection.commit()
    result_id = cur.lastrowid

    if supports_answer_review():
        for q in questions:
            question_id = q[0]
            question_type = q[8] if coding_supported and len(q) > 8 and q[8] else "mcq"

            if question_type == "coding":
                source_code = request.form.get(f"code_q{question_id}", "")
                language_id = language_id_from_form(
                    request.form.get(f"language_q{question_id}", ""),
                    q[9] or JUDGE0_LANGUAGES["python"]["id"]
                )
                test_cases = get_question_test_cases(question_id)
                is_correct = False

                if coding_is_configured() and source_code.strip() and test_cases:
                    passed, _ = grade_coding_question(
                        source_code=source_code,
                        language_id=language_id,
                        test_cases=test_cases
                    )
                    is_correct = passed == len(test_cases)

                save_result_answer(
                    result_id=result_id,
                    question_id=question_id,
                    question_type="coding",
                    code_answer=source_code,
                    is_correct=is_correct
                )
                continue

            user_answer = request.form.get(f"q{question_id}")
            correct_answer = q[7]
            is_correct = bool(user_answer and int(user_answer) == correct_answer)
            save_result_answer(
                result_id=result_id,
                question_id=question_id,
                question_type="mcq",
                selected_option=user_answer,
                is_correct=is_correct
            )

    cur.execute(
        """
        SELECT username, score
        FROM results
        WHERE quiz_id=%s
        ORDER BY score DESC, id ASC
        """,
        (quiz_id,)
    )
    leaderboard = cur.fetchall()
    cur.close()

    rank = 1
    for result in leaderboard:
        if result[0] == username:
            break
        rank += 1

    percentage = round((score / total) * 100, 1) if total else 0
    certificate_available = percentage >= PASS_PERCENTAGE
    ai_feedback = generate_result_feedback(quiz["title"], score, total, percentage)

    return render_template(
        "result.html",
        score=score,
        total=total,
        rank=rank,
        participants=len(leaderboard),
        percentage=percentage,
        certificate_available=certificate_available,
        result_id=result_id,
        review_available=supports_answer_review(),
        ai_feedback=ai_feedback
    )


# LEADERBOARD
@app.route('/leaderboard/<int:quiz_id>')
def leaderboard(quiz_id):
    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT username, score, total
        FROM results
        WHERE quiz_id=%s
        ORDER BY score DESC, id ASC
        """,
        (quiz_id,)
    )
    results = cur.fetchall()

    cur.execute("SELECT title FROM quizzes WHERE id=%s", (quiz_id,))
    quiz = cur.fetchone()
    cur.close()

    if not quiz:
        return redirect('/dashboard')

    return render_template(
        "leaderboard.html",
        results=results,
        quiz_title=quiz[0]
    )


# HISTORY
@app.route('/history')
def history():
    if 'user' not in session:
        return redirect('/login')

    username = session['user']

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT results.id, quizzes.title, results.score, results.total
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        WHERE results.username=%s
        ORDER BY results.id DESC
        """,
        (username,)
    )
    history_rows = cur.fetchall()
    cur.close()

    passed_attempts = sum(
        1 for row in history_rows
        if row[3] and round((row[2] / row[3]) * 100, 1) >= PASS_PERCENTAGE
    )
    best_percentage = max(
        (round((row[2] / row[3]) * 100, 1) for row in history_rows if row[3]),
        default=0
    )

    return render_template(
        "history.html",
        history=history_rows,
        passed_attempts=passed_attempts,
        best_percentage=best_percentage,
        pass_percentage=PASS_PERCENTAGE
    )


# STUDENT PROFILE
@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect('/login')

    if session['role'] != 'student':
        return redirect('/dashboard')

    summary = student_profile_summary(session['user'])
    weak_topic_analysis = generate_weak_topic_analysis(summary["attempts"])

    return render_template(
        "profile.html",
        user=session['user'],
        summary=summary,
        weak_topic_analysis=weak_topic_analysis
    )


@app.route('/certificates')
def certificates():
    if 'user' not in session:
        return redirect('/login')

    if session['role'] != 'student':
        return redirect('/dashboard')

    return render_template(
        "certificates.html",
        user=session['user'],
        certificates=student_certificates(session['user'])
    )


@app.route('/certificate/<int:result_id>')
def certificate(result_id):
    certificate_data = certificate_context(result_id)

    if not certificate_data:
        return "Certificate not found"

    if certificate_data["percentage"] < PASS_PERCENTAGE:
        return "Certificate not available (not passed)"

    return render_template(
        "certificate.html",
        username=certificate_data["username"],
        quiz_title=certificate_data["quiz_title"],
        issue_date=format_issue_date(),
        result_id=result_id,
    )


@app.route('/review/<int:result_id>')
def review_result(result_id):
    if 'user' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT results.id, results.username, results.quiz_id, results.score, results.total, quizzes.title
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        WHERE results.id=%s
        """,
        (result_id,)
    )
    result = cur.fetchone()

    if not result:
        cur.close()
        return redirect('/dashboard')

    if session['role'] != 'admin' and result[1] != session['user']:
        cur.close()
        return redirect('/dashboard')

    if not supports_answer_review():
        cur.close()
        return render_template(
            "review.html",
            result=result,
            answers=[],
            review_available=False
        )

    cur.execute(
        """
        SELECT questions.id, questions.question, questions.option1, questions.option2,
               questions.option3, questions.option4, questions.correct_option,
               result_answers.question_type, result_answers.selected_option,
               result_answers.code_answer, result_answers.is_correct
        FROM result_answers
        JOIN questions ON result_answers.question_id = questions.id
        WHERE result_answers.result_id=%s
        ORDER BY result_answers.id ASC
        """,
        (result_id,)
    )
    rows = cur.fetchall()
    cur.close()

    answers = []
    for row in rows:
        options = {
            1: row[2],
            2: row[3],
            3: row[4],
            4: row[5]
        }
        selected_option = int(row[8]) if row[8] else None
        correct_option = row[6]

        answers.append({
            "question": row[1],
            "options": options,
            "correct_option": correct_option,
            "selected_option": selected_option,
            "selected_text": options.get(selected_option),
            "correct_text": options.get(correct_option),
            "question_type": row[7],
            "code_answer": row[9],
            "is_correct": bool(row[10])
        })

    return render_template(
        "review.html",
        result=result,
        answers=answers,
        review_available=True
    )


# ANALYTICS
@app.route('/analytics')
def analytics():
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM quizzes")
    quizzes = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM results")
    attempts = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM questions")
    total_questions = cur.fetchone()[0]

    cur.execute("SELECT role, COUNT(*) FROM users GROUP BY role")
    role_counts = {row[0]: row[1] for row in cur.fetchall()}
    admins = role_counts.get("admin", 0)
    students = role_counts.get("student", 0)

    cur.execute(
        """
        SELECT
            COALESCE(ROUND(AVG(CASE WHEN total > 0 THEN (score / total) * 100 ELSE 0 END), 1), 0),
            COALESCE(SUM(CASE WHEN total > 0 AND (score / total) * 100 >= %s THEN 1 ELSE 0 END), 0)
        FROM results
        """,
        (PASS_PERCENTAGE,)
    )
    average_score, passed_attempts = cur.fetchone()
    average_score = float(average_score or 0)
    passed_attempts = int(passed_attempts or 0)
    pass_rate = round((passed_attempts / attempts) * 100, 1) if attempts else 0

    cur.execute(
        """
        SELECT
            SUM(CASE WHEN total > 0 AND (score / total) * 100 < 40 THEN 1 ELSE 0 END),
            SUM(CASE WHEN total > 0 AND (score / total) * 100 >= 40 AND (score / total) * 100 < 70 THEN 1 ELSE 0 END),
            SUM(CASE WHEN total > 0 AND (score / total) * 100 >= 70 THEN 1 ELSE 0 END)
        FROM results
        """
    )
    score_distribution = [int(value or 0) for value in cur.fetchone()]

    cur.execute(
        """
        SELECT quizzes.title, COUNT(results.id), COALESCE(ROUND(AVG(CASE WHEN results.total > 0 THEN (results.score / results.total) * 100 ELSE 0 END), 1), 0)
        FROM quizzes
        LEFT JOIN results ON results.quiz_id = quizzes.id
        GROUP BY quizzes.id, quizzes.title
        ORDER BY COUNT(results.id) DESC, quizzes.id DESC
        LIMIT 6
        """
    )
    quiz_performance = cur.fetchall()

    cur.execute(
        """
        SELECT results.username, quizzes.title, results.score, results.total
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        ORDER BY results.id DESC
        LIMIT 8
        """
    )
    recent_attempts = cur.fetchall()

    if supports_coding_questions():
        cur.execute(
            """
            SELECT COALESCE(question_type, 'mcq'), COUNT(*)
            FROM questions
            GROUP BY COALESCE(question_type, 'mcq')
            """
        )
        question_type_counts = {row[0]: row[1] for row in cur.fetchall()}
    else:
        question_type_counts = {"mcq": total_questions}

    anti_cheat_events = 0
    if has_table("anti_cheat_logs"):
        cur.execute("SELECT COUNT(*) FROM anti_cheat_logs")
        anti_cheat_events = cur.fetchone()[0]

    cur.close()

    chart_payload = {
        "overview": [users, quizzes, attempts, total_questions],
        "score_distribution": score_distribution,
        "quiz_labels": [row[0] for row in quiz_performance],
        "quiz_attempts": [row[1] for row in quiz_performance],
        "quiz_averages": [float(row[2] or 0) for row in quiz_performance],
        "question_type_labels": list(question_type_counts.keys()),
        "question_type_values": list(question_type_counts.values())
    }

    return render_template(
        "analytics.html",
        users=users,
        quizzes=quizzes,
        attempts=attempts,
        total_questions=total_questions,
        admins=admins,
        students=students,
        average_score=average_score,
        pass_rate=pass_rate,
        passed_attempts=passed_attempts,
        anti_cheat_events=anti_cheat_events,
        quiz_performance=quiz_performance,
        recent_attempts=recent_attempts,
        question_type_counts=question_type_counts,
        chart_payload=json.dumps(chart_payload)
    )


@app.route('/ai_tools', methods=['GET', 'POST'])
def ai_tools():
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    generated_questions = None
    cleaned_question = None
    raw_ai_output = None
    ai_error = None
    form_data = {
        "topic": "",
        "difficulty": "Intermediate",
        "count": 5,
        "question_type": "mcq",
        "language_key": "python",
        "raw_question": ""
    }

    if request.method == 'POST':
        action = request.form.get("action")

        if action == "generate":
            topic = request.form.get("topic", "").strip()
            difficulty = request.form.get("difficulty", "Intermediate")
            count = min(max(int(request.form.get("count", 5)), 1), 50)
            question_type = request.form.get("question_type", "mcq")
            language_key = request.form.get("language_key", "python")

            if question_type not in ("mcq", "coding"):
                question_type = "mcq"
            if language_key not in JUDGE0_LANGUAGES:
                language_key = "python"

            form_data.update({
                "topic": topic,
                "difficulty": difficulty,
                "count": count,
                "question_type": question_type,
                "language_key": language_key
            })

            if topic:
                generated_questions, raw_ai_output, ai_error = generate_ai_questions(
                    topic,
                    difficulty,
                    count,
                    question_type=question_type,
                    language_key=language_key
                )
                if not generated_questions and not ai_error:
                    ai_error = "AI returned text, but it could not be parsed into structured questions."
            else:
                ai_error = "Enter a topic before generating questions."

        if action == "cleanup":
            raw_question = request.form.get("raw_question", "").strip()
            form_data["raw_question"] = raw_question

            if raw_question:
                cleaned_question, raw_ai_output, ai_error = cleanup_ai_question(raw_question)
                if not cleaned_question and not ai_error:
                    ai_error = "AI returned text, but it could not be parsed into one clean question."
            else:
                ai_error = "Paste rough question text before cleanup."

    return render_template(
        "ai_tools.html",
        ai_configured=ai_is_configured(),
        model=active_ai_label(),
        generated_questions=generated_questions,
        cleaned_question=cleaned_question,
        raw_ai_output=raw_ai_output,
        ai_error=ai_error,
        form_data=form_data,
        languages=JUDGE0_LANGUAGES
    )


@app.route('/delete_quiz/<int:quiz_id>')
def delete_quiz(quiz_id):
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM questions WHERE quiz_id=%s", (quiz_id,))
    cur.execute("DELETE FROM quizzes WHERE id=%s", (quiz_id,))
    mysql.connection.commit()
    cur.close()

    return redirect('/dashboard')


@app.route('/admin_results')
def admin_results():
    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    selected_quiz = request.args.get("quiz", "all")
    selected_status = request.args.get("status", "all")
    search_query = request.args.get("q", "").strip()

    ensure_anti_cheat_table()
    cur = mysql.connection.cursor()

    filters = []
    params = []

    if selected_quiz != "all":
        filters.append("results.quiz_id=%s")
        params.append(selected_quiz)

    if selected_status == "pass":
        filters.append("results.total > 0 AND (results.score / results.total) * 100 >= %s")
        params.append(PASS_PERCENTAGE)
    elif selected_status == "fail":
        filters.append("results.total = 0 OR (results.score / results.total) * 100 < %s")
        params.append(PASS_PERCENTAGE)

    if search_query:
        filters.append("(results.username LIKE %s OR users.email LIKE %s OR quizzes.title LIKE %s)")
        like_query = f"%{search_query}%"
        params.extend([like_query, like_query, like_query])

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""

    cur.execute("SELECT id, title FROM quizzes ORDER BY title ASC")
    quiz_options = cur.fetchall()

    cur.execute(
        f"""
        SELECT results.id, results.username, quizzes.title, results.score, results.total,
               users.email, results.quiz_id,
               CASE WHEN results.total > 0 THEN ROUND((results.score / results.total) * 100, 1) ELSE 0 END AS percentage
        FROM results
        JOIN quizzes ON results.quiz_id = quizzes.id
        LEFT JOIN users ON users.name = results.username
        {where_clause}
        ORDER BY results.id DESC
        """,
        tuple(params)
    )
    rows = cur.fetchall()

    cur.execute(
        """
        SELECT quiz_id, username, COUNT(*)
        FROM anti_cheat_logs
        GROUP BY quiz_id, username
        """
    )
    anti_cheat_counts = {
        f"{row[0]}:{row[1]}": row[2]
        for row in cur.fetchall()
    }

    data = []
    for row in rows:
        log_count = anti_cheat_counts.get(f"{row[6]}:{row[1]}", 0)
        data.append({
            "id": row[0],
            "username": row[1],
            "quiz_title": row[2],
            "score": row[3],
            "total": row[4],
            "email": row[5] or "No email",
            "quiz_id": row[6],
            "percentage": float(row[7] or 0),
            "passed": float(row[7] or 0) >= PASS_PERCENTAGE,
            "anti_cheat_count": log_count
        })

    total_attempts = len(data)
    passed_attempts = sum(1 for item in data if item["passed"])
    flagged_attempts = sum(1 for item in data if item["anti_cheat_count"])
    average_percentage = round(
        sum(item["percentage"] for item in data) / total_attempts,
        1
    ) if total_attempts else 0

    cur.execute(
        """
        SELECT username, quiz_id, event_type, details, created_at
        FROM anti_cheat_logs
        ORDER BY id DESC
        LIMIT 50
        """
    )
    anti_cheat_logs = cur.fetchall()
    cur.close()

    return render_template(
        "admin_results.html",
        data=data,
        anti_cheat_logs=anti_cheat_logs,
        quiz_options=quiz_options,
        selected_quiz=selected_quiz,
        selected_status=selected_status,
        search_query=search_query,
        total_attempts=total_attempts,
        passed_attempts=passed_attempts,
        flagged_attempts=flagged_attempts,
        average_percentage=average_percentage,
        pass_percentage=PASS_PERCENTAGE,
        review_available=supports_answer_review()
    )

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if request.method == 'POST':
        cert_id = request.form.get('cert_id')

        if cert_id:
            return redirect(f"/certificate/{cert_id}")

    return render_template("verify.html")


@app.route('/run_code/<int:question_id>', methods=['POST'])
def run_code(question_id):
    if 'user' not in session or session['role'] != 'student':
        return jsonify({"ok": False, "error": "Login as a student to run code."}), 403

    if not supports_coding_questions():
        return jsonify({"ok": False, "error": "Coding questions are not configured in the database."}), 400

    if not coding_is_configured():
        return jsonify({
            "ok": False,
            "error": "Code execution is disabled. Enable LOCAL_CODE_RUNNER or configure Judge0."
        }), 400

    cur = mysql.connection.cursor()
    cur.execute(
        """
        SELECT language_id
        FROM questions
        WHERE id=%s AND question_type='coding'
        """,
        (question_id,)
    )
    question = cur.fetchone()
    cur.close()

    if not question:
        return jsonify({"ok": False, "error": "Coding question not found."}), 404

    payload = request.get_json(silent=True) or {}
    source_code = payload.get("source_code", "")
    language_id = language_id_from_form(
        payload.get("language_key", ""),
        question[0] or JUDGE0_LANGUAGES["python"]["id"]
    )
    test_cases = [
        test_case for test_case in get_question_test_cases(question_id)
        if not test_case["is_hidden"]
    ]

    if not source_code.strip():
        return jsonify({"ok": False, "error": "Write code before running."}), 400

    if not test_cases:
        return jsonify({"ok": False, "error": "No visible sample test case is available."}), 400

    passed_count, details = grade_coding_question(
        source_code=source_code,
        language_id=language_id,
        test_cases=test_cases
    )

    return jsonify({
        "ok": True,
        "passed": passed_count,
        "total": len(test_cases),
        "cases": details,
        "status": "Accepted" if passed_count == len(test_cases) else "Check failed cases"
    })


@app.route('/log_anti_cheat/<int:quiz_id>', methods=['POST'])
def log_anti_cheat(quiz_id):
    if 'user' not in session or session['role'] != 'student':
        return jsonify({"ok": False}), 403

    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event_type", "unknown"))[:80]
    details = str(payload.get("details", ""))[:1000]

    ensure_anti_cheat_table()
    cur = mysql.connection.cursor()
    cur.execute(
        """
        INSERT INTO anti_cheat_logs(username, quiz_id, event_type, details)
        VALUES(%s,%s,%s,%s)
        """,
        (session['user'], quiz_id, event_type, details)
    )
    mysql.connection.commit()
    cur.close()

    return jsonify({"ok": True})


# LOGOUT
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user', None)
    session.pop('role', None)
    return redirect('/login')


if __name__ == "__main__":
    app.run(debug=True)
