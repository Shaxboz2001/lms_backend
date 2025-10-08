from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from enum import Enum
from datetime import date


# ==============================
# Role va Student status enumlari
# ==============================
class RoleEnum(str, Enum):
    admin = "admin"
    teacher = "teacher"
    manager = "manager"
    student = "student"


class StudentStatus(str, Enum):
    interested = "interested"
    studying = "studying"
    left = "left"
    graduated = "graduated"


# ==============================
# User schemas
# ==============================
class UserBase(BaseModel):
    username: Optional[str]
    full_name: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    subject: Optional[str]
    fee: Optional[float]
    status: Optional[StudentStatus] = StudentStatus.studying
    group_id: Optional[int] = None          # ✅ optional
    teacher_id: Optional[int] = None        # ✅ optional
    role: Optional[RoleEnum] = RoleEnum.student
    age: Optional[int] = None

    class Config:
        from_attributes = True


class UserCreate(UserBase):
    username: str
    password: Optional[str] = "1234"        # ✅ default password


class UserResponse(UserBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==============================
# Group schemas
# ==============================
class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    student_ids: Optional[List[int]] = []
    teacher_ids: Optional[List[int]] = []


class GroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    student_ids: List[int] = []
    teacher_ids: List[int] = []

    class Config:
        from_attributes = True


# ==============================
# Payment schemas
# ==============================
class PaymentBase(BaseModel):
    amount: float
    description: Optional[str] = None
    student_id: Optional[int] = None
    teacher_id: Optional[int] = None
    group_id: Optional[int] = None


class PaymentCreate(PaymentBase):
    month: Optional[str] = None


class PaymentResponse(PaymentBase):
    id: int
    created_at: datetime
    month: Optional[str] = None
    student: Optional[UserResponse] = None
    teacher: Optional[UserResponse] = None
    group: Optional[GroupResponse] = None

    class Config:
        from_attributes = True


# ==============================
# Attendance schemas
# ==============================
class AttendanceCreate(BaseModel):
    student_id: int
    is_present: bool


class AttendanceResponse(BaseModel):
    id: int
    student_id: int
    teacher_id: int
    group_id: int
    date: datetime
    status: str

    class Config:
        from_attributes = True


# ==============================
# Test schemas
# ==============================
class OptionCreate(BaseModel):
    text: str
    is_correct: Optional[int] = 0   # ✅ integer (0 yoki 1) sifatida saqlanadi


class QuestionCreate(BaseModel):
    text: str
    type: str = "single"
    options: List[OptionCreate]


class TestCreate(BaseModel):
    title: str
    description: Optional[str]
    group_id: int                    # ✅ test aniq bir guruh uchun
    questions: List[QuestionCreate]


class OptionResponse(BaseModel):
    id: int
    text: str
    is_correct: Optional[int] = 0

    class Config:
        from_attributes = True


class QuestionResponse(BaseModel):
    id: int
    text: str
    type: str
    options: List[OptionResponse]

    class Config:
        from_attributes = True


class TestResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    group_id: int
    questions: List[QuestionResponse]

    class Config:
        from_attributes = True


class StudentAnswerCreate(BaseModel):
    question_id: int
    selected_option_id: int
class AnswerItem(BaseModel):
    question_id: int
    option_id: int
class TestSubmit(BaseModel):
    answers: List[AnswerItem]


class TestResultResponse(BaseModel):
    student_name: str
    score: int
    total: int

    class Config:
        orm_mode = True


class CourseBase(BaseModel):
    title: str
    description: str
    start_date: date | None = None
    end_date: date | None = None
    price: float | None = None


class CourseCreate(CourseBase):
    pass


class CourseOut(CourseBase):
    id: int
    creator_id: int
    creator_name: str | None = None

    class Config:
        from_attributes = True  # ✅ Pydantic v2 uchun to‘g‘ri variant