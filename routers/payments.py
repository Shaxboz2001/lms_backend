# routers/payments.py
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import List, Optional
from datetime import date, datetime

from .dependencies import get_db, get_current_user
from .models import User, UserRole, Payment, PaymentStatus, Group, Course
from .schemas import PaymentResponse

payments_router = APIRouter(prefix="/payments", tags=["Payments"])


# ================= Helperlar =================
class CalculateMonthPayload(BaseModel):
    month: Optional[str] = None  # "YYYY-MM"


def _to_yyyy_mm(dt: date) -> str:
    return dt.strftime("%Y-%m")


# ================= GET /payments =================
@payments_router.get("/", response_model=List[PaymentResponse])
def get_payments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    student_id: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    course_id: Optional[int] = Query(None),
    teacher_id: Optional[int] = Query(None),
    month: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
):
    q = db.query(Payment)

    # Role restrictions
    if current_user.role == UserRole.student:
        q = q.filter(Payment.student_id == current_user.id)
    elif current_user.role == UserRole.teacher:
        q = q.filter(Payment.teacher_id == current_user.id)

    # Filters
    if student_id:
        q = q.filter(Payment.student_id == student_id)
    if group_id:
        q = q.filter(Payment.group_id == group_id)
    if teacher_id:
        q = q.filter(Payment.teacher_id == teacher_id)
    if course_id:
        q = q.join(Group).filter(Group.course_id == course_id)
    if month:
        q = q.filter(Payment.month == month)
    if year:
        q = q.filter(func.substr(Payment.month, 1, 4) == str(year))

    payments = q.order_by(Payment.created_at.desc()).all()

    for p in payments:
        p.is_overdue = bool(p.due_date and p.due_date < date.today() and p.status != PaymentStatus.paid)

    return payments


# ================= POST /payments =================
@payments_router.post("/", response_model=PaymentResponse)
def create_payment(
    amount: float = Body(..., gt=0),
    description: Optional[str] = Body(None),
    student_id: int = Body(...),
    group_id: int = Body(...),
    month: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar to‘lov qo‘sha olmaydi.")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Guruh topilmadi.")

    if not month:
        month = _to_yyyy_mm(date.today())

    course_price = group.course.price if group.course else 0
    debt_amount = max(course_price - amount, 0)

    if debt_amount == 0:
        status = PaymentStatus.paid
    elif 0 < amount < course_price:
        status = PaymentStatus.partial
    else:
        status = PaymentStatus.unpaid

    payment = Payment(
        amount=amount,
        description=description or group.course.title,
        student_id=student_id,
        teacher_id=group.teacher_id,
        group_id=group_id,
        month=month,
        status=status,
        debt_amount=debt_amount,
        created_at=datetime.utcnow(),
    )

    db.add(payment)

    # Agar ortiqcha to‘lov bo‘lsa — balansga qo‘shamiz
    if amount > course_price and course_price > 0:
        extra = amount - course_price
        student.balance = (student.balance or 0) + extra

    db.commit()
    db.refresh(payment)
    return payment


# ================= GET /payments/student/{id} =================
@payments_router.get("/student/{student_id}")
def get_student_history(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q!")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    payments = db.query(Payment).filter(Payment.student_id == student_id).order_by(Payment.created_at.desc()).all()

    history = []
    total_paid = 0
    total_debt = 0

    for p in payments:
        total_paid += p.amount or 0
        total_debt += p.debt_amount or 0
        history.append({
            "id": p.id,
            "month": p.month,
            "amount": p.amount,
            "debt_amount": p.debt_amount,
            "status": p.status,
            "group_name": p.group.name if p.group else None,
            "course_name": p.group.course.title if p.group and p.group.course else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "student_id": student.id,
        "student_name": student.full_name or student.username,
        "total_paid": total_paid,
        "total_debt": total_debt,
        "balance": student.balance or 0,
        "history": history,
    }


# ================= POST /payments/calculate-monthly =================
@payments_router.post("/calculate-monthly")
def calculate_monthly(
    payload: CalculateMonthPayload = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat admin yoki manager hisoblay oladi.")

    today = date.today()
    month = payload.month or _to_yyyy_mm(today)
    created, updated = 0, 0

    groups = db.query(Group).all()
    for g in groups:
        course_price = g.course.price if g.course else 0
        students = db.query(User).filter(User.group_id == g.id, User.role == UserRole.student).all()

        for s in students:
            prev_unpaid = db.query(func.sum(Payment.debt_amount)).filter(
                Payment.student_id == s.id,
                Payment.group_id == g.id,
                Payment.month < month,
            ).scalar() or 0

            existing = db.query(Payment).filter(
                Payment.student_id == s.id,
                Payment.group_id == g.id,
                Payment.month == month,
            ).first()

            final_debt = max(course_price + prev_unpaid, 0)

            if existing:
                existing.debt_amount = final_debt - (existing.amount or 0)
                existing.status = (
                    PaymentStatus.paid
                    if existing.debt_amount <= 0
                    else PaymentStatus.partial
                    if existing.amount > 0
                    else PaymentStatus.unpaid
                )
                updated += 1
            else:
                p = Payment(
                    amount=0,
                    description=f"{month} uchun qarz",
                    student_id=s.id,
                    teacher_id=g.teacher_id,
                    group_id=g.id,
                    month=month,
                    debt_amount=final_debt,
                    status=PaymentStatus.unpaid,
                    created_at=datetime.utcnow(),
                )
                db.add(p)
                created += 1

    db.commit()
    return {"message": f"Hisoblash yakunlandi: {created} yangi, {updated} yangilandi", "month": month}


# ================= GET /payments/summary =================
@payments_router.get("/summary")
def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    month: Optional[str] = Query(None),
):
    q = db.query(
        func.sum(Payment.amount).label("total_paid"),
        func.sum(Payment.debt_amount).label("total_debt"),
        func.count(Payment.id).label("count"),
    )

    if month:
        q = q.filter(Payment.month == month)

    if current_user.role == UserRole.teacher:
        q = q.filter(Payment.teacher_id == current_user.id)
    elif current_user.role == UserRole.student:
        q = q.filter(Payment.student_id == current_user.id)

    totals = q.first()
    return {
        "total_paid": float(totals.total_paid or 0),
        "total_debt": float(totals.total_debt or 0),
        "count": int(totals.count or 0),
    }
