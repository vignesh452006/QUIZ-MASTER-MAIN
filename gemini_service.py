import os
import requests
import json
from dotenv import load_dotenv

# Ensure we load from the correct environment file
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, 'gemini.env'))

class QuizGenerator:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in gemini.env")

    def generate_quiz(self, topic, num_q):
        """
        Generates a quiz using the current Gemini 2.5 Flash model.
        Note: gemini-1.5-flash was retired and will always return a 404.
        """
        # 2026 Stable Endpoint and Model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.api_key}"
        
        prompt = (
            f"Generate exactly {num_q} multiple choice questions about {topic}. "
            "Return the response as a valid JSON array of objects. "
            "Format: [{\"question\": \"text\", \"options\": [\"a\", \"b\", \"c\", \"d\"], \"answer\": 0}]"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "responseMimeType": "application/json"
            }
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    # Clean up any potential markdown formatting
                    clean_json = raw_text.replace("```json", "").replace("```", "").strip()
                    return json.loads(clean_json)
            
            # Print specific error to terminal for debugging
            print(f"API ERROR ({response.status_code}): {response.text}")
            
            # Optional: Fallback to Gemini 3 if 2.5 fails
            if response.status_code == 404:
                print("2.5 Flash not found, trying gemini-3-flash-preview...")
                url_3 = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={self.api_key}"
                response = requests.post(url_3, json=payload, timeout=30)
                if response.status_code == 200:
                    raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(raw_text.replace("```json", "").replace("```", "").strip())

            return []
                
        except Exception as e:
            print(f"SYSTEM ERROR: {e}")
            return []