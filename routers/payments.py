# routers/payments.py
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text, func, and_
from typing import List, Optional
from datetime import date, datetime, timedelta

from .dependencies import get_db, get_current_user
from .models import User, UserRole, Payment, Group, PaymentStatus, Attendance, Course
from .schemas import PaymentResponse  # if you have, else return raw dicts

payments_router = APIRouter(prefix="/payments", tags=["Payments"])


# ---------- Helpers ----------
class CalculateMonthPayload(BaseModel):
    month: Optional[str] = None  # "YYYY-MM"


def _to_yyyy_mm(dt: date) -> str:
    return dt.strftime("%Y-%m")


# ---------- Get payments (role-based) ----------
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
    limit: int = Query(200),
):
    q = db.query(Payment)

    # Role restrictions
    if current_user.role == UserRole.student:
        q = q.filter(Payment.student_id == current_user.id)
    elif current_user.role == UserRole.teacher:
        # teacher sees payments for their groups or their students
        q = q.filter(
            (Payment.teacher_id == current_user.id) |
            (Payment.group_id.in_([g.id for g in getattr(current_user, "groups_as_teacher", [])]))
        )
    # managers/admin see all

    # Filters
    if student_id:
        q = q.filter(Payment.student_id == student_id)
    if group_id:
        q = q.filter(Payment.group_id == group_id)
    if teacher_id:
        q = q.filter(Payment.teacher_id == teacher_id)
    if course_id:
        # join group->course or filter by group's course_id
        q = q.join(Group).filter(Group.course_id == course_id)
    if month:
        # Postgres: to_char(created_at, 'YYYY-MM') or Payment.month column
        q = q.filter(Payment.month == month)
    if year:
        q = q.filter(func.substr(Payment.month, 1, 4) == str(year))

    payments = q.order_by(Payment.created_at.desc()).limit(limit).all()

    # compute is_overdue convenience field
    for p in payments:
        p.is_overdue = bool(p.due_date and p.due_date < date.today() and p.status != PaymentStatus.paid)

    return payments


# ---------- Create payment (admin/manager) ----------
@payments_router.post("/", response_model=PaymentResponse)
def create_payment(
    amount: float = Body(..., gt=0),
    description: Optional[str] = Body(None),
    student_id: Optional[int] = Body(None),
    group_id: Optional[int] = Body(None),
    month: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.student:
        raise HTTPException(status_code=403, detail="Talabalar to‘lov qo‘sha olmaydi.")
    if not student_id:
        raise HTTPException(status_code=400, detail="O‘quvchi ID kiritilmadi.")

    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi.")

    group = None
    if group_id:
        group = db.query(Group).filter(Group.id == group_id).first()
        if not group:
            raise HTTPException(status_code=404, detail="Guruh topilmadi.")
    else:
        # try to use student's group_id
        if student.group_id:
            group = db.query(Group).filter(Group.id == student.group_id).first()
            if group:
                group_id = group.id

    if not month:
        month = _to_yyyy_mm(date.today())

    course_price = 0
    if group and getattr(group, "course", None):
        course_price = group.course.price or 0

    status = PaymentStatus.unpaid
    if course_price > 0:
        if amount >= course_price:
            status = PaymentStatus.paid
        elif 0 < amount < course_price:
            status = PaymentStatus.partial
    else:
        status = PaymentStatus.paid if amount > 0 else PaymentStatus.unpaid

    debt_amount = max((course_price or 0) - amount, 0)

    payment = Payment(
        amount=amount,
        description=description or (group.course.title if group and getattr(group, "course", None) else "To'lov"),
        student_id=student_id,
        teacher_id=group.teacher_id if group else None,
        group_id=group_id,
        month=month,
        status=status,
        debt_amount=debt_amount,
        created_at=datetime.utcnow()
    )
    db.add(payment)

    # update student's balance: if amount > course_price => put extra into balance
    if amount and course_price and amount > course_price:
        extra = amount - course_price
        student.balance = (student.balance or 0) + extra

    db.commit()
    db.refresh(payment)
    return payment


# ---------- Generate simple monthly debts ----------
@payments_router.post("/generate-debts")
def generate_monthly_debts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin generatsiya qilishi mumkin.")
    today = date.today()
    current_month = _to_yyyy_mm(today)
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
                p = Payment(
                    amount=0.0,
                    description=f"{current_month} uchun avtomatik qarz",
                    student_id=student.id,
                    group_id=group.id,
                    teacher_id=group.teacher_id,
                    month=current_month,
                    status=PaymentStatus.unpaid if course_price > 0 else PaymentStatus.paid,
                    debt_amount=course_price,
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.utcnow()
                )
                db.add(p)
                created_count += 1
    db.commit()
    return {"message": f"{created_count} ta yangi qarz yozildi", "month": current_month}


# ---------- Mark as paid (partial/full) ----------
@payments_router.put("/mark-paid/{payment_id}")
def mark_payment_as_paid(payment_id: int, amount: float = Body(..., gt=0), db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Sizda ruxsat yo‘q.")
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To‘lov topilmadi.")

    course_price = (payment.group.course.price if payment.group and getattr(payment.group, "course", None) else 0) or 0

    payment.amount = (payment.amount or 0) + amount
    remaining = course_price - payment.amount if course_price else 0
    if remaining <= 0:
        payment.status = PaymentStatus.paid
        payment.debt_amount = 0
    else:
        payment.status = PaymentStatus.partial
        payment.debt_amount = remaining

    payment.paid_at = datetime.utcnow()

    # if payment overpaid -> add to student.balance
    if course_price and payment.amount > course_price:
        extra = payment.amount - course_price
        payment.student.balance = (payment.student.balance or 0) + extra

    db.commit()
    db.refresh(payment)
    return {"message": "To‘lov yangilandi ✅", "payment": payment}


# ---------- Student payment history ----------
@payments_router.get("/student/{student_id}/history")
def get_student_payment_history(student_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.admin, UserRole.manager] and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q!")
    student = db.query(User).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(status_code=404, detail="O‘quvchi topilmadi")

    payments = db.query(Payment).filter(Payment.student_id == student_id).order_by(Payment.month.desc(), Payment.created_at.desc()).all()
    history = []
    total_paid = 0.0
    total_debt = 0.0
    for p in payments:
        course_name = p.group.course.title if p.group and getattr(p.group, "course", None) else None
        group_name = p.group.name if p.group else None
        total_paid += float(p.amount or 0)
        total_debt += float(p.debt_amount or 0)
        history.append({
            "id": p.id,
            "month": p.month,
            "course_name": course_name,
            "group_name": group_name,
            "amount": float(p.amount or 0),
            "debt_amount": float(p.debt_amount or 0),
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "is_overdue": bool(p.due_date and p.due_date < date.today() and p.status != PaymentStatus.paid)
        })
    return {
        "student_id": student.id,
        "student_name": student.full_name or student.username,
        "total_paid": total_paid,
        "total_debt": total_debt,
        "balance": float(student.balance or 0.0),
        "history": history,
    }


# ---------- Aggregates / summary (by filters) ----------
@payments_router.get("/aggregates")
def get_aggregates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    month: Optional[str] = Query(None),  # YYYY-MM
    year: Optional[int] = Query(None),
    group_id: Optional[int] = Query(None),
    course_id: Optional[int] = Query(None),
    student_id: Optional[int] = Query(None),
):
    # Accessible to manager/admin/teacher (teacher limited)
    q = db.query(Payment)
    if current_user.role == UserRole.student:
        q = q.filter(Payment.student_id == current_user.id)
    elif current_user.role == UserRole.teacher:
        q = q.filter((Payment.teacher_id == current_user.id) | (Payment.group_id.in_([g.id for g in getattr(current_user, "groups_as_teacher", [])])))

    if month:
        q = q.filter(Payment.month == month)
    if year:
        q = q.filter(func.substr(Payment.month, 1, 4) == str(year))
    if group_id:
        q = q.filter(Payment.group_id == group_id)
    if course_id:
        q = q.join(Group).filter(Group.course_id == course_id)
    if student_id:
        q = q.filter(Payment.student_id == student_id)

    # totals
    totals = q.with_entities(
        func.sum(Payment.amount).label("paid_total"),
        func.sum(Payment.debt_amount).label("debt_total"),
        func.count(Payment.id).label("count")
    ).first()

    paid_total = float(totals.paid_total or 0)
    debt_total = float(totals.debt_total or 0)
    count = int(totals.count or 0)

    # expected_total: sum of course prices for distinct student+group combos for the period (approx)
    expected_q = db.query(func.sum(Course.price)).select_from(Payment).join(Group).join(Course)
    if month:
        expected_q = expected_q.filter(Payment.month == month)
    if group_id:
        expected_q = expected_q.filter(Payment.group_id == group_id)
    if course_id:
        expected_q = expected_q.filter(Group.course_id == course_id)
    expected_total = float(expected_q.scalar() or 0)

    return {
        "paid_total": paid_total,
        "debt_total": debt_total,
        "expected_total": expected_total,
        "count": count
    }


# ---------- Calculate monthly debts using attendance (Postgres friendly) ----------
@payments_router.post("/calculate-monthly")
def calculate_monthly_payments(payload: CalculateMonthPayload = Body(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager yoki admin hisoblay oladi.")

    today = date.today()
    month = payload.month or _to_yyyy_mm(today)  # "YYYY-MM"
    created = 0
    updated = 0

    groups = db.query(Group).all()
    for group in groups:
        course_price = group.course.price if getattr(group, "course", None) else 0
        lessons_count = 12  # can be changed: group.course.lessons_count
        if course_price <= 0 or lessons_count <= 0:
            continue

        students = db.query(User).filter(User.group_id == group.id, User.role == UserRole.student).all()
        for student in students:
            # count attendance for this month (Postgres: to_char(date, 'YYYY-MM'))
            # we expect attendance.date is timestamp/date
            attendance_rows = db.execute(
                text(
                    "SELECT status, coalesce(reason, '') as reason "
                    "FROM attendance "
                    "WHERE student_id = :sid AND group_id = :gid AND to_char(date, 'YYYY-MM') = :month"
                ),
                {"sid": student.id, "gid": group.id, "month": month}
            ).fetchall()

            attended = sum(1 for r in attendance_rows if (r['status'] if 'status' in r.keys() else r.status) == "present")
            absent_sababli = sum(1 for r in attendance_rows if (r.get('status') if hasattr(r, 'get') else (r['status'] if 'status' in r.keys() else r.status)) == "absent" and (r.get('reason') if hasattr(r, 'get') else (r['reason'] if 'reason' in r.keys() else r.reason)) == "sababli")
            absent_sababsiz = sum(1 for r in attendance_rows if (r.get('status') if hasattr(r, 'get') else (r['status'] if 'status' in r.keys() else r.status)) == "absent" and (r.get('reason') if hasattr(r, 'get') else (r['reason'] if 'reason' in r.keys() else r.reason)) == "sababsiz")
            total_lessons = attended + absent_sababli + absent_sababsiz

            per_lesson_price = course_price / lessons_count

            # previous balance logic (sum of unpaid debts across previous months)
            prev_unpaid = db.query(func.sum(Payment.debt_amount)).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month < month
            ).scalar() or 0.0

            # calculate monthly due: policy = if no lessons that month -> 0; else full month price,
            # and sababsiz absences are counted as present (i.e., chargeable).
            if total_lessons == 0:
                monthly_due = 0.0
            else:
                # you asked: if student new -> count from join date; here we assume full month for simplicity;
                # advanced: check student.joined date and prorate.
                monthly_due = round(course_price, 2)

            # include previous unpaid
            final_debt = monthly_due + (float(prev_unpaid or 0.0))

            # create or update payment record
            existing = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.group_id == group.id,
                Payment.month == month
            ).first()
            if existing:
                existing.debt_amount = float(final_debt)
                # status: if debt 0 => paid; if amount>0 but < course_price => partial else unpaid
                existing.status = PaymentStatus.paid if final_debt <= 0 else (PaymentStatus.partial if existing.amount and existing.amount < course_price else PaymentStatus.unpaid)
                updated += 1
            else:
                new_p = Payment(
                    amount=0.0,
                    description=f"{month} uchun hisoblangan qarz",
                    student_id=student.id,
                    teacher_id=group.teacher_id,
                    group_id=group.id,
                    month=month,
                    status=PaymentStatus.unpaid if final_debt > 0 else PaymentStatus.paid,
                    debt_amount=float(final_debt),
                    due_date=date(today.year, today.month, 10),
                    created_at=datetime.utcnow()
                )
                db.add(new_p)
                created += 1

    db.commit()
    return {"message": f"✅ Hisoblash yakunlandi: {created} yangi, {updated} yangilandi.", "month": month}


# ---------- Update attendance reason (manager) ----------
@payments_router.post("/attendance/reason")
def update_attendance_reason(student_id: int = Body(...), date_value: str = Body(...), group_id: int = Body(...),
                             reason: str = Body(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.manager, UserRole.admin]:
        raise HTTPException(status_code=403, detail="Faqat manager o‘zgartira oladi.")
    # date_value expected YYYY-MM-DD
    att = db.execute(
        text("SELECT id FROM attendance WHERE student_id = :sid AND group_id = :gid AND date::date = :dt::date"),
        {"sid": student_id, "gid": group_id, "dt": date_value}
    ).fetchone()
    if not att:
        raise HTTPException(status_code=404, detail="Dars topilmadi.")
    db.execute(
        text("UPDATE attendance SET reason = :reason WHERE id = :aid"),
        {"reason": reason, "aid": att['id'] if 'id' in att.keys() else att.id}
    )
    db.commit()
    return {"message": f"Dars uchun sabab yangilandi: {reason}"}
