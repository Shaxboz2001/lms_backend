from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import User, StudentStatus, Group, Payment, Attendance, UserRole, StudentAnswer, group_students, \
    group_teachers, Question, Option, Test
from .dependencies import get_db, get_current_user

dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@dashboard_router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    role = current_user.role
    stats = {}

    # -------------------------
    # ADMIN & MANAGER statistikasi
    # -------------------------
    if role in [UserRole.admin, UserRole.manager]:
        total_students = db.query(User).filter(User.role == "student").count()
        interested = db.query(User).filter(User.role == "student").filter(User.status == "interested").count()
        studying = db.query(User).filter(User.role == "student").filter(User.status == "studying").count()
        left = db.query(User).filter(User.role == "student").filter(User.status == "left").count()
        graduated = db.query(User).filter(User.role == "student").filter(User.status == "graduated").count()

        groups_count = db.query(Group).count()

        total_payments = db.query(Payment).with_entities(
            func.sum(Payment.amount)
        ).scalar() or 0
        today_payments = db.query(Payment).filter(
            func.date(Payment.created_at) == func.current_date()
        ).with_entities(func.sum(Payment.amount)).scalar() or 0

        stats = {
            "students": {
                "total": total_students,
                "interested": interested,
                "studying": studying,
                "left": left,
                "graduated": graduated,
            },
            "groups": {"count": groups_count},
            "payments": {"total": total_payments, "today": today_payments},
        }

    # -------------------------
    # TEACHER statistikasi
    # -------------------------
    elif role == UserRole.teacher:
        teacher_groups = (
            db.query(Group)
            .join(group_teachers, group_teachers.c.group_id == Group.id)
            .filter(group_teachers.c.teacher_id == current_user.id)
            .all()
        )
        student_ids = [s.id for g in teacher_groups for s in g.students]
        total_students = len(student_ids)

        graduated = db.query(User).filter(User.role == "student").filter(User.status == "graduated").count()

        stats = {
            "groups": len(teacher_groups),
            "students_count": total_students,
            "graduated": graduated,
        }

    # -------------------------
    # STUDENT statistikasi
    # -------------------------
    elif role == UserRole.student:
        # 1️⃣ Studentni topish
        student = (
            db.query(User)
            .filter(User.role == UserRole.student, User.id == current_user.id)
            .first()
        )
        if not student:
            raise HTTPException(status_code=404, detail="Student topilmadi")

        # 2️⃣ Student qatnashgan testlar ID’lari
        test_ids = (
            db.query(Question.test_id)
            .join(StudentAnswer, StudentAnswer.question_id == Question.id)
            .filter(StudentAnswer.student_id == student.id)
            .distinct()
            .all()
        )
        test_ids = [tid[0] for tid in test_ids]

        results = []

        for test_id in test_ids:
            # 3️⃣ Testdagi savollar soni
            total_q = db.query(Question).filter(Question.test_id == test_id).count()
            if total_q == 0:
                continue

            # 4️⃣ Studentning eng so‘nggi topshirgan vaqti
            last_attempt = (
                db.query(func.max(StudentAnswer.submitted_at))
                .join(Question, StudentAnswer.question_id == Question.id)
                .filter(
                    StudentAnswer.student_id == student.id,
                    Question.test_id == test_id
                )
                .scalar()
            )
            if not last_attempt:
                continue

            # 5️⃣ Faqat eng so‘nggi urinishdagi javoblarni olish
            correct = (
                db.query(func.count(StudentAnswer.id))
                .join(Option, StudentAnswer.selected_option_id == Option.id)
                .join(Question, StudentAnswer.question_id == Question.id)
                .filter(
                    StudentAnswer.student_id == student.id,
                    Question.test_id == test_id,
                    Option.is_correct == True,
                    func.date_trunc('second', StudentAnswer.submitted_at)
                    == func.date_trunc('second', last_attempt)
                )
                .scalar()
            )

            # 6️⃣ Test nomini olish
            test = db.query(Test).filter(Test.id == test_id).first()
            test_name = test.title if test else f"Test #{test_id}"

            # 7️⃣ Test natijasini hisoblash
            score = round((correct / total_q) * 100, 2) if total_q else 0
            results.append({
                "test_id": test_id,
                "test_name": test_name,
                "submitted_at": last_attempt.strftime("%Y-%m-%d %H:%M:%S"),
                "correct": correct,
                "total_questions": total_q,
                "score": score
            })

        # 8️⃣ O‘rtacha va oxirgi ballni hisoblash
        avg_score = round(sum(r["score"] for r in results) / len(results), 2) if results else 0
        last_score = results[-1]["score"] if results else 0

        # 9️⃣ Yakuniy statistika
        stats = {
            "profile": {
                "full_name": student.full_name,
                "phone": student.phone,
            },
            "attendance": {
                "attended": db.query(Attendance)
                .filter(Attendance.student_id == student.id, Attendance.status == "present")
                .count(),
                "missed": db.query(Attendance)
                .filter(Attendance.student_id == student.id, Attendance.status == "absent")
                .count(),
            },
            "tests": {
                "average": avg_score,
                "last": last_score,
                "details": results  # 🔥 Har bir test alohida ko‘rsatiladi
            },
        }

        return stats


    else:
        raise HTTPException(status_code=403, detail="Role not supported")

    return stats
