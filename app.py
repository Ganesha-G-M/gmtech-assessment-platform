from flask import Flask, render_template, request, redirect, session
from flask_mysqldb import MySQL
import random

app = Flask(__name__)

# Secret key
app.secret_key = "gmtech_secret"

# MySQL configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Gani@2004'
app.config['MYSQL_DB'] = 'gmtech'

mysql = MySQL(app)


# HOME
@app.route('/')
def home():
    return render_template("index.html")


# REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']

        cur = mysql.connection.cursor()

        cur.execute(
            "INSERT INTO users(name,email,password,role) VALUES(%s,%s,%s,%s)",
            (name, email, password, role)
        )

        mysql.connection.commit()
        cur.close()

        return redirect('/login')

    return render_template("register.html")


# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        email = request.form['email']
        password = request.form['password']
        role = request.form['role']

        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT * FROM users WHERE email=%s AND password=%s AND role=%s",
            (email, password, role)
        )

        user = cur.fetchone()
        cur.close()

        if user:
            session['user'] = user[1]
            session['role'] = user[4]
            return redirect('/dashboard')
        else:
            return "Invalid Email or Password"

    return render_template("login.html")


# DASHBOARD
@app.route('/dashboard')
def dashboard():

    if 'user' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM quizzes")
    quizzes = cur.fetchall()
    cur.close()

    return render_template(
        "dashboard.html",
        user=session['user'],
        role=session['role'],
        quizzes=quizzes
    )


# CREATE QUIZ (ADMIN ONLY)
@app.route('/create_quiz', methods=['GET', 'POST'])
def create_quiz():

    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    if request.method == 'POST':

        title = request.form['title']
        description = request.form['description']
        time_limit = request.form['time_limit']

        cur = mysql.connection.cursor()

        cur.execute(
            "INSERT INTO quizzes(title,description,time_limit) VALUES(%s,%s,%s)",
            (title, description, time_limit)
        )

        mysql.connection.commit()
        cur.close()

        return redirect('/dashboard')

    return render_template("create_quiz.html")


# ADD QUESTION (ADMIN ONLY)
@app.route('/add_question', methods=['GET', 'POST'])
def add_question():

    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()

    cur.execute("SELECT id,title FROM quizzes")
    quizzes = cur.fetchall()

    if request.method == 'POST':

        quiz_id = request.form['quiz_id']
        question = request.form['question']
        option1 = request.form['option1']
        option2 = request.form['option2']
        option3 = request.form['option3']
        option4 = request.form['option4']
        correct_option = request.form['correct_option']

        cur.execute("""
        INSERT INTO questions
        (quiz_id,question,option1,option2,option3,option4,correct_option)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
        """,
                    (quiz_id,question,option1,option2,option3,option4,correct_option))

        mysql.connection.commit()

        return redirect('/dashboard')

    cur.close()

    return render_template("add_question.html", quizzes=quizzes)

# START QUIZ
@app.route('/start_quiz/<int:quiz_id>')
def start_quiz(quiz_id):

    if 'user' not in session:
        return redirect('/login')

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM questions WHERE quiz_id=%s", (quiz_id,))
    questions = cur.fetchall()

    cur.execute("SELECT time_limit FROM quizzes WHERE id=%s", (quiz_id,))
    quiz = cur.fetchone()

    cur.close()

    time_limit = quiz[0] * 60

    questions = list(questions)
    random.shuffle(questions)

    return render_template(
        "quiz.html",
        questions=questions,
        quiz_id=quiz_id,
        time_limit=time_limit
    )


# SUBMIT QUIZ
@app.route('/submit_quiz/<int:quiz_id>', methods=['POST'])
def submit_quiz(quiz_id):

    if 'user' not in session:
        return redirect('/login')

    username = session['user']

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM questions WHERE quiz_id=%s", (quiz_id,))
    questions = cur.fetchall()

    score = 0
    total = len(questions)

    for q in questions:

        question_id = q[0]
        correct_answer = q[7]

        user_answer = request.form.get(f"q{question_id}")

        if user_answer and int(user_answer) == correct_answer:
            score += 1

    cur.execute(
        "INSERT INTO results(username,quiz_id,score,total) VALUES(%s,%s,%s,%s)",
        (username, quiz_id, score, total)
    )

    mysql.connection.commit()
    cur.close()

    return render_template("result.html", score=score, total=total)


# LEADERBOARD
@app.route('/leaderboard')
def leaderboard():

    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT username,score,total FROM results ORDER BY score DESC LIMIT 10"
    )

    data = cur.fetchall()

    cur.close()

    return render_template("leaderboard.html", results=data)


# HISTORY
@app.route('/history')
def history():

    if 'user' not in session:
        return redirect('/login')

    username = session['user']

    cur = mysql.connection.cursor()

    cur.execute(
        "SELECT quiz_id,score,total FROM results WHERE username=%s",
        (username,)
    )

    history = cur.fetchall()

    cur.close()

    return render_template("history.html", history=history)


# ANALYTICS
@app.route('/analytics')
def analytics():

    cur = mysql.connection.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM quizzes")
    quizzes = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM results")
    attempts = cur.fetchone()[0]

    cur.close()

    return render_template(
        "analytics.html",
        users=users,
        quizzes=quizzes,
        attempts=attempts
    )

@app.route('/delete_quiz/<int:quiz_id>')
def delete_quiz(quiz_id):

    if 'user' not in session or session['role'] != 'admin':
        return redirect('/dashboard')

    cur = mysql.connection.cursor()

    # delete questions of that quiz first
    cur.execute("DELETE FROM questions WHERE quiz_id=%s", (quiz_id,))

    # delete quiz
    cur.execute("DELETE FROM quizzes WHERE id=%s", (quiz_id,))

    mysql.connection.commit()
    cur.close()

    return redirect('/dashboard')

# LOGOUT
@app.route('/logout')
def logout():

    session.pop('user', None)
    session.pop('role', None)

    return redirect('/login')


if __name__ == "__main__":
    app.run(debug=True)