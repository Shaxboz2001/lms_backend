from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import date, datetime
from enum import Enum

from .dependencies import get_db, get_current_user
from .schemas import PaymentResponse, UserResponse, GroupResponse
from .models import User, UserRole, Payment, Group

payments_router = APIRouter(
    prefix="/payments",
    tags=["Payments"]
)


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
        payments = db.query(Payment).filter(
            or_(
                Payment.student_id == current_user.id,
                Payment.teacher_id == current_user.id
            )
        ).all()
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

    # overdue aniqlaymiz
    for p in payments:
        if p.due_date and p.due_date < date.today() and p.status != "paid":
            p.is_overdue = True
        else:
            p.is_overdue = False

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
        raise HTTPException(status_code=403, detail="Students cannot create payments")

    if current_user.role == UserRole.teacher:
        if teacher_id and teacher_id != current_user.id:
            raise HTTPException(status_code=403, detail="Teachers can only add their own salary")
        if group_id:
            group = db.query(Group).filter(Group.id == group_id).first()
            if not group or current_user not in group.teachers:
                raise HTTPException(status_code=403, detail="You can only add payments for your groups")

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

    return PaymentResponse(
        id=payment.id,
        amount=payment.amount,
        description=payment.description,
        created_at=payment.created_at,
        month=payment.month,
        status=payment.status,
        debt_amount=payment.debt_amount,
        due_date=payment.due_date,
        student=UserResponse.from_orm(payment.student) if payment.student else None,
        teacher=UserResponse.from_orm(payment.teacher) if payment.teacher else None,
        group=GroupResponse.from_orm(payment.group) if payment.group else None,
    )


# ------------------------------
# GET Only Debtors
# ------------------------------
@payments_router.get("/debts", response_model=List[PaymentResponse])
def get_debts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    debts = db.query(Payment).filter(Payment.status != "paid").all()

    result = []
    for p in debts:
        # Overdue aniqlaymiz
        p.is_overdue = bool(p.due_date and p.due_date < date.today())

        result.append(PaymentResponse(
            id=p.id,
            amount=p.amount,
            description=p.description,
            created_at=p.created_at,
            month=p.month,
            status=p.status,
            debt_amount=p.debt_amount,
            due_date=p.due_date,
            student=UserResponse.from_orm(p.student) if p.student else None,
            teacher=UserResponse.from_orm(p.teacher) if p.teacher else None,
            group=GroupResponse.from_orm(p.group) if p.group else None,
        ))

    return result

