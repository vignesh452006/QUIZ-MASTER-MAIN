from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

from controller.config import Config
from controller.database import db
from datetime import datetime
from datetime import date
from controller.models import Admin, User, Role, UserRole, Staff, Student, Quiz, Question, Option,StudentResult
from sqlalchemy import or_
from gemini_service import QuizGenerator # Make sure the file name matches exactly
import json

from flask import Flask
app = Flask(__name__)
app.config.from_object(Config)
import os
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret")

db.init_app(app)

# ---------------- INIT DB, SEED ROLES & ADMIN ----------------
with app.app_context():
    db.create_all()

    # Seed roles
    for r in ["staff", "student"]:
        if not Role.query.filter_by(name=r).first():
            db.session.add(Role(name=r))
    db.session.commit()

    # Hardcoded admin in admins table
    admin_email = "admin@gmail.com"
    admin_user = Admin.query.filter_by(email=admin_email).first()
    if not admin_user:
        admin_user = Admin(
            username="admin",
            email=admin_email,
            password=generate_password_hash("admin123")
        )
        db.session.add(admin_user)
        db.session.commit()
        print("✅ Admin created in admins table")

# ---------------- HOME ----------------
@app.route("/")
def home():
    admin = Admin.query.first()   # fetch admin from DB
    return render_template("home.html", admin=admin)

# ---------------- REGISTER (STAFF/STUDENT) ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        role_name = request.form.get("role")

        if role_name not in ["staff", "student"]:
            flash("Select Staff or Student role", "danger")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("User already exists", "danger")
            return redirect(url_for("register"))

        user = User(
            username=username,
            email=email,
            password=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        role = Role.query.filter_by(name=role_name).first()
        db.session.add(UserRole(user_id=user.id, role_id=role.id))

        # create staff/student profile
        if role_name == "staff":
            db.session.add(Staff(user_id=user.id, full_name=username))
        else:
            db.session.add(Student(user_id=user.id, full_name=username))

        db.session.commit()

        flash("Registered successfully. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        # -------- ADMIN LOGIN --------
        admin = Admin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.password, password):
            session["user_id"] = admin.id
            session["role"] = "admin"
            # Instead of immediate redirect, we show success then redirect (optional)
            # For now, let's just redirect as per your logic
            return redirect(url_for("admin_dashboard"))

        # -------- USER LOGIN --------
        user = User.query.filter_by(email=email).first()
        
        # Check if user exists and password is correct
        if not user or not check_password_hash(user.password, password):
            # Pass the error string directly to the template
            return render_template("login.html", error="Wrong Password or Email!")

        # If we reach here, login is SUCCESSFUL
        ur = UserRole.query.filter_by(user_id=user.id).first()
        role = db.session.get(Role, ur.role_id)

        session["user_id"] = user.id
        session["username"] = user.username
        session["role"] = role.name

        # If you want to show "Successful Login" before they go to dashboard:
        # return render_template("login.html", success="Successfully Logged In!")
        
        if role.name == "staff":
            return redirect(url_for("staff_dashboard"))
        else:
            return redirect(url_for("student_dashboard"))

    return render_template("login.html")
@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    user = User.query.filter_by(email=email).first()
    if user and user.password == password:
        role = UserRole.query.filter_by(user_id=user.id).first()
        return {
            "status": "success",
            "user_id": user.id,
            "role": role.role.name
        }

    return {"status": "error", "message": "Invalid credentials"}, 401

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- DASHBOARDS ----------------
from sqlalchemy import or_

# ---------------- ADMIN DASHBOARD ----------------
from datetime import date
from sqlalchemy import func
from flask import jsonify
# ===================== ANALYTICS APIs =====================

@app.route("/api/analytics/overview")
def analytics_overview():
    if session.get("role") != "admin":
        return jsonify({"error": "unauthorized"}), 403

    total_students = User.query.join(UserRole).join(Role)\
        .filter(Role.name == "student").count()

    total_staff = User.query.join(UserRole).join(Role)\
        .filter(Role.name == "staff").count()

    total_quizzes = Quiz.query.count()

    total_attempts = StudentResult.query.count()

    return jsonify({
        "students": total_students,
        "staff": total_staff,
        "quizzes": total_quizzes,
        "attempts": total_attempts
    })


@app.route("/api/analytics/performance")
def analytics_performance():
    if session.get("role") != "admin":
        return jsonify({"error": "unauthorized"}), 403

    data = db.session.query(
        User.username,
        func.avg(StudentResult.score)
    ).join(StudentResult, StudentResult.student_id == User.id)\
     .group_by(User.username).all()

    return jsonify({
        "labels": [d[0] for d in data],
        "scores": [float(d[1]) for d in data]
    })


@app.route("/api/analytics/quiz_difficulty")
def quiz_difficulty():
    if session.get("role") != "admin":
        return jsonify({"error": "unauthorized"}), 403

    data = db.session.query(
        Quiz.subject,
        func.avg(StudentResult.score)
    ).join(StudentResult, StudentResult.quiz_id == Quiz.id)\
     .group_by(Quiz.subject).all()

    return jsonify({
        "labels": [d[0] for d in data],
        "difficulty": [float(d[1]) for d in data]
    })




# ---------------- ADMIN SEARCH ----------------
@app.route("/admin_search")
def admin_search():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 5

    students = User.query.join(UserRole).join(Role)\
        .filter(Role.name=="student",
                or_(User.username.ilike(f"%{q}%"),
                    User.email.ilike(f"%{q}%")))\
        .paginate(page=page, per_page=per_page)

    staff = User.query.join(UserRole).join(Role)\
        .filter(Role.name=="staff",
                or_(User.username.ilike(f"%{q}%"),
                    User.email.ilike(f"%{q}%")))\
        .paginate(page=page, per_page=per_page)

    quizzes = Quiz.query.filter(
        or_(Quiz.subject.ilike(f"%{q}%"),
            Quiz.chapter.ilike(f"%{q}%"))
    ).paginate(page=page, per_page=per_page)

    return render_template("admin_dashboard.html",
                           username=session.get("username"),
                           students=students,
                           staff=staff,
                           quizzes=quizzes)


# ---------------- EDIT USER ----------------
@app.route("/admin/edit_user/<int:user_id>", methods=["POST"])
def admin_edit_user(user_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    user = User.query.get_or_404(user_id)
    user.username = request.form["username"]
    user.email = request.form["email"]
    db.session.commit()
    flash("User updated successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------- DELETE USER ----------------
@app.route("/admin/delete_user/<int:user_id>")
def admin_delete_user(user_id):
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    user = User.query.get_or_404(user_id)
    UserRole.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------- ADMIN SUMMARY ----------------
@app.route("/admin/summary")
def admin_summary():
    if session.get("role") != "admin":
        return redirect(url_for("login"))

    total_students = UserRole.query.join(Role)\
        .filter(Role.name == "student").count()

    total_staff = UserRole.query.join(Role)\
        .filter(Role.name == "staff").count()

    total_quizzes = Quiz.query.count()

    return render_template(
        "admin_summary.html",
        total_students=total_students,
        total_staff=total_staff,
        total_quizzes=total_quizzes
    )






# ---------------- ADMIN SETTINGS ----------------
@app.route("/admin/settings")
def admin_settings():
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    return render_template("admin_settings.html")


@app.route("/staff")
def staff_dashboard():
    if session.get("role") != "staff":
        return redirect(url_for("login"))
    return render_template("staff_dashboard.html",
                           username=session.get("username"))







@app.route("/start_quiz/<int:quiz_id>", methods=["GET", "POST"])
def start_quiz(quiz_id):
    if session.get("role") != "student":
        return redirect(url_for("login"))

    quiz = Quiz.query.get_or_404(quiz_id)
    questions = Question.query.filter_by(quiz_id=quiz.id).all()

    if request.method == "POST":
        score = 0
        for q in questions:
            selected = request.form.get(str(q.id))
            if selected:
                opt = Option.query.get(int(selected))
                if opt and opt.is_correct:
                    score += 1

        result = StudentResult(
            student_id=session["user_id"],
            quiz_id=quiz.id,
            score=score,
            taken_at=datetime.utcnow()
        )
        db.session.add(result)
        db.session.commit()

        flash("Quiz submitted successfully!", "success")
        return redirect(url_for("view_results"))

    return render_template("start_quiz.html",
                           quiz=quiz,
                           questions=questions)

@app.route("/student")
def student_dashboard():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    upcoming_quizzes = Quiz.query.all()  # no date filter

    return render_template(
        "student_dashboard.html",
        username=session.get("username"),
        upcoming_quizzes=upcoming_quizzes
    )




from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
from controller.database import db
from controller.models import Quiz, Question, Option
from gemini_service import QuizGenerator

@app.route("/ai_generate_quiz", methods=["POST"])
def ai_generate_quiz():
    if session.get("role") not in ["staff", "admin"]:
        return jsonify({"status": "error", "message": "Unauthorized"}), 403

    topic = request.form.get("topic")
    num_q_raw = request.form.get("num_questions", 3)

    try:
        num_q = int(num_q_raw)
    except (ValueError, TypeError):
        num_q = 3

    if not topic:
        return jsonify({"status": "error", "message": "Please enter a topic"}), 400

    try:
        generator = QuizGenerator()
        questions = generator.generate_quiz(topic, num_q)
        
        if not questions:
            return jsonify({"status": "error", "message": "AI failed to generate questions. Check API Key or Quota in terminal."}), 500
            
        return jsonify({"status": "success", "questions": questions})
        
    except Exception as e:
        print(f"Server Error: {str(e)}")
        return jsonify({"status": "error", "message": "Internal Server Error"}), 500

# SAVE FULL QUIZ ROUTE
@app.route("/create_quiz", methods=["GET", "POST"])
def create_quiz():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    if request.method == "POST":
        try:
            # 1. Create Quiz Header
            quiz = Quiz(
                subject=request.form.get("subject"),
                chapter=request.form.get("chapter"),
                date=datetime.strptime(request.form.get("date"), "%Y-%m-%d").date(),
                duration=int(request.form.get("duration"))
            )
            db.session.add(quiz)
            db.session.flush()

            # 2. Process Questions and Options
            q_index = 1
            while f"question_{q_index}" in request.form:
                q_text = request.form.get(f"question_{q_index}")
                correct_opt = request.form.get(f"q{q_index}_correct") # 'a', 'b', etc.

                new_q = Question(text=q_text, quiz_id=quiz.id)
                db.session.add(new_q)
                db.session.flush()

                for letter in ['a', 'b', 'c', 'd']:
                    opt_text = request.form.get(f"q{q_index}_{letter}")
                    is_correct = (letter == correct_opt)
                    new_opt = Option(text=opt_text, is_correct=is_correct, question_id=new_q.id)
                    db.session.add(new_opt)
                
                q_index += 1

            db.session.commit()
            flash("Quiz created successfully!", "success")
            return redirect(url_for("staff_dashboard"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error saving quiz: {str(e)}", "danger")

    return render_template("create_quiz.html")


from functools import wraps
from flask import session, redirect, url_for, flash, render_template, request

# 1. THE DECORATOR (Place this at the top)
from functools import wraps

def staff_or_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ["staff", "admin"]:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

# 2. THE ADMIN DASHBOARD ROUTE
@app.route("/admin/dashboard")
def admin_dashboard():

    if session.get("role") != "admin":
        return redirect(url_for("login"))

    page = request.args.get("page", 1, type=int)

    users = User.query.paginate(
        page=page,
        per_page=10,
        error_out=False
    )

    quizzes = (
        Quiz.query
        .order_by(Quiz.created_at.desc())
        .paginate(page=page, per_page=10, error_out=False)
    )

    return render_template(
        "admin_dashboard.html",
        username=session.get("username"),
        users=users,
        quizzes=quizzes
    )

@app.route('/view_quizzes')
def view_quizzes():
    # 1. Security Check: Ensure user is logged in
    if not session.get("user_id"):
        return redirect(url_for("login"))
    
    # 2. Get search query from the URL (e.g., /view_quizzes?q=Science)
    query = request.args.get('q', '').strip()
    
    # 3. Database Query: Search if query exists, else get all
    if query:
        quizzes = Quiz.query.filter(
            (Quiz.subject.ilike(f"%{query}%")) | 
            (Quiz.chapter.ilike(f"%{query}%"))
        ).all()
    else:
        quizzes = Quiz.query.all()
        
    # 4. Render the page, passing the user's role for button logic
    return render_template('view_quizzes.html', 
                           quizzes=quizzes, 
                           query=query, 
                           role=session.get('role'))

# 2. ROUTE FOR PREVIEWING A SPECIFIC QUIZ (OPEN TO ALL)
@app.route('/view_quiz/<int:quiz_id>')
def view_quiz(quiz_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    quiz = Quiz.query.get_or_404(quiz_id)
    # Fetch questions and options
    questions = Question.query.filter_by(quiz_id=quiz_id).all()
    
    return render_template('view_quiz.html', 
                           quiz=quiz, 
                           questions=questions, 
                           role=session.get('role'))

# 4. THE DELETE ROUTE
@app.route("/delete_quiz/<int:quiz_id>")
@staff_or_admin_required
def delete_quiz(quiz_id):

    quiz = Quiz.query.get_or_404(quiz_id)

    # ✅ First delete related student results
    StudentResult.query.filter_by(quiz_id=quiz.id).delete()

    # ✅ Then delete quiz
    db.session.delete(quiz)
    db.session.commit()

    flash("Quiz deleted successfully", "success")
    return redirect(url_for("manage_quizzes"))

@app.route("/admin/manage_quizzes")
@staff_or_admin_required
def manage_quizzes():
    quizzes = Quiz.query.all()
    return render_template("manage_quizzes.html", quizzes=quizzes)




@app.route("/add_question/<int:quiz_id>", methods=["POST"])
def add_question(quiz_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    q_text = request.form["question"]
    correct = request.form["correct"]

    question = Question(text=q_text, quiz_id=quiz_id)
    db.session.add(question)
    db.session.flush()  # get question.id

    for i in range(4):
        opt_text = request.form[f"opt{i}"]
        option = Option(
            text=opt_text,
            is_correct=(str(i) == correct),
            question_id=question.id
        )
        db.session.add(option)

    db.session.commit()
    flash("Question added!", "success")
    return redirect(url_for("manage_quizzes"))


@app.route("/update_question/<int:question_id>", methods=["POST"])
def update_question(question_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    question = Question.query.get_or_404(question_id)
    question.text = request.form["question"]
    correct = request.form["correct"]

    for i, opt in enumerate(question.options):
        opt.text = request.form[f"opt{i}"]
        opt.is_correct = (str(i) == correct)

    db.session.commit()
    flash("Question updated!", "success")
    return redirect(url_for("manage_quizzes"))


@app.route("/delete_question/<int:question_id>", methods=["POST"])
def delete_question(question_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    q = Question.query.get_or_404(question_id)
    db.session.delete(q)
    db.session.commit()
    flash("Question deleted!", "success")
    return redirect(url_for("manage_quizzes"))

@app.route("/attempt_quiz", methods=["GET", "POST"])
def attempt_quiz():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    # Load all quizzes for dropdown
    quizzes = Quiz.query.all()
    quiz = None

    # ---------------- LOAD QUIZ (GET) ----------------
    quiz_id = request.args.get("quiz_id")
    if quiz_id:
        quiz = Quiz.query.get_or_404(int(quiz_id))

    # ---------------- SUBMIT QUIZ (POST) ----------------
    if request.method == "POST":
        quiz_id = int(request.form.get("quiz_id"))
        quiz = Quiz.query.get_or_404(quiz_id)

        score = 0
        total = len(quiz.questions)

        for q in quiz.questions:
            selected_opt_id = request.form.get(f"q{q.id}")
            if selected_opt_id:
                opt = Option.query.get(int(selected_opt_id))
                if opt and opt.is_correct:
                    score += 1

        # ✅ Save result
        result = StudentResult(
            student_id=session.get("user_id"),
            quiz_id=quiz.id,
            score=score
        )
        db.session.add(result)
        db.session.commit()

        flash(f"Quiz submitted! Your score: {score} / {total}", "success")
        return redirect(url_for("view_results"))

    # ---------------- RENDER PAGE ----------------
    return render_template(
        "attempt_quiz.html",
        quizzes=quizzes,
        quiz=quiz
    )


@app.route("/view_results")
def view_results():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    role = session.get("role")
    user_id = session.get("user_id")

    if role == "student":
        # We filter by student_id and order by date
        results = StudentResult.query.filter_by(student_id=user_id)\
                                     .order_by(StudentResult.taken_at.desc()).all()
    elif role == "staff":
        # Staff see everything
        results = StudentResult.query.order_by(StudentResult.taken_at.desc()).all()
    else:
        return redirect(url_for("login"))

    return render_template("view_results.html", 
                           results=results, 
                           role=role)


# ---------- SETTINGS / MANAGE STUDENTS ----------
@app.route("/settings")
def settings():
    if session.get("role") != "staff":
        return redirect(url_for("login"))
    students = User.query.join(UserRole).join(Role)\
        .filter(Role.name == "student").all()
    return render_template("settings.html", students=students)

# ---------- UPDATE STUDENT ----------
@app.route("/update_student/<int:student_id>", methods=["POST"])
def update_student(student_id):
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    student = User.query.get_or_404(student_id)
    student.username = request.form["username"]
    student.email = request.form["email"]

    db.session.commit()
    flash("Student updated successfully", "success")
    return redirect(url_for("settings"))

# ---------- DELETE STUDENT ----------
@app.route("/delete_student/<int:student_id>")
def delete_student(student_id):

    if session.get("role") != "staff":
        return redirect(url_for("login"))

    student = User.query.get_or_404(student_id)

    try:
        # Delete quiz results first
        StudentResult.query.filter_by(student_id=student.id).delete()

        db.session.delete(student)
        db.session.commit()

        flash("Student deleted successfully", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting student: {str(e)}", "danger")
        print(e)

    return redirect(url_for("settings"))


@app.route("/staff_search_students", methods=["GET"])
def staff_search_students():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()

    students = []
    results = []

    if query:
        # 🔍 Search students by name or email
        students = User.query.join(UserRole).join(Role)\
            .filter(Role.name == "student")\
            .filter(
                or_(
                    User.username.ilike(f"%{query}%"),
                    User.email.ilike(f"%{query}%")
                )
            ).all()

        # 🔍 Search results by student name or quiz subject
        results = StudentResult.query\
            .join(User, StudentResult.student_id == User.id)\
            .join(Quiz, StudentResult.quiz_id == Quiz.id)\
            .filter(
                or_(
                    User.username.ilike(f"%{query}%"),
                    Quiz.subject.ilike(f"%{query}%")
                )
            ).all()

    return render_template(
        "manage_students.html",
        query=query,
        students=students,
        results=results
    )




@app.route("/summary")
def summary():
    if session.get("role") != "staff":
        return redirect(url_for("login"))

    total_students = UserRole.query.join(Role)\
        .filter(Role.name == "student").count()

    attempted = StudentResult.query.distinct(StudentResult.student_id).count()
    not_attempted = max(total_students - attempted, 0)

    results = StudentResult.query\
        .order_by(StudentResult.taken_at.desc()).all()

    return render_template(
        "summary.html",
        total_students=total_students,
        attempted=attempted,
        not_attempted=not_attempted,
        results = results
    )
from sqlalchemy import func

@app.route("/student_summary")
def student_summary():
    if session.get("role") != "student":
        return redirect(url_for("login"))

    student_id = session.get("user_id")

    # Total quizzes available
    total_quizzes = Quiz.query.count()

    # Quizzes attempted by this student
    attempted = StudentResult.query.filter_by(student_id=student_id).count()

    not_attempted = total_quizzes - attempted if total_quizzes >= attempted else 0

    return render_template(
        "student_summary.html",
        attempted=attempted,
        not_attempted=not_attempted,
        username=session.get("username")
    )

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])
    
    # Logic to fetch data based on who is logged in
    students = []
    if session.get("role") in ["admin", "staff"]:
        students = User.query.join(UserRole).join(Role).filter(Role.name == "student").all()
    
    quizzes = Quiz.query.all()

    # CRITICAL: Make sure 'role' is passed here!
    return render_template("profile.html",
                           user=user,
                           role=session.get("role"), # This sends the role to HTML
                           students=students,
                           quizzes=quizzes)

@app.route("/edit_profile", methods=["POST"])
def edit_profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])
    user.username = request.form["username"]
    user.email = request.form["email"]

    db.session.commit()
    flash("Profile updated successfully", "success")
    return redirect(url_for("profile"))

from functools import wraps
from flask import session, redirect, url_for
def staff_or_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") not in ["staff", "admin"]:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper   # ✅ CORRECT


@staff_or_admin_required
def edit_student(student_id):
    student = User.query.get_or_404(student_id)

    if request.method == "POST":
        student.username = request.form["username"]
        student.email = request.form["email"]
        db.session.commit()
        flash("Student updated successfully", "success")
        return redirect(url_for("profile"))

    return render_template("edit_student.html", student=student)
@app.route("/edit_quiz/<int:quiz_id>", methods=["GET", "POST"])
@staff_or_admin_required
def edit_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)

    if request.method == "POST":
        quiz.subject = request.form["subject"]
        quiz.chapter = request.form["chapter"]
        db.session.commit()
        flash("Quiz updated successfully", "success")
        return redirect(url_for("profile"))

    return render_template("edit_quiz.html", quiz=quiz)


@app.route("/manage_subjects", methods=["POST"])
@staff_or_admin_required
def manage_subjects():
    subject = request.form["subject"]
    chapter = request.form["chapter"]

    quiz = Quiz(subject=subject, chapter=chapter)
    db.session.add(quiz)
    db.session.commit()

    flash("Subject & chapter added successfully", "success")
    return redirect(url_for("profile"))



      
@app.route("/create_quiz", methods=["POST"])
def save_quiz():
    """
    This handles the 'Save Full Quiz' button click.
    It reads all the questions (AI-generated or manual) and saves them to the DB.
    """
    try:
        subject = request.form.get("subject")
        chapter = request.form.get("chapter")
        # Add logic to save to your specific Database here
        # Example: 
        # new_quiz = Quiz(subject=subject, chapter=chapter, created_by=session['user_id'])
        # db.session.add(new_quiz)
        # db.session.commit()

        flash("Quiz saved successfully!", "success")
        return redirect(url_for('staff_dashboard'))
    except Exception as e:
        flash(f"Error saving quiz: {str(e)}", "danger")
        return redirect(url_for('create_quiz'))



        
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )



