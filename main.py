from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI
from bson import ObjectId
from datetime import datetime
import os
import json

from db import interviews_collection

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# START INTERVIEW
# ---------------------------
@app.post("/start-interview")
def start_interview():
    first_question = "Tell me about yourself."

    result = interviews_collection.insert_one({
        "role": "Backend Developer",
        "current_question": first_question,
        "history": [],
        "created_at": datetime.utcnow()
    })

    return {
        "interview_id": str(result.inserted_id),
        "question": first_question
    }

# ---------------------------
# SUBMIT ANSWER
# ---------------------------
@app.post("/submit-answer")
async def submit_answer(interview_id: str, file: UploadFile = File(...)):
    
    # Save audio
    with open("temp_audio.webm", "wb") as f:
        f.write(await file.read())

    # 🎧 Speech → Text
    with open("temp_audio.webm", "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio_file
        )

    user_text = transcript.text

    # Get current interview
    interview = interviews_collection.find_one({"_id": ObjectId(interview_id)})
    current_question = interview["current_question"]

    # 🧠 AI Evaluation
    ai_response = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "You are a professional technical interviewer."
            },
            {
                "role": "user",
                "content": f"""
Question: {current_question}
Answer: {user_text}

Evaluate the answer (score out of 10 + feedback)
Then ask next interview question.

Return JSON:
{{
  "score": number,
  "feedback": "text",
  "next_question": "text"
}}
"""
            }
        ]
    )

    result = json.loads(ai_response.choices[0].message.content)

    # 💾 Update DB
    interviews_collection.update_one(
        {"_id": ObjectId(interview_id)},
        {
            "$push": {
                "history": {
                    "question": current_question,
                    "answer": user_text,
                    "score": result["score"],
                    "feedback": result["feedback"],
                    "timestamp": datetime.utcnow()
                }
            },
            "$set": {
                "current_question": result["next_question"]
            }
        }
    )

    return {
        "transcript": user_text,
        "score": result["score"],
        "feedback": result["feedback"],
        "next_question": result["next_question"]
    }

# ---------------------------
# GET RESULTS
# ---------------------------
@app.get("/results")
def get_results():
    interviews = list(interviews_collection.find({}))

    for interview in interviews:
        interview["_id"] = str(interview["_id"])

    return interviews