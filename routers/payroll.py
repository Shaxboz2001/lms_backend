from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from pydantic import BaseModel

from .dependencies import get_db
from .auth import get_current_user
from .models import (
    User, UserRole, Payment, Group,
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
        s = SalarySetting(
            teacher_percent=50,
            manager_active_percent=10,
            manager_new_percent=25
        )
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
        raise HTTPException(status_code=403, detail="Only admin can update settings")

    s = db.query(SalarySetting).order_by(SalarySetting.id.desc()).first()
    if not s:
        s = SalarySetting(**payload.dict())
        db.add(s)
    else:
        for key, val in payload.dict().items():
            setattr(s, key, val)
    db.commit()
    db.refresh(s)
    return {"message": "Settings updated ✅", "settings": payload.dict()}


# -------- Per-Teacher Percent --------
class TeacherPercentIn(BaseModel):
    teacher_percent: float


@payroll_router.put("/teacher-percent/{teacher_id}")
def update_teacher_percent(
    teacher_id: int,
    payload: TeacherPercentIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Admin can assign a custom percent for an individual teacher"""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Only admin can update")

    teacher = db.query(User).filter(User.id == teacher_id, User.role == UserRole.teacher).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    teacher.teacher_percent = payload.teacher_percent
    db.commit()
    db.refresh(teacher)

    return {
        "message": f"Teacher {teacher.full_name or teacher.username} percent updated",
        "teacher_id": teacher.id,
        "teacher_percent": teacher.teacher_percent
    }


@payroll_router.get("/teacher-percent/{teacher_id}")
def get_teacher_percent(
    teacher_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get teacher-specific percent"""
    teacher = db.query(User).filter(User.id == teacher_id, User.role == UserRole.teacher).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    return {
        "teacher_id": teacher.id,
        "teacher_name": teacher.full_name,
        "teacher_percent": teacher.teacher_percent
    }


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
        settings = SalarySetting(teacher_percent=50, manager_active_percent=10, manager_new_percent=25)
        db.add(settings)
        db.commit()
        db.refresh(settings)

    db.query(Payroll).filter(Payroll.month == month).delete()
    db.commit()

    # ------------------------
    # 🎓 TEACHERS
    # ------------------------
    teachers = db.query(User).filter(User.role == UserRole.teacher).all()
    for t in teachers:
        group_ids = [g.id for g in db.query(Group).filter(Group.teacher_id == t.id).all()]
        if not group_ids:
            continue

        total_group_payments = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.group_id.in_(group_ids),
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0.0

        # Use teacher custom percent if available
        teacher_percent = t.teacher_percent if t.teacher_percent is not None else settings.teacher_percent
        earned = total_group_payments * (teacher_percent / 100.0)

        db.add(Payroll(
            user_id=t.id,
            role="teacher",
            month=month,
            earned=round(earned, 2),
            deductions=0.0,
            net=round(earned, 2),
            status="pending",
            details={
                "total_group_payments": total_group_payments,
                "teacher_percent_used": teacher_percent,
                "groups_count": len(group_ids)
            }
        ))

    db.commit()

    # ------------------------
    # 🧑‍💼 MANAGERS
    # ------------------------
    managers = db.query(User).filter(User.role == UserRole.manager).all()
    for m in managers:
        month_payments_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0.0

        # Find new students (first payment within month)
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

        new_students_first_sum = db.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            Payment.student_id.in_(new_student_ids) if new_student_ids else False,
            Payment.created_at >= start,
            Payment.created_at < end
        ).scalar() or 0.0

        earned = (
            month_payments_sum * (settings.manager_active_percent / 100.0)
        ) + (
            new_students_first_sum * (settings.manager_new_percent / 100.0)
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
                "month_payments_sum": month_payments_sum,
                "new_students_first_sum": new_students_first_sum,
                "active_percent": settings.manager_active_percent,
                "new_percent": settings.manager_new_percent,
                "new_students_count": len(new_student_ids)
            }
        ))

    db.commit()

    return {"message": f"Payroll calculated successfully for {month}"}


# -------- List Payroll --------
@payroll_router.get("/")
def list_payroll(
    month: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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
            "details": r.details,
            "userid": r.user_id
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

    return {"message": "Salary marked as paid 💰", "id": row.id, "paid_amount": payload.paid_amount}
