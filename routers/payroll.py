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
        year = int(year); month = int(month)
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
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
        s = SalarySetting(teacher_percent=0, manager_active_percent=0, manager_new_percent=0)
        db.add(s); db.commit(); db.refresh(s)
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
    db.commit(); db.refresh(s)
    return {"message": "updated", "settings": payload.dict()}


# -------- User List (teachers & managers) --------
@payroll_router.get("/users")
def list_teachers_and_managers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admin")
    users = db.query(User).filter(User.role.in_([UserRole.teacher, UserRole.manager])).all()
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "role": u.role.value,
            "created_at": getattr(u, "created_at", None)
        }
        for u in users
    ]


# -------- Calculate Payroll --------
@payroll_router.post("/calculate")
def calculate_payroll(month: str = Query(..., description="YYYY-MM"),
                      db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admin")

    start, end = parse_month(month)
    settings = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not settings:
        settings = SalarySetting(teacher_percent=30, manager_active_percent=10, manager_new_percent=25)
        db.add(settings); db.commit()

    # Clear existing payroll
    db.query(Payroll).filter(Payroll.month == month).delete()
    db.commit()

    # ---- Teachers ----
    teachers = db.query(User).filter(User.role == UserRole.teacher).all()
    for t in teachers:
        groups = db.query(Group.id).filter(Group.teacher_id == t.id).all()
        group_ids = [g[0] for g in groups] if groups else []

        payments_sum = 0.0
        if group_ids:
            payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
                Payment.group_id.in_(group_ids),
                Payment.created_at >= start, Payment.created_at < end
            ).scalar() or 0.0

        present = db.query(func.count(Attendance.id)).filter(
            Attendance.group_id.in_(group_ids),
            Attendance.present == True,
            Attendance.created_at >= start, Attendance.created_at < end
        ).scalar() or 0
        total = db.query(func.count(Attendance.id)).filter(
            Attendance.group_id.in_(group_ids),
            Attendance.created_at >= start, Attendance.created_at < end
        ).scalar() or 0
        attendance_rate = (present / total * 100) if total > 0 else 100.0

        earned = payments_sum * (settings.teacher_percent / 100)
        deductions = earned * (1 - attendance_rate / 100)
        net = earned - deductions

        p = Payroll(
            user_id=t.id, role="teacher", month=month,
            earned=round(earned, 2), deductions=round(deductions, 2),
            net=round(net, 2), status="pending",
            details={"attendance": attendance_rate, "payments_sum": payments_sum}
        )
        db.add(p)
    db.commit()

    # ---- Managers ----
    managers = db.query(User).filter(User.role == UserRole.manager).all()
    for m in managers:
        active_students = db.query(Attendance.student_id).filter(
            Attendance.present == True,
            Attendance.created_at >= start, Attendance.created_at < end
        ).distinct().all()
        active_ids = [r[0] for r in active_students]

        active_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.student_id.in_(active_ids),
            Payment.created_at >= start, Payment.created_at < end
        ).scalar() or 0.0

        new_students = db.query(User).filter(
            User.role == UserRole.student,
            User.created_at >= start, User.created_at < end
        ).all()
        new_sum = 0.0
        for ns in new_students:
            first = db.query(Payment).filter(Payment.student_id == ns.id).order_by(Payment.created_at.asc()).first()
            if first: new_sum += float(first.amount)

        earned = (active_sum * (settings.manager_active_percent / 100)) + (new_sum * (settings.manager_new_percent / 100))
        net = earned

        p = Payroll(
            user_id=m.id, role="manager", month=month,
            earned=round(earned, 2), deductions=0, net=round(net, 2),
            status="pending",
            details={"active_sum": active_sum, "new_sum": new_sum}
        )
        db.add(p)
    db.commit()

    return {"message": "Payroll calculated", "month": month}


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
def pay_salary(payroll_id: int, payload: PayIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
