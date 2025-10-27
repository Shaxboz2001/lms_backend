from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import date, datetime
from enum import Enum

from .dependencies import get_db, get_current_user
from .schemas import PaymentResponse, UserResponse, GroupResponse
from .models import User, UserRole, Payment, Group

payments_router = APIRouter(prefix="/payments", tags=["Payments"])


# ---------------------------------
# Enum for Payment Status
# ---------------------------------
class PaymentStatus(str, Enum):
    paid = "paid"
    unpaid = "unpaid"
    partial = "partial"


# ------------------------------
# GET Payments
# ------------------------------
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


# ------------------------------
# CREATE Payment
# ------------------------------
@payments_router.post("/", response_model=PaymentResponse)
def create_payment(
    amount: float = Body(..., gt=0),
    description: Optional[str] = Body(None),
    student_id: Optional[int] = Body(None),
    teacher_id: Optional[int] = Body(None),
    group_id: Optional[int] = Body(None),
    month: Optional[str] = Body(None),
    status: Optional[PaymentStatus] = Body(PaymentStatus.paid),
    debt_amount: Optional[float] = Body(0),
    due_date: Optional[date] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar to‘lov qo‘sha olmaydi.")

    if not month:
        month = date.today().strftime("%Y-%m")

    payment = Payment(
        amount=amount,
        description=description,
        student_id=student_id,
        teacher_id=teacher_id,
        group_id=group_id,
        month=month,
        status=status.value,
        debt_amount=debt_amount,
        due_date=due_date,
        created_at=datetime.now()
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# ------------------------------
# GET Debts
# ------------------------------
@payments_router.get("/debts", response_model=List[PaymentResponse])
def get_debts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    debts = db.query(Payment).filter(Payment.status != "paid").all()
    for p in debts:
        p.is_overdue = bool(p.due_date and p.due_date < date.today())
    return debts


# ------------------------------
# GENERATE Monthly Debts
# ------------------------------
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
                payment = Payment(
                    amount=0,
                    description=f"{current_month} uchun avtomatik qarz",
                    student_id=student.id,
                    group_id=group.id,
                    month=current_month,
                    status="unpaid",
                    debt_amount=group.fee or 0,
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.now()
                )
                db.add(payment)
                created_count += 1

    db.commit()
    return {"message": f"{created_count} ta yangi qarz yozildi", "month": current_month}


# ------------------------------
# MARK Payment as Paid
# ------------------------------
@payments_router.put("/mark-paid/{payment_id}")
def mark_payment_as_paid(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Sizda ruxsat yo‘q.")

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To‘lov topilmadi.")

    payment.status = "paid"
    payment.amount = payment.debt_amount
    payment.debt_amount = 0
    payment.paid_at = datetime.now()

    db.commit()
    db.refresh(payment)
    return {"message": "To‘lov to‘landi ✅", "payment": payment}
