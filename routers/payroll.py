# routers/payroll.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timezone, timedelta
from typing import List
from .dependencies import get_db
from .auth import get_current_user
from .models import User, UserRole, Payment, Attendance, Group, SalarySetting, Payroll, PayrollPayment
from .database import SessionLocal
from pydantic import BaseModel

payroll_router = APIRouter(prefix="/payroll", tags=["Payroll"])

# ---------- helpers ----------
def parse_month(month_str: str):
    # expecting 'YYYY-MM'
    try:
        year, month = month_str.split("-")
        month = int(month)
        year = int(year)
        start = datetime(year, month, 1)
        if month == 12:
            end = datetime(year + 1, 1, 1)
        else:
            end = datetime(year, month + 1, 1)
        return start, end
    except Exception:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")


# ---------- Salary settings endpoints ----------
class SalarySettingsIn(BaseModel):
    teacher_percent: float
    manager_active_percent: float
    manager_new_percent: float

@payroll_router.get("/salary/settings")
def get_salary_settings(db: Session = Depends(get_db)):
    s = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not s:
        # create defaults if none
        s = SalarySetting()
        db.add(s)
        db.commit()
        db.refresh(s)
    return {
        "teacher_percent": s.teacher_percent,
        "manager_active_percent": s.manager_active_percent,
        "manager_new_percent": s.manager_new_percent,
        "id": s.id
    }

@payroll_router.put("/salary/settings")
def update_salary_settings(payload: SalarySettingsIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin,]:
        raise HTTPException(status_code=403, detail="Only admin can update settings")
    s = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not s:
        s = SalarySetting(
            teacher_percent=payload.teacher_percent,
            manager_active_percent=payload.manager_active_percent,
            manager_new_percent=payload.manager_new_percent
        )
        db.add(s)
    else:
        s.teacher_percent = payload.teacher_percent
        s.manager_active_percent = payload.manager_active_percent
        s.manager_new_percent = payload.manager_new_percent
    db.commit()
    db.refresh(s)
    return {"message": "updated", "settings": {
        "teacher_percent": s.teacher_percent,
        "manager_active_percent": s.manager_active_percent,
        "manager_new_percent": s.manager_new_percent
    }}


# ---------- Calculate payroll ----------
@payroll_router.post("/calculate")
def calculate_payroll(month: str = Query(..., description="YYYY-MM"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # admin only
    if current_user.role not in [UserRole.admin,]:
        raise HTTPException(status_code=403, detail="Only admin can calculate payroll")

    start, end = parse_month(month)

    settings = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not settings:
        settings = SalarySetting()
        db.add(settings)
        db.commit()
        db.refresh(settings)

    # Clear existing payroll rows for that month (optional)
    existing = db.query(Payroll).filter(Payroll.month == month).all()
    for ex in existing:
        db.delete(ex)
    db.commit()

    # TEACHERS
    teachers = db.query(User).filter(User.role == UserRole.teacher).all()
    for t in teachers:
        # find groups taught by teacher
        groups = db.query(Group.id).filter(Group.teacher_id == t.id).all()
        group_ids = [g[0] for g in groups] if groups else []

        # sum payments made in month by students of those groups
        if group_ids:
            payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
                Payment.group_id.in_(group_ids),
                Payment.created_at >= start, Payment.created_at < end
            ).scalar() or 0.0
        else:
            payments_sum = 0.0

        # attendance: compute attendance rate for groups in that month (present / total)
        if group_ids:
            present = db.query(func.count(Attendance.id)).filter(
                Attendance.group_id.in_(group_ids),
                Attendance.present == True,
                Attendance.created_at >= start, Attendance.created_at < end
            ).scalar() or 0
            total = db.query(func.count(Attendance.id)).filter(
                Attendance.group_id.in_(group_ids),
                Attendance.created_at >= start, Attendance.created_at < end
            ).scalar() or 0
            attendance_rate = (present / total * 100.0) if total > 0 else 100.0
        else:
            attendance_rate = 100.0

        earned = float(payments_sum) * (settings.teacher_percent / 100.0)
        # Deduction proportional to attendance (if low attendance, pay reduced)
        deductions = earned * (1.0 - (attendance_rate / 100.0))  # if attendance=80%, deduction = 20% of earned
        net = earned - deductions

        # Save payroll row
        p = Payroll(
            user_id=t.id,
            role="teacher",
            month=month,
            earned=round(earned, 2),
            deductions=round(deductions, 2),
            net=round(net, 2),
            status="pending",
            details={
                "payments_sum": payments_sum,
                "attendance_rate": attendance_rate,
                "group_count": len(group_ids),
            }
        )
        db.add(p)
    db.commit()

    # MANAGERS
    managers = db.query(User).filter(User.role == UserRole.manager).all()
    for m in managers:
        # Manager gets:
        # 1) 10% of each active student's payments in the month (active = students who have at least one attendance present this month?)
        # 2) 25% of first payment of new students who started this month

        # Active students: students with attendance.present == True in month
        active_student_ids = db.query(Attendance.student_id).filter(
            Attendance.present == True,
            Attendance.created_at >= start, Attendance.created_at < end
        ).distinct().all()
        active_student_ids = [r[0] for r in active_student_ids]

        # sum payments of active students in month
        active_payments_sum = 0.0
        if active_student_ids:
            active_payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
                Payment.student_id.in_(active_student_ids),
                Payment.created_at >= start, Payment.created_at < end
            ).scalar() or 0.0

        # New students: users created in this month (assuming User.created_at exists)
        new_students = db.query(User).filter(
            User.role == UserRole.student,
            User.created_at >= start, User.created_at < end
        ).all()
        new_student_first_payments_sum = 0.0
        for ns in new_students:
            first_payment = db.query(Payment).filter(
                Payment.student_id == ns.id,
                Payment.created_at >= start, Payment.created_at < end
            ).order_by(Payment.created_at.asc()).first()
            if first_payment:
                new_student_first_payments_sum += float(first_payment.amount)

        earned = (float(active_payments_sum) * (settings.manager_active_percent / 100.0)) + \
                 (float(new_student_first_payments_sum) * (settings.manager_new_percent / 100.0))
        deductions = 0.0
        net = earned - deductions

        p = Payroll(
            user_id=m.id,
            role="manager",
            month=month,
            earned=round(earned, 2),
            deductions=round(deductions, 2),
            net=round(net, 2),
            status="pending",
            details={
                "active_payments_sum": active_payments_sum,
                "new_students_count": len(new_students),
                "new_students_first_payments": new_student_first_payments_sum
            }
        )
        db.add(p)
    db.commit()

    return {"message": "Payroll calculated", "month": month}


# ---------- List payroll rows ----------
@payroll_router.get("/")
def list_payroll(month: str = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin, UserRole.manager, UserRole.teacher]:
        raise HTTPException(status_code=403, detail="Not allowed")
    q = db.query(Payroll)
    if month:
        q = q.filter(Payroll.month == month)
    rows = q.all()
    # For non-admins, only return their own rows
    if current_user.role != UserRole.admin:
        rows = [r for r in rows if r.user_id == current_user.id]
    result = []
    for r in rows:
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "user_name": getattr(r.user, "full_name", None),
            "role": r.role,
            "month": r.month,
            "earned": r.earned,
            "deductions": r.deductions,
            "net": r.net,
            "status": r.status,
            "details": r.details,
            "paid_at": r.paid_at
        })
    return result


# ---------- Mark as paid ----------
@payroll_router.post("/{payroll_id}/pay")
def pay_salary(payroll_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin,]:
        raise HTTPException(status_code=403, detail="Only admin can mark paid")

    row = db.query(Payroll).filter(Payroll.id == payroll_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Payroll row not found")
    if row.status == "paid":
        raise HTTPException(status_code=400, detail="Already paid")

    row.status = "paid"
    row.paid_at = datetime.utcnow()
    db.add(PayrollPayment(payroll_id=row.id, paid_amount=row.net, paid_by=current_user.id))
    db.commit()
    db.refresh(row)
    return {"message": "Paid", "payroll_id": row.id, "net": row.net}
