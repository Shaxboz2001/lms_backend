from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_, text
from typing import List, Optional
from datetime import date, datetime
from enum import Enum

from .dependencies import get_db, get_current_user
from .schemas import PaymentResponse, UserResponse, GroupResponse
from .models import User, UserRole, Payment, Group

payments_router = APIRouter(prefix="/payments", tags=["Payments"])


class PaymentStatus(str, Enum):
    paid = "paid"
    unpaid = "unpaid"
    partial = "partial"


# ==============================
# GET all payments
# ==============================
@payments_router.get("/", response_model=List[PaymentResponse])
def get_payments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == UserRole.student:
        payments = db.query(Payment).filter(Payment.student_id == current_user.id).all()
    elif current_user.role == UserRole.teacher:
        group_ids = [g.id for g in current_user.groups_as_teacher]
        payments = db.query(Payment).filter(
            or_(
                Payment.teacher_id == current_user.id,
                Payment.group_id.in_(group_ids)
            )
        ).all()
    elif current_user.role in [UserRole.manager, UserRole.admin]:
        payments = db.query(Payment).all()
    else:
        payments = []

    for p in payments:
        p.is_overdue = bool(p.due_date and p.due_date < date.today() and p.status != "paid")

    return payments


# ==============================
# CREATE new payment manually
# ==============================
@payments_router.post("/", response_model=PaymentResponse)
def create_payment(
    amount: float = Body(..., gt=0),
    description: Optional[str] = Body(None),
    student_id: Optional[int] = Body(None),
    group_id: Optional[int] = Body(None),
    month: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar to‘lov qo‘sha olmaydi.")

    if not student_id:
        raise HTTPException(status_code=400, detail="O‘quvchi ID kiritilmadi.")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    # 🧩 Agar group_id kiritilmagan bo‘lsa — studentning birinchi guruhini olamiz
    if not group_id:
        group = db.query(Group).filter(Group.id == student.group_id).first()
        if not group:
            raise HTTPException(status_code=400, detail="O‘quvchiga biriktirilgan guruh topilmadi.")
        group_id = group.id
    else:
        group = db.query(Group).filter(Group.id == group_id).first()

    if not month:
        month = date.today().strftime("%Y-%m")

    # 🔹 Kurs narxini avtomatik olish
    course_price = group.course.price if group and group.course else 0

    payment = Payment(
        amount=amount,
        description=description or group.course.title if group and group.course else "To‘lov",
        student_id=student_id,
        group_id=group_id,
        month=month,
        status="paid" if amount >= course_price else "partial",
        debt_amount=max(course_price - amount, 0),
        created_at=datetime.now(),
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# ==============================
# GENERATE unpaid debts automatically
# ==============================
@payments_router.post("/generate-debts")
def generate_monthly_debts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin generatsiya qilishi mumkin.")

    today = date.today()
    current_month = today.strftime("%Y-%m")
    groups = db.query(Group).all()
    created_count = 0

    for group in groups:
        students = db.query(User).filter(User.group_id == group.id, User.role == UserRole.student).all()
        for student in students:
            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == current_month
            ).first()
            if not existing:
                course_price = group.course.price if group.course else 0
                payment = Payment(
                    amount=0,
                    description=f"{current_month} uchun avtomatik qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status="unpaid",
                    debt_amount=course_price,
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                )
                db.add(payment)
                created_count += 1

    db.commit()
    return {"message": f"{created_count} ta yangi qarz yozildi", "month": current_month}


# ==============================
# MARK PAYMENT AS PAID va BALANSNI YANGILASH
# ==============================
@payments_router.put("/mark-paid/{payment_id}")
def mark_payment_as_paid(
    payment_id: int,
    amount: float = Body(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Sizda ruxsat yo‘q.")

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To‘lov topilmadi.")

    student = db.query(User).filter(User.id == payment.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    # Kurs narxi
    course_price = payment.group.course.price if payment.group and payment.group.course else 0

    # Oldingi balans
    balance = student.balance or 0

    # Qisman to‘lovni balans bilan jamlash
    total_available = balance + amount

    # Qarzni kamaytirish
    remaining_debt = payment.debt_amount - total_available
    if remaining_debt <= 0:
        payment.status = "paid"
        payment.debt_amount = 0
        # Agar ortiqcha pul bo‘lsa, balansga yoziladi
        student.balance = abs(remaining_debt)
    else:
        payment.status = "partial"
        payment.debt_amount = remaining_debt
        student.balance = 0

    # To‘langan summa
    payment.amount += amount
    payment.paid_at = datetime.now()

    db.commit()
    db.refresh(payment)
    db.refresh(student)

    return {"message": "To‘lov yangilandi ✅", "payment": payment, "balance": student.balance}

# ==============================
# GET student's monthly payment history
# ==============================
@payments_router.get("/student/{student_id}/history")
def get_student_payment_history(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 🔐 Ruxsat: faqat admin, manager yoki o‘zi
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q!")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi")

    payments = (
        db.query(Payment)
        .filter(Payment.student_id == student_id)
        .order_by(Payment.month.desc())
        .all()
    )

    history = []
    total_paid = 0
    total_debt = 0

    for p in payments:
        # Kurs nomini olish
        course_name = None
        if p.group and p.group.course:
            course_name = p.group.course.title

        group_name = p.group.name if p.group else None

        total_paid += p.amount or 0
        total_debt += p.debt_amount or 0

        history.append({
            "month": p.month,
            "course_name": course_name,
            "group_name": group_name,
            "amount": p.amount or 0,
            "debt_amount": p.debt_amount or 0,
            "status": p.status,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "is_overdue": bool(p.due_date and p.due_date < date.today() and p.status != "paid"),
        })

    return {
        "student_id": student.id,
        "student_name": student.full_name or student.username,
        "total_paid": total_paid,
        "total_debt": total_debt,
        "history": history,
    }

# ==============================
# CALCULATE MONTHLY PAYMENTS avtomatik, balans bilan
# ==============================
@payments_router.post("/calculate-monthly")
def calculate_monthly_payments(
    month: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin hisoblay oladi.")

    today = date.today()
    current_month = month or today.strftime("%Y-%m")
    groups = db.query(Group).all()
    created, updated = 0, 0

    for group in groups:
        course_price = group.course.price if group.course else 0
        lessons_count = 12
        if course_price == 0:
            continue

        students = db.query(User).filter(
            User.group_id == group.id,
            User.role == UserRole.student
        ).all()

        for student in students:
            # Attendance yozuvlari
            attendance_records = db.execute(
                text("""
                    SELECT date, status
                    FROM attendance
                    WHERE student_id = :sid
                      AND group_id = :gid
                      AND to_char(date, 'YYYY-MM') = :month
                """),
                {"sid": student.id, "gid": group.id, "month": current_month}
            ).fetchall()

            attended_lessons = sum(1 for a in attendance_records if a.status == "present")
            absent_lessons = sum(1 for a in attendance_records if a.status == "absent")
            total_lessons = attended_lessons + absent_lessons
            per_lesson_price = course_price / lessons_count if lessons_count else 0

            monthly_due = round(per_lesson_price * lessons_count, 2) if total_lessons > 0 else 0

            # Oldingi to‘lovlar va balans
            previous_payments = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month <= current_month
            ).all()
            total_paid_before = sum(p.amount or 0 for p in previous_payments)
            balance = student.balance or 0

            # Qarzni balans bilan kamaytirish
            total_available = total_paid_before + balance
            final_debt = max(monthly_due - total_available, 0)

            # Payment status
            if final_debt <= 0:
                payment_status = "paid"
                student.balance = total_available - monthly_due  # ortiqcha pul
            elif 0 < final_debt < course_price:
                payment_status = "partial"
                student.balance = 0
            else:
                payment_status = "unpaid"
                student.balance = 0

            # Existing payment tekshirish
            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == current_month
            ).first()

            if existing:
                existing.debt_amount = final_debt
                existing.status = payment_status
                updated += 1
            else:
                payment = Payment(
                    amount=0,
                    description=f"{current_month} uchun hisoblangan qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status=payment_status,
                    debt_amount=final_debt,
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                )
                db.add(payment)
                created += 1

            db.add(student)  # balansni yangilash

    db.commit()

    return {
        "message": f"✅ Hisoblash yakunlandi: {created} yangi, {updated} yangilandi.",
        "month": current_month
    }

# =================== ATTENDANCE SABAB O‘ZGARTIRISH ===================
@payments_router.post("/attendance/reason")
def update_attendance_reason(
    student_id: int = Body(...),
    date_value: str = Body(...),
    group_id: int = Body(...),
    reason: str = Body(...),  # "sababli" yoki "sababsiz"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager o‘zgartira oladi.")

    att = db.execute(
        text("""
            SELECT * FROM attendance
            WHERE student_id = :sid AND group_id = :gid AND date = :dt
        """),
        {"sid": student_id, "gid": group_id, "dt": date_value}
    ).fetchone()

    if not att:
        raise HTTPException(status_code=404, detail="Dars topilmadi.")

    db.execute(
        text("""
            UPDATE attendance
            SET reason = :reason
            WHERE student_id = :sid AND group_id = :gid AND date = :dt
        """),
        {"reason": reason, "sid": student_id, "gid": group_id, "dt": date_value}
    )
    db.commit()

    return {"message": f"Dars uchun sabab yangilandi: {reason}"}


