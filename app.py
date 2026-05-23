import os
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from gtts import gTTS
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static')
CORS(app)

# 1. INITIALIZE KEY POOL (Make sure NO placeholder text remains)
API_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2"),
    os.getenv("GEMINI_KEY_3"),
    os.getenv("GEMINI_KEY_4"),
    os.getenv("GEMINI_KEY_5")
]

# Track the index of the currently active key globally
current_key_index = 0

def get_gemini_client(force_next=False):
    """Fetches a client using the current active key or rotates to the next one if forced."""
    global current_key_index
    
    if force_next:
        current_key_index = (current_key_index + 1) % len(API_KEYS)
        print(f"🔄 Rate limit hit! Rotating to API Key Index: {current_key_index}")
        
    return genai.Client(api_key=API_KEYS[current_key_index])

LOG_FILE = "conversation_logs.json"

def save_log(user_text, bot_text):
    """Stores chat history in JSON format for assignment evaluation."""
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "user": user_text,
        "bot": bot_text
    }
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(log_entry)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving logs: {e}")

def get_recent_history_context(max_turns=3):
    """Reads conversation_logs.json to build context history for Gemini."""
    context_str = ""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
            
            # Take the last few turns to maintain context without overloading tokens
            recent_logs = logs[-max_turns:]
            if recent_logs:
                context_str = "Previous conversation history for context:\n"
                for log in recent_logs:
                    context_str += f"User: {log['user']}\nAI: {log['bot']}\n"
                context_str += "Current interaction:\n"
    except Exception as e:
        print(f"Error reading history context: {e}")
    return context_str

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/voice-chat', methods=['POST'])
def voice_chat():
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({"error": "No text payload provided"}), 400
            
        user_text = data['text']
        print(f"User Spoke: {user_text}")

        # 2. SYSTEM INSTRUCTIONS: TRILINGUAL FLUID ADAPTATION
        system_instruction = (
            "You are a friendly, elegant AI voice assistant for Sonkor Group. "
            "You engage in completely fluid, open-ended general conversation. "
            "You must adapt to the user's input language choice exactly: "
            "1. If the user speaks to you in Telugu, reply cleanly in native Telugu script. "
            "2. If the user speaks to you in Hindi, reply cleanly in native Hindi script (Devanagari). "
            "3. If the user speaks to you in English, reply cleanly in fluid English text. "
            "4. Keep your responses limited to exactly 1 short, clear conversational sentence so it sounds natural when spoken aloud. "
            "5. Never output emojis, asterisks, or markdown symbols."
        )

        # NEW: Build the payload by blending recent file memory with current input text
        history_context = get_recent_history_context(max_turns=3)
        gemini_payload = f"{history_context}User: {user_text}"

        # 3. GENERATE DYNAMIC CHAT CONTENT (With Fault-Tolerant Auto-Key Rotation)
        bot_text = ""
        max_attempts = len(API_KEYS)
        
        for attempt in range(max_attempts):
            try:
                client = get_gemini_client(force_next=(attempt > 0))
                
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=gemini_payload,  # Sending text input along with its context history
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction
                    ),
                )
                bot_text = response.text.strip()
                print(f"Gemini Generated Text (Key Index {current_key_index}): {bot_text}")
                break  # Success! Break out of the rotation loop
                
            except Exception as api_err:
                print(f"Warning: Attempt {attempt + 1} failed with key index {current_key_index}: {api_err}")
                
                if attempt == max_attempts - 1:
                    print("⚠️ All API keys in the rotation pool are currently exhausted. Using local backup...")
                    user_lower = user_text.lower()
                    
                    is_telugu = any(ord(char) >= 0x0C00 and ord(char) <= 0x0C7F for char in user_text) or any(word in user_lower for word in ["kavali", "peru", "namaskaram", "chesta", "matladu"])
                    is_hindi = any(ord(char) >= 0x0900 and ord(char) <= 0x097F for char in user_text) or any(word in user_lower for word in ["baat", "karo", "naam", "kya", "kaise", "suno", "hai", "mein"])
                    
                    if is_telugu:
                        bot_text = "నేను మీతో మాట్లాడటానికి సిద్ధంగా ఉన్నాను. చెప్పండి!"
                    elif is_hindi:
                        bot_text = "मैं आपसे बात करने के लिए पूरी तरह तैयार हूँ। कहिए!"
                    else:
                        bot_text = "I am ready to chat with you about anything."

        # 4. ROBUST UNICODE DETECTION FOR SPEAKER CORES
        has_telugu_script = any(ord(char) >= 0x0C00 and ord(char) <= 0x0C7F for char in bot_text)
        has_hindi_script = any(ord(char) >= 0x0900 and ord(char) <= 0x097F for char in bot_text)
        
        if has_telugu_script:
            bot_lang = 'te'
        elif has_hindi_script:
            bot_lang = 'hi'
        else:
            bot_lang = 'en'

        print(f"Routing Output to Voice Engine Accent: {bot_lang}")

        # Save to local text logs (which builds memory context for the next turn!)
        save_log(user_text, bot_text)

        # 5. GENERATE THE AUDIO PAYLOAD VIA TTS
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_audio_name = f"response_{timestamp}.mp3"
        
        os.makedirs('static', exist_ok=True)
        output_audio_path = os.path.join('static', output_audio_name)
        
        tts = gTTS(text=bot_text, lang=bot_lang, slow=False)
        tts.save(output_audio_path)

        return jsonify({
            "user_text": user_text,
            "bot_text": bot_text,
            "audio_url": f"/static/{output_audio_name}"
        })

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(port=8000, debug=True)