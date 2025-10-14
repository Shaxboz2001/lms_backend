from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models import User, StudentStatus, Group, Payment, Attendance, UserRole, StudentAnswer
from dependencies import get_db, get_current_user

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
            db.func.sum(Payment.amount)
        ).scalar() or 0
        today_payments = db.query(Payment).filter(
            db.func.date(Payment.created_at) == db.func.current_date()
        ).with_entities(db.func.sum(Payment.amount)).scalar() or 0

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
        teacher_groups = db.query(Group).filter(Group.teacher_id == current_user.id).all()
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
            .filter(User.role == UserRole.student)
            .filter(User.id == current_user.id)
            .first()
        )
        if not student:
            raise HTTPException(status_code=404, detail="Student topilmadi")

        # 2️⃣ Qatnashgan va qatnashmagan darslar
        attended = (
            db.query(Attendance)
            .filter(Attendance.student_id == student.id, Attendance.status == True)
            .count()
        )

        total_lessons = (
            db.query(Attendance)
            .filter(Attendance.student_id == student.id)
            .count()
        )

        missed = total_lessons - attended if total_lessons else 0

        # 3️⃣ Test natijalari (agar mavjud bo‘lsa)
        tests = (
            db.query(StudentAnswer)
            .filter(StudentAnswer.student_id == student.id)
            .order_by(StudentAnswer.id.asc())
            .all()
        )

        test_scores = [t.score for t in tests]
        avg_score = round(sum(test_scores) / len(test_scores), 2) if test_scores else 0
        last_score = test_scores[-1] if test_scores else 0

        # 4️⃣ Yakuniy statistika
        stats = {
            "profile": {
                "full_name": student.full_name,
                "phone": student.phone,
            },
            "attendance": {
                "attended": attended,
                "missed": missed,
                "total": total_lessons,
            },
            "tests": {
                "average": avg_score,
                "last": last_score,
            },
        }

        return stats

    else:
        raise HTTPException(status_code=403, detail="Role not supported")

    return stats
