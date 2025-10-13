from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from datetime import datetime,  timezone, timedelta
from .dependencies import get_db
from .auth import get_current_user
from .models import UserRole, Test, User, Question, Option, group_students, StudentAnswer, Group
from .schemas import TestResponse, TestCreate, TestSubmit


tests_router = APIRouter(prefix="/tests", tags=["Tests"])


# ✅ Test yaratish (Teacher)
@tests_router.post("/", response_model=TestResponse)
def create_test(test: TestCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.teacher:
        raise HTTPException(status_code=403, detail="Faqat teacher test yaratishi mumkin")

    db_test = Test(
        title=test.title,
        description=test.description,
        created_by=current_user.id,  # testni kim yaratgan
        group_id=test.group_id,
        created_at=datetime.utcnow()
    )
    db.add(db_test)
    db.commit()
    db.refresh(db_test)

    for q in test.questions:
        db_question = Question(
            test_id=db_test.id,
            text=q.text
        )
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


# ✅ Testlarni olish (Teacher yoki Student)
@tests_router.get("/", response_model=List[TestResponse])
def get_my_tests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == UserRole.student:
        group_ids = [g.id for g in current_user.groups_as_student]
    elif current_user.role == UserRole.teacher:
        group_ids = [g.id for g in current_user.groups_as_teacher]
    elif current_user.role in [UserRole.admin, UserRole.manager]:
        return db.query(Test).all()
    else:
        return []

    if not group_ids:
        return []
    tests = db.query(Test).filter(Test.group_id.in_(group_ids)).all()
    return tests


# ✅ Testni ID orqali olish (Student yechishi uchun)
@tests_router.get("/{test_id}", response_model=TestResponse)
def get_test(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # 👇 Student testni ko‘ra oladimi?
    if current_user.role == UserRole.student:
        student_groups = (
            db.query(group_students.c.group_id)
            .filter(group_students.c.student_id == current_user.id)
            .all()
        )
        student_group_ids = [g[0] for g in student_groups]

        if test.group_id not in student_group_ids:
            raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")

    return test


# ✅ Testni javobini yuborish (Student)
@tests_router.post("/{test_id}/submit")
def submit_test(
    test_id: int,
    answers: TestSubmit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat studentlar test topshira oladi")

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
            submitted_at=tashkent_time  # ✅ Toshkent vaqti
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


@tests_router.get("/{test_id}/results")
def get_test_results(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1️⃣ Testni topamiz
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # 2️⃣ Faqat testni yaratgan o‘qituvchi ko‘ra oladi
    if current_user.role != UserRole.teacher or test.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Siz bu testning natijalarini ko‘ra olmaysiz")

    # 3️⃣ Testdagi savollar soni
    total_questions = db.query(Question).filter(Question.test_id == test_id).count()

    # 4️⃣ Studentlarning barcha urinishlarini olish
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
        # Har bir studentning aynan shu urinishdagi javoblarini olish
        student_answers = (
            db.query(StudentAnswer)
            .filter(
                StudentAnswer.student_id == attempt.student_id,
                StudentAnswer.question_id.in_(
                    db.query(Question.id).filter(Question.test_id == test_id)
                ),
                func.date_trunc('second', StudentAnswer.submitted_at) == attempt.attempt_time
            )
            .all()
        )

        # To‘g‘ri javoblarni hisoblash
        correct = 0
        for ans in student_answers:
            option = db.query(Option).filter(Option.id == ans.selected_option_id).first()
            if option and option.is_correct:
                correct += 1

        # Studentning guruhi
        group_info = (
            db.query(Group.name)
            .join(group_students, group_students.c.group_id == Group.id)
            .filter(group_students.c.student_id == attempt.student_id)
            .first()
        )
        group_name = group_info[0] if group_info else None

        output.append({
            "student_name": attempt.full_name,
            "group_name": group_name,
            "score": correct,
            "total": total_questions,
            "submitted_at": attempt.attempt_time.strftime("%Y-%m-%d %H:%M:%S")
        })

    return {"test_name": test.title, "results": output}

