# routers/payments.py
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import date, datetime

from .dependencies import get_db, get_current_user
from .models import User, UserRole, Payment, Group, PaymentStatus
from .schemas import PaymentResponse  # Agar mavjud bo‘lsa

payments_router = APIRouter(prefix="/payments", tags=["Payments"])


# =========================
# 🔹 GET ALL PAYMENTS (by role)
# =========================
@payments_router.get("/", response_model=List[PaymentResponse])
def get_payments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Foydalanuvchi roliga qarab to‘lovlar ro‘yxatini qaytaradi."""
    if current_user.role == UserRole.student:
        payments = db.query(Payment).filter(Payment.student_id == current_user.id).all()
    elif current_user.role == UserRole.teacher:
        group_ids = [g.id for g in getattr(current_user, "groups_as_teacher", [])]
        payments = db.query(Payment).filter(
            (Payment.teacher_id == current_user.id) | (Payment.group_id.in_(group_ids))
        ).all()
    elif current_user.role in [UserRole.manager, UserRole.admin]:
        payments = db.query(Payment).all()
    else:
        payments = []

    for p in payments:
        p.is_overdue = bool(p.due_date and p.due_date < date.today() and p.status != "paid")

    return payments


# =========================
# 🔹 CREATE PAYMENT manually
# =========================
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
    """Admin/Manager tomonidan qo‘lda to‘lov yaratish."""
    if current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar to‘lov yarata olmaydi.")

    if not student_id:
        raise HTTPException(status_code=400, detail="O‘quvchi ID kiritilmadi.")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    # Agar group_id kiritilmagan bo‘lsa — student.group_id dan olamiz
    if not group_id:
        if not student.group_id:
            raise HTTPException(status_code=400, detail="Guruh aniqlanmadi.")
        group_id = student.group_id

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi.")

    course_price = group.course.price if getattr(group, "course", None) else 0
    month = month or date.today().strftime("%Y-%m")

    status = "paid" if amount >= course_price else "partial" if amount > 0 else "unpaid"
    debt_amount = max(course_price - amount, 0)

    payment = Payment(
        amount=amount,
        description=description or (group.course.title if getattr(group, "course", None) else "To‘lov"),
        student_id=student_id,
        group_id=group_id,
        month=month,
        status=status,
        debt_amount=debt_amount,
        created_at=datetime.now()
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# =========================
# 🔹 GENERATE Monthly Debts
# =========================
@payments_router.post("/generate-debts")
def generate_monthly_debts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Har bir guruh uchun avtomatik oylik qarz yozuvlarini yaratadi."""
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin ruxsat etiladi.")

    today = date.today()
    current_month = today.strftime("%Y-%m")
    created_count = 0

    groups = db.query(Group).all()
    for group in groups:
        course_price = group.course.price if getattr(group, "course", None) else 0
        students = db.query(User).filter(User.group_id == group.id, User.role == UserRole.student).all()

        for student in students:
            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == current_month
            ).first()

            if not existing:
                payment = Payment(
                    amount=0,
                    description=f"{current_month} uchun avtomatik qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status="unpaid" if course_price > 0 else "paid",
                    debt_amount=course_price,
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                )
                db.add(payment)
                created_count += 1

    db.commit()
    return {"message": f"{created_count} ta yangi qarz yozildi", "month": current_month}


# =========================
# 🔹 MARK PAYMENT AS PAID
# =========================
@payments_router.put("/mark-paid/{payment_id}")
def mark_payment_as_paid(
    payment_id: int,
    amount: float = Body(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """To‘lovni to‘langan (yoki qisman) sifatida belgilaydi."""
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q.")

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To‘lov topilmadi.")

    course_price = payment.group.course.price if getattr(payment.group, "course", None) else 0
    payment.amount = (payment.amount or 0) + amount
    remaining = course_price - payment.amount

    if remaining <= 0:
        payment.status = "paid"
        payment.debt_amount = 0
    else:
        payment.status = "partial"
        payment.debt_amount = remaining

    payment.paid_at = datetime.now()
    db.commit()
    db.refresh(payment)
    return {"message": "To‘lov yangilandi ✅", "payment": payment}


# =========================
# 🔹 GET STUDENT PAYMENT HISTORY
# =========================
@payments_router.get("/student/{student_id}/history")
def get_student_payment_history(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """O‘quvchi to‘lov tarixini qaytaradi (admin/manager yoki o‘sha o‘quvchi o‘zi)."""
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q.")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    payments = db.query(Payment).filter(Payment.student_id == student_id).order_by(Payment.month.desc()).all()

    history = []
    total_paid, total_debt = 0, 0
    for p in payments:
        course_name = p.group.course.title if getattr(p.group, "course", None) else None
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
        "history": history
    }


# =========================
# 🔹 CALCULATE MONTHLY PAYMENTS from ATTENDANCE
# =========================
class CalculateMonthPayload(BaseModel):
    month: Optional[str] = None


@payments_router.post("/calculate-monthly")
def calculate_monthly_payments(
    payload: CalculateMonthPayload = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PostgreSQL uchun optimallashtirilgan versiya."""
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin hisoblay oladi.")

    today = date.today()
    current_month = payload.month or today.strftime("%Y-%m")
    groups = db.query(Group).all()
    created, updated = 0, 0

    for group in groups:
        course_price = group.course.price if getattr(group, "course", None) else 0
        lessons_count = 12
        if not course_price or lessons_count <= 0:
            continue

        students = db.query(User).filter(User.group_id == group.id, User.role == UserRole.student).all()

        for student in students:
            # ✅ PostgreSQL uchun TO_CHAR
            attendance_records = db.execute(
                text("""
                    SELECT status, reason
                    FROM attendance
                    WHERE student_id = :sid
                      AND group_id = :gid
                      AND TO_CHAR(date, 'YYYY-MM') = :month
                """),
                {"sid": student.id, "gid": group.id, "month": current_month}
            ).fetchall()

            attended_lessons = sum(1 for a in attendance_records if a.status == "present")
            absent_sababli = sum(1 for a in attendance_records if a.status == "absent" and a.reason == "sababli")
            absent_sababsiz = sum(1 for a in attendance_records if a.status == "absent" and a.reason == "sababsiz")

            per_lesson_price = course_price / lessons_count
            effective_lessons = attended_lessons + absent_sababsiz
            monthly_due = round(per_lesson_price * lessons_count, 2)

            previous_payment = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id
            ).order_by(Payment.month.desc()).first()

            previous_balance = 0.0
            if previous_payment:
                if previous_payment.status in [PaymentStatus.unpaid, PaymentStatus.partial]:
                    previous_balance = float(previous_payment.debt_amount or 0.0)
                elif previous_payment.status == PaymentStatus.paid:
                    previous_balance = -float(previous_payment.amount or 0.0) if (previous_payment.amount or 0) > 0 else 0.0

            if previous_balance > 0:
                final_debt = monthly_due + previous_balance
            elif previous_balance < 0:
                final_debt = max(0, monthly_due + previous_balance)
            else:
                final_debt = monthly_due

            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == current_month
            ).first()

            if existing:
                existing.debt_amount = float(final_debt)
                existing.status = (
                    PaymentStatus.paid if final_debt <= 0
                    else PaymentStatus.partial if final_debt < course_price
                    else PaymentStatus.unpaid
                )
                updated += 1
            else:
                db.add(Payment(
                    amount=0.0,
                    description=f"{current_month} uchun hisoblangan qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status=PaymentStatus.unpaid if final_debt > 0 else PaymentStatus.paid,
                    debt_amount=float(final_debt),
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                ))
                created += 1

    db.commit()
    return {"message": f"✅ Hisoblash yakunlandi: {created} yangi, {updated} yangilandi.", "month": current_month}


# =========================
# 🔹 UPDATE ATTENDANCE REASON
# =========================
@payments_router.post("/attendance/reason")
def update_attendance_reason(
    student_id: int = Body(...),
    date_value: str = Body(...),
    group_id: int = Body(...),
    reason: str = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manager tomonidan attendance sababini o‘zgartirish."""
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
