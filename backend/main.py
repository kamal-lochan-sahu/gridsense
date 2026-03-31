from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os

# .env file se variables load karo
load_dotenv()

# FastAPI app banao
app = FastAPI(
    title="GridSense API",
    description="Real-Time Industrial Energy Intelligence Platform",
    version="1.0.0"
)

# CORS — frontend ko backend se baat karne deta hai
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Test route
@app.get("/")
def root():
    return {"message": "GridSense API is running!"}

# Health check route
@app.get("/health")
def health():
    return {"status": "ok"}