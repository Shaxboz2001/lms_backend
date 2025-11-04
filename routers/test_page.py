from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from .dependencies import get_db
from .auth import get_current_user
from .models import (
    UserRole, Test, User, Question, Option, group_students,
    StudentAnswer, Group, TestGroup
)
from .schemas import TestResponse, TestCreate, TestSubmit, TestUpdate

tests_router = APIRouter(prefix="/tests", tags=["Tests"])


# ✅ Test yaratish (Teacher)
@tests_router.post("/", response_model=TestResponse)
def create_test(
    test: TestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.teacher:
        raise HTTPException(status_code=403, detail="Faqat teacher test yaratishi mumkin")

    db_test = Test(
        title=test.title,
        description=test.description,
        created_by=current_user.id,
        created_at=datetime.utcnow()
    )
    db.add(db_test)
    db.commit()
    db.refresh(db_test)

    # ✅ Ko‘p guruhlarni biriktirish
    for group_id in test.group_ids:
        db.add(TestGroup(test_id=db_test.id, group_id=group_id))
    db.commit()

    # ✅ Savollarni qo‘shish
    for q in test.questions:
        db_question = Question(test_id=db_test.id, text=q.text)
        db.add(db_question)
        db.commit()
        db.refresh(db_question)

        for opt in q.options:
            db_option = Option(
                question_id=db_question.id,
                text=opt.text,
                is_correct=int(opt.is_correct)
            )
            db.add(db_option)
        db.commit()

    return db_test


# ✅ Testlarni olish
@tests_router.get("/", response_model=List[TestResponse])
def get_my_tests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Test).distinct()

    if current_user.role == UserRole.student:
        group_ids = [g.id for g in current_user.groups_as_student]
        if not group_ids:
            return []
        # 🔹 Many-to-Many orqali filter
        query = query.join(TestGroup).filter(TestGroup.group_id.in_(group_ids))

    elif current_user.role == UserRole.teacher:
        group_ids = [g.id for g in current_user.groups_as_teacher]
        if not group_ids:
            return []
        query = query.join(TestGroup).filter(TestGroup.group_id.in_(group_ids))

    elif current_user.role in [UserRole.admin, UserRole.manager]:
        # 🔹 admin/manager barcha testlarni ko‘radi
        return query.all()

    else:
        return []

    return query.all()



# ✅ Testni olish (Student uchun)
@tests_router.get("/{test_id}", response_model=TestResponse)
def get_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # Admin va manager hamma testlarni ko'rishi mumkin
    if current_user.role in [UserRole.admin, UserRole.manager]:
        return test

    # STUDENT ruxsat tekshiruvi
    if current_user.role == UserRole.student:
        # student's group ids (relationship orqali yoki junction jadvalidan)
        student_group_ids = [g.id for g in current_user.groups_as_student]

        # agar studentda guruhlar bo'lmasa - ruxsat yo'q
        if not student_group_ids:
            raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")

        # 1) agar test.group_id eski (direct) maydonda bo'lsa tekshiramiz
        if test.group_id in student_group_ids:
            return test

        # 2) yoki TestGroup orqali biriktirilgan guruhlar orasida studentning guruhlari bor-yo'qligini tekshiramiz
        tg = db.query(TestGroup).filter(
            TestGroup.test_id == test_id,
            TestGroup.group_id.in_(student_group_ids)
        ).first()

        if tg:
            return test

        raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")

    # TEACHER ruxsat tekshiruvi
    if current_user.role == UserRole.teacher:
        # teacher yaratgan testni ko'ra oladi
        if test.created_by == current_user.id:
            return test

        # teacher'ning guruhlari
        teacher_group_ids = [g.id for g in current_user.groups_as_teacher]
        if teacher_group_ids:
            # direct group_id bilan tekshiruv (backward compat)
            if test.group_id in teacher_group_ids:
                return test

            # yoki TestGroup orqali biriktirilgan bo'lsa
            tg = db.query(TestGroup).filter(
                TestGroup.test_id == test_id,
                TestGroup.group_id.in_(teacher_group_ids)
            ).first()

            if tg:
                return test

        # agarda yuqoridagi shartlardan hech biri bajarilmasa - ruxsat yo'q
        raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")

    # default - ruxsat yo'q
    raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")

# ✅ Testni yuborish (Student)
@tests_router.post("/{test_id}/submit")
def submit_test(
    test_id: int,
    answers: TestSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat studentlar test topshira oladi")

    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    tashkent_time = datetime.now(timezone(timedelta(hours=5)))
    score = 0

    for ans in answers.answers:
        option = db.query(Option).filter(Option.id == ans.option_id).first()
        if option and option.is_correct:
            score += 1

        db_answer = StudentAnswer(
            student_id=current_user.id,
            question_id=ans.question_id,
            selected_option_id=ans.option_id,
            submitted_at=tashkent_time
        )
        db.add(db_answer)

    db.commit()
    total = db.query(Question).filter(Question.test_id == test_id).count()

    return {
        "student_name": current_user.full_name,
        "score": score,
        "total": total,
        "submitted_at": tashkent_time.strftime("%Y-%m-%d %H:%M:%S")
    }


# ✅ Teacher uchun natijalar
@tests_router.get("/{test_id}/results")
def get_test_results(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    if current_user.role != UserRole.teacher or test.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Siz bu testning natijalarini ko‘ra olmaysiz")

    total_questions = db.query(Question).filter(Question.test_id == test_id).count()

    attempts = (
        db.query(
            StudentAnswer.student_id,
            User.full_name,
            func.date_trunc('second', StudentAnswer.submitted_at).label("attempt_time")
        )
        .join(User, User.id == StudentAnswer.student_id)
        .filter(
            StudentAnswer.question_id.in_(
                db.query(Question.id).filter(Question.test_id == test_id)
            )
        )
        .distinct(StudentAnswer.student_id, func.date_trunc('second', StudentAnswer.submitted_at))
        .all()
    )

    output = []
    for attempt in attempts:
        student_answers = db.query(StudentAnswer).filter(
            StudentAnswer.student_id == attempt.student_id,
            StudentAnswer.question_id.in_(
                db.query(Question.id).filter(Question.test_id == test_id)
            ),
            func.date_trunc('second', StudentAnswer.submitted_at) == attempt.attempt_time
        ).all()

        correct = sum(
            1 for a in student_answers
            if db.query(Option).filter(Option.id == a.selected_option_id, Option.is_correct == 1).first()
        )

        group_info = (
            db.query(Group.name)
            .join(group_students, group_students.c.group_id == Group.id)
            .filter(group_students.c.student_id == attempt.student_id)
            .first()
        )

        output.append({
            "student_name": attempt.full_name,
            "group_name": group_info[0] if group_info else None,
            "score": correct,
            "total": total_questions,
            "submitted_at": attempt.attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
            "student_id": attempt.student_id
        })

    return {"test_name": test.title, "results": output, 'test_id': test.id}


# ✅ Batafsil natija (student/teacher)
@tests_router.get("/{test_id}/detailed_result/{student_id}")
def get_detailed_test_result(
    test_id: int,
    student_id: int,
    submitted_at: Optional[str] = Query(None, description="YYYY-MM-DD HH:MM:SS"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    if current_user.role == UserRole.teacher:
        if test.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    elif current_user.role == UserRole.student:
        if current_user.id != student_id:
            raise HTTPException(status_code=403, detail="Siz faqat o‘zingizni ko‘ra olasiz")
    else:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")

    questions = db.query(Question).filter(Question.test_id == test_id).all()
    q_ids = [q.id for q in questions]

    if submitted_at:
        try:
            attempt_time = datetime.strptime(submitted_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            raise HTTPException(status_code=400, detail="submitted_at noto‘g‘ri formatda")
    else:
        attempt_time = (
            db.query(func.max(StudentAnswer.submitted_at))
            .filter(StudentAnswer.student_id == student_id)
            .filter(StudentAnswer.question_id.in_(q_ids))
            .scalar()
        )
        if not attempt_time:
            raise HTTPException(status_code=404, detail="Student hali bu testni topshirmagan")

    student_answers = db.query(StudentAnswer).filter(
        StudentAnswer.student_id == student_id,
        StudentAnswer.question_id.in_(q_ids),
        func.date_trunc('second', StudentAnswer.submitted_at) == func.date_trunc('second', attempt_time)
    ).all()

    detailed_result = []
    for q in questions:
        options = db.query(Option).filter(Option.question_id == q.id).all()
        selected_answer = next((a for a in student_answers if a.question_id == q.id), None)
        selected_id = selected_answer.selected_option_id if selected_answer else None
        correct_option = next((o for o in options if o.is_correct), None)

        detailed_result.append({
            "question_text": q.text,
            "options": [
                {
                    "id": o.id,
                    "text": o.text,
                    "is_correct": bool(o.is_correct),
                    "is_selected": o.id == selected_id
                } for o in options
            ],
            "is_answer_correct": (correct_option and selected_id == correct_option.id)
        })

    correct_count = sum(1 for q in detailed_result if q["is_answer_correct"])
    total = len(detailed_result)
    percentage = round((correct_count / total) * 100, 2)

    return {
        "test_name": test.title,
        "student_id": student_id,
        "student_name": db.query(User.full_name).filter(User.id == student_id).scalar(),
        "submitted_at": attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
        "correct_count": correct_count,
        "total": total,
        "percentage": percentage,
        "details": detailed_result
    }


# ✅ Student o‘z natijasini ko‘rish
@tests_router.get("/{test_id}/my_result")
def get_my_result(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat student uchun")

    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    last_time = (
        db.query(func.max(StudentAnswer.submitted_at))
        .filter(StudentAnswer.student_id == current_user.id)
        .filter(
            StudentAnswer.question_id.in_(
                db.query(Question.id).filter(Question.test_id == test_id)
            )
        )
        .scalar()
    )
    if not last_time:
        raise HTTPException(status_code=404, detail="Hali test yechmagansiz")

    answers = db.query(StudentAnswer).filter(
        StudentAnswer.student_id == current_user.id,
        StudentAnswer.question_id.in_(
            db.query(Question.id).filter(Question.test_id == test_id)
        ),
        func.date_trunc('second', StudentAnswer.submitted_at) == func.date_trunc('second', last_time)
    ).all()

    correct = sum(
        1 for a in answers
        if db.query(Option).filter(Option.id == a.selected_option_id, Option.is_correct == 1).first()
    )
    total = db.query(Question).filter(Question.test_id == test_id).count()

    return {
        "test_id": test.id,
        "test_name": test.title,
        "student_name": current_user.full_name,
        "score": correct,
        "total": total,
        "submitted_at": last_time.strftime("%Y-%m-%d %H:%M:%S")
    }


# ✅ Studentning barcha urinishlari
@tests_router.get("/{test_id}/my_attempts")
def get_my_attempts(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat student uchun")

    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    question_ids = [q.id for q in db.query(Question).filter(Question.test_id == test_id).all()]
    if not question_ids:
        return {"test_id": test_id, "attempts": []}  # ✅ test_id shu yerda

    attempts = (
        db.query(func.date_trunc('second', StudentAnswer.submitted_at).label("attempt_time"))
        .filter(StudentAnswer.student_id == current_user.id)
        .filter(StudentAnswer.question_id.in_(question_ids))
        .group_by("attempt_time")
        .order_by(func.max(StudentAnswer.submitted_at).desc())
        .all()
    )

    total_questions = len(question_ids)
    output = []
    for a in attempts:
        attempt_time = a.attempt_time
        answers = db.query(StudentAnswer).filter(
            StudentAnswer.student_id == current_user.id,
            StudentAnswer.question_id.in_(question_ids),
            func.date_trunc('second', StudentAnswer.submitted_at) == func.date_trunc('second', attempt_time)
        ).all()

        correct = sum(
            1 for ans in answers
            if db.query(Option).filter(Option.id == ans.selected_option_id, Option.is_correct == 1).first()
        )

        output.append({
            "submitted_at": attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
            "score": correct,
            "total": total_questions
        })

    # ✅ test_id umumiy javobda qaytariladi
    return {"test_id": test_id, "attempts": output}

# ✅ TESTNI YANGILASH (TEACHER)
@tests_router.put("/{test_id}")
def update_test(test_id: int, data: TestUpdate, db: Session = Depends(get_db)):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    test.title = data.title
    test.description = data.description

    # Eski bog‘lanishlarni tozalaymiz
    db.query(TestGroup).filter(TestGroup.test_id == test.id).delete()

    # Yangi guruhlarni biriktiramiz
    for gid in data.group_ids:
        db.add(TestGroup(test_id=test.id, group_id=gid))

    db.commit()
    return {"message": "✅ Test yangilandi"}
