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
            "submitted_at": attempt.attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
            "student_id": attempt.student_id
        })

    return {"test_name": test.title, "results": output}

@tests_router.get("/{test_id}/detailed_result/{student_id}")
def get_detailed_test_result(
    test_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1️⃣ Testni topamiz
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # 2️⃣ Faqat testni yaratgan teacher yoki student o‘zi kirishi mumkin
    if current_user.role == UserRole.teacher:
        if test.created_by != current_user.id:
            raise HTTPException(status_code=403, detail="Siz bu testni ko‘ra olmaysiz")
    elif current_user.role == UserRole.student:
        if current_user.id != student_id:
            raise HTTPException(status_code=403, detail="Siz faqat o‘zingizning natijangizni ko‘ra olasiz")
    else:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")

    # 3️⃣ Testdagi savollarni olish
    questions = db.query(Question).filter(Question.test_id == test_id).all()

    # 4️⃣ Studentning eng so‘nggi urinish vaqtini topamiz
    last_attempt_time = (
        db.query(func.max(StudentAnswer.submitted_at))
        .filter(StudentAnswer.student_id == student_id)
        .filter(StudentAnswer.question_id.in_([q.id for q in questions]))
        .scalar()
    )

    if not last_attempt_time:
        raise HTTPException(status_code=404, detail="Student hali bu testni topshirmagan")

    # 5️⃣ Shu urinishdagi barcha javoblarini olish
    student_answers = (
        db.query(StudentAnswer)
        .filter(
            StudentAnswer.student_id == student_id,
            StudentAnswer.question_id.in_([q.id for q in questions]),
            func.date_trunc('second', StudentAnswer.submitted_at) == func.date_trunc('second', last_attempt_time)
        )
        .all()
    )

    # 6️⃣ Batafsil natijani tuzamiz
    detailed_result = []
    for q in questions:
        options = db.query(Option).filter(Option.question_id == q.id).all()

        selected_answer = next((a for a in student_answers if a.question_id == q.id), None)
        selected_option_id = selected_answer.selected_option_id if selected_answer else None

        # To‘g‘ri javobni aniqlaymiz
        correct_option = next((o for o in options if o.is_correct), None)

        detailed_result.append({
            "question_text": q.text,
            "options": [
                {
                    "id": o.id,
                    "text": o.text,
                    "is_correct": bool(o.is_correct),
                    "is_selected": (o.id == selected_option_id)
                } for o in options
            ],
            "is_answer_correct": (
                correct_option and selected_option_id == correct_option.id
            )
        })

    # 7️⃣ Yakuniy hisob
    correct_count = sum(1 for q in detailed_result if q["is_answer_correct"])
    total = len(detailed_result)
    percentage = round((correct_count / total) * 100, 2)

    return {
        "test_name": test.title,
        "student_id": student_id,
        "student_name": db.query(User.full_name).filter(User.id == student_id).scalar(),
        "submitted_at": last_attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
        "correct_count": correct_count,
        "total": total,
        "percentage": percentage,
        "details": detailed_result
    }

# ✅ Student o‘zining test natijasini ko‘rishi uchun
@tests_router.get("/{test_id}/my_result")
def get_my_result(
    test_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="Faqat student uchun")

    # testni topamiz
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test topilmadi")

    # studentning so‘nggi urinish vaqtini topamiz
    last_attempt_time = (
        db.query(func.max(StudentAnswer.submitted_at))
        .filter(StudentAnswer.student_id == current_user.id)
        .filter(
            StudentAnswer.question_id.in_(
                db.query(Question.id).filter(Question.test_id == test_id)
            )
        )
        .scalar()
    )

    if not last_attempt_time:
        raise HTTPException(status_code=404, detail="Siz bu testni hali topshirmagansiz")

    # shu urinishdagi javoblarini olish
    answers = (
        db.query(StudentAnswer)
        .filter(
            StudentAnswer.student_id == current_user.id,
            StudentAnswer.question_id.in_(
                db.query(Question.id).filter(Question.test_id == test_id)
            ),
            func.date_trunc('second', StudentAnswer.submitted_at)
            == func.date_trunc('second', last_attempt_time)
        )
        .all()
    )

    total = db.query(Question).filter(Question.test_id == test_id).count()

    # to‘g‘ri javoblarni sanaymiz
    correct = 0
    for a in answers:
        opt = db.query(Option).filter(Option.id == a.selected_option_id).first()
        if opt and opt.is_correct:
            correct += 1

    return {
        "test_id": test.id,
        "test_name": test.title,
        "student_name": current_user.full_name,
        "score": correct,
        "total": total,
        "submitted_at": last_attempt_time.strftime("%Y-%m-%d %H:%M:%S"),
    }


