from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from .routers import auth, dashboard
from .database import Base, engine
from .routers import users
from .routers import groups
from .routers import payments
from .routers import students
from .routers import attendance
from .routers import teachers
from .routers import tests
from .routers import courses

app = FastAPI(title="LMS Backend")

origins = [
    "http://localhost:5173",  # React dev server
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # Qaysi domenlarga ruxsat beriladi
    allow_credentials=True,
    allow_methods=["*"],         # Barcha metodlarga ruxsat (GET, POST, PUT, DELETE)
    allow_headers=["*"],         # Barcha header’lar uchun
)

Base.metadata.create_all(bind=engine)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(payments.router)
app.include_router(users.router)
app.include_router(groups.router)
app.include_router(students.router)
app.include_router(attendance.router)
app.include_router(teachers.router)
app.include_router(tests.router)
app.include_router(courses.router)


@app.get("/")
def home():
    return {"message": "LMS backend is running"}
