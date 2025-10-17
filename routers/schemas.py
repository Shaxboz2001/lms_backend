from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
from enum import Enum


# ==============================
# ENUMLAR
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
# USER SCHEMAS
# ==============================
class UserBase(BaseModel):
    id: Optional[int] = None
    username: Optional[str]
    full_name: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    subject: Optional[str]
    fee: Optional[float]
    status: Optional[StudentStatus] = StudentStatus.studying
    role: Optional[RoleEnum] = RoleEnum.student
    age: Optional[int] = None
    group_id: Optional[int] = None
    teacher_id: Optional[int] = None

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    password: str
    role: RoleEnum
    full_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    subject: Optional[str] = None
    fee: Optional[float] = 0
    status: Optional[StudentStatus] = StudentStatus.studying
    age: Optional[int] = None
    group_id: Optional[int] = None
    teacher_id: Optional[int] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    age: Optional[int] = None
    subject: Optional[str] = None
    fee: Optional[float] = None
    status: Optional[StudentStatus] = None

    class Config:
        from_attributes = True


class UserResponse(UserBase):
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==============================
# COURSE SCHEMAS
# ==============================
class CourseBase(BaseModel):
    title: str
    subject: str
    teacher_id: int
    description: Optional[str] = None
    start_date: Optional[date] = None
    price: Optional[float] = 0.0


class CourseCreate(BaseModel):
    title: str
    subject: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = 0
    start_date: Optional[date] = None
    teacher_id: Optional[int] = None  # frontenddan keladi


class CourseOut(BaseModel):
    id: int
    title: str
    subject: Optional[str]
    description: Optional[str]
    price: Optional[float]
    start_date: Optional[date]
    teacher_name: Optional[str]
    teacher_id: Optional[int]

    class Config:
        from_attributes = True


# ==============================
# GROUP SCHEMAS
# ==============================
class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    course_id: int
    teacher_ids: Optional[List[int]] = []
    student_ids: Optional[List[int]] = []


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    course_id: Optional[int] = None
    teacher_ids: Optional[List[int]] = []
    student_ids: Optional[List[int]] = []


class GroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    course_id: Optional[int] = None
    course: Optional[CourseOut] = None
    teachers: Optional[List[UserResponse]] = []
    students: Optional[List[UserResponse]] = []

    class Config:
        from_attributes = True


# ==============================
# PAYMENT SCHEMAS
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
# ATTENDANCE SCHEMAS
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
# TEST SCHEMAS
# ==============================
class OptionCreate(BaseModel):
    text: str
    is_correct: Optional[int] = 0


class QuestionCreate(BaseModel):
    text: str
    type: str = "single"
    options: List[OptionCreate]


class TestCreate(BaseModel):
    title: str
    description: Optional[str]
    group_id: int
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
