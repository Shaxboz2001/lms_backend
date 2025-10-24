from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import List
from pydantic import BaseModel

from .dependencies import get_db
from .auth import get_current_user
from .models import (
    User, UserRole, Payment, Attendance, Group,
    SalarySetting, Payroll, PayrollPayment
)

payroll_router = APIRouter(prefix="/payroll", tags=["Payroll"])


# -------- Helper --------
def parse_month(month_str: str):
    try:
        year, month = month_str.split("-")
        year = int(year)
        month = int(month)
        start = datetime(year, month, 1)
        end = datetime(year + (month // 12), (month % 12) + 1, 1)
        return start, end
    except Exception:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")


# -------- Salary Settings --------
class SalarySettingsIn(BaseModel):
    teacher_percent: float
    manager_active_percent: float
    manager_new_percent: float


@payroll_router.get("/salary/settings")
def get_salary_settings(db: Session = Depends(get_db)):
    s = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not s:
        s = SalarySetting(teacher_percent=50, manager_active_percent=10, manager_new_percent=25)
        db.add(s)
        db.commit()
        db.refresh(s)
    return {
        "id": s.id,
        "teacher_percent": s.teacher_percent,
        "manager_active_percent": s.manager_active_percent,
        "manager_new_percent": s.manager_new_percent
    }


@payroll_router.put("/salary/settings")
def update_salary_settings(
    payload: SalarySettingsIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admin can update")
    s = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not s:
        s = SalarySetting(**payload.dict())
        db.add(s)
    else:
        for key, val in payload.dict().items():
            setattr(s, key, val)
    db.commit()
    db.refresh(s)
    return {"message": "updated", "settings": payload.dict()}


# -------- Calculate Payroll --------
@payroll_router.post("/calculate")
def calculate_payroll(
    month: str = Query(..., description="YYYY-MM"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admin can calculate payroll")

    start, end = parse_month(month)

    settings = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not settings:
        settings = SalarySetting()
        db.add(settings)
        db.commit()
        db.refresh(settings)

    # Eski payrolllar o‘chiriladi
    db.query(Payroll).filter(Payroll.month == month).delete()
    db.commit()

    # ------------------------
    # TEACHERS
    # ------------------------
    teachers = db.query(User).filter(User.role == UserRole.teacher).all()
    for t in teachers:
        group_ids = [g.id for g in db.query(Group).filter(Group.teacher_id == t.id).all()]

        # to‘lov summasi
        payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.group_id.in_(group_ids) if group_ids else False,
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0.0

        # attendance
        total_att = db.query(func.count(Attendance.id)).filter(
            Attendance.group_id.in_(group_ids) if group_ids else False,
            Attendance.date >= start.date(),
            Attendance.date < end.date()
        ).scalar() or 0

        present_att = db.query(func.count(Attendance.id)).filter(
            Attendance.group_id.in_(group_ids) if group_ids else False,
            Attendance.status == "present",
            Attendance.date >= start.date(),
            Attendance.date < end.date()
        ).scalar() or 0

        attendance_rate = (present_att / total_att * 100) if total_att > 0 else 100.0

        earned = payments_sum * (settings.teacher_percent / 100)
        deductions = earned * (1 - attendance_rate / 100)
        net = earned - deductions

        db.add(Payroll(
            user_id=t.id,
            role="teacher",
            month=month,
            earned=round(earned, 2),
            deductions=round(deductions, 2),
            net=round(net, 2),
            status="pending",
            details={
                "groups": len(group_ids),
                "payments_sum": payments_sum,
                "attendance_rate": attendance_rate
            }
        ))
    db.commit()

    # ------------------------
    # MANAGERS
    # ------------------------
    managers = db.query(User).filter(User.role == UserRole.manager).all()
    for m in managers:
        # Aktiv talabalar
        active_student_ids = [
            s[0] for s in db.query(Attendance.student_id)
            .filter(
                Attendance.status == "present",
                Attendance.date >= start.date(),
                Attendance.date < end.date()
            ).distinct().all()
        ]

        active_payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.student_id.in_(active_student_ids) if active_student_ids else False,
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0.0

        # Yangi o‘quvchilar — birinchi to‘lov aynan shu oyda bo‘lganlar
        subquery = db.query(
            Payment.student_id,
            func.min(Payment.created_at).label("first_payment_date")
        ).group_by(Payment.student_id).subquery()

        new_student_ids = [
            r[0] for r in db.query(subquery.c.student_id)
            .filter(subquery.c.first_payment_date >= start)
            .filter(subquery.c.first_payment_date < end)
            .all()
        ]

        new_students_first_payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.student_id.in_(new_student_ids) if new_student_ids else False,
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0.0

        earned = (
            active_payments_sum * (settings.manager_active_percent / 100.0)
        ) + (
            new_students_first_payments_sum * (settings.manager_new_percent / 100.0)
        )

        db.add(Payroll(
            user_id=m.id,
            role="manager",
            month=month,
            earned=round(earned, 2),
            deductions=0.0,
            net=round(earned, 2),
            status="pending",
            details={
                "active_students": len(active_student_ids),
                "new_students": len(new_student_ids),
                "active_payments_sum": active_payments_sum,
                "new_students_first_payments": new_students_first_payments_sum
            }
        ))
    db.commit()

    return {"message": f"Payroll calculated successfully for {month}"}


# -------- List Payroll --------
@payroll_router.get("/")
def list_payroll(month: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = db.query(Payroll)
    if month:
        q = q.filter(Payroll.month == month)
    if current_user.role != UserRole.admin:
        q = q.filter(Payroll.user_id == current_user.id)
    rows = q.all()
    return [
        {
            "id": r.id,
            "user_name": getattr(r.user, "full_name", ""),
            "role": r.role,
            "month": r.month,
            "earned": r.earned,
            "deductions": r.deductions,
            "net": r.net,
            "status": r.status,
            "paid_at": r.paid_at,
            "details": r.details
        }
        for r in rows
    ]


# -------- Mark as Paid --------
class PayIn(BaseModel):
    paid_amount: float


@payroll_router.post("/{payroll_id}/pay")
def pay_salary(
    payroll_id: int,
    payload: PayIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admin can mark paid")

    row = db.query(Payroll).filter(Payroll.id == payroll_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Payroll not found")
    if row.status == "paid":
        raise HTTPException(status_code=400, detail="Already paid")

    row.status = "paid"
    row.paid_at = datetime.utcnow()
    payment = PayrollPayment(
        payroll_id=row.id,
        paid_amount=payload.paid_amount,
        paid_by=current_user.id,
        paid_at=row.paid_at
    )
    db.add(payment)
    db.commit()
    db.refresh(row)

    return {"message": "Salary marked as paid", "id": row.id, "paid_amount": payload.paid_amount}
