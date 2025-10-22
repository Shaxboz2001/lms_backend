import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from routers.database import  engine, Base
from routers import (
    auth_router,
    attend_router,
    payments_router,
    groups_router,
    courses_router,
    students_router,
    teachers_router,
    tests_router,
    users_router,
    dashboard_router,
    reports_router
)
app = FastAPI(title="LMS Backend")

origins = [
    "http://localhost:5173",  # React dev server
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://ilmnajot-lms.vercel.app",
    "https://www.ilmnajot-lms.vercel.app",
    "http://localhost:5173",  # dev uchun
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # Qaysi domenlarga ruxsat beriladi
    allow_credentials=True,
    allow_methods=["*"],         # Barcha metodlarga ruxsat (GET, POST, PUT, DELETE)
    allow_headers=["*"],         # Barcha header’lar uchun
)

Base.metadata.create_all(bind=engine)

app.include_router(auth_router)
app.include_router(attend_router)
app.include_router(payments_router)
app.include_router(courses_router)
app.include_router(groups_router)
app.include_router(tests_router)
app.include_router(students_router)
app.include_router(teachers_router)
app.include_router(users_router)
app.include_router(dashboard_router)
app.include_router(reports_router)



@app.get("/")
def home():
    return {"message": "LMS backend is running"}

if '__name__' == "__main__":
    uvicorn.run(host='127.0.0.1', port='8001')
