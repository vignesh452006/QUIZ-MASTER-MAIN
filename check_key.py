import os
from dotenv import load_dotenv

# Test if the file is being read
load_dotenv('gemini.env')
key = os.getenv("GEMINI_API_KEY")

if key:
    print(f"SUCCESS: Found API Key starting with: {key[:8]}...")
else:
    print("FAILURE: gemini.env not found or GEMINI_API_KEY is missing inside it.")