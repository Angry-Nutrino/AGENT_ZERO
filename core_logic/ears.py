import speech_recognition as sr
from faster_whisper import WhisperModel
import os

# 1. Load the Local Model (Download happens once)
# "base.en" is fast and accurate enough. Use "small.en" if you want higher accuracy.
# device="cpu" is safest for now. Change to "cuda" later if you have an NVIDIA GPU setup.
print("--- 🧠 Loading Local Whisper Model... ---")
model = WhisperModel("medium.en", device="cuda", compute_type="int8")
print("--- ✅ Model Loaded! ---")

def get_dynamic_mic_index(target_name_substring):
    """
    Scans for a microphone that contains the target_name_substring.
    Returns the Index ID if found, otherwise returns None (Default Mic).
    """
    print(f"--- 🕵️ Scanning for mic: '{target_name_substring}'... ---")
    mics = sr.Microphone.list_microphone_names()
    
    for index, name in enumerate(mics):
        # Case-insensitive check
        if target_name_substring.lower() in name.lower():
            print(f"✅ Found '{name}' at Index {index}")
            return index
            
    print(f"❌ Warning: '{target_name_substring}' not found. Using Default Mic.")
    return None # Lets SpeechRecognition pick the system default

def listen_local()-> str:
    recognizer = sr.Recognizer()
    
    # Use your working Index 4\
    mic= get_dynamic_mic_index("Microphone Array (Realtek(R)")
    with sr.Microphone(device_index=mic) as source:
        print("--- 🔇 Adjusting noise... ---")
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        print("--- 👂 Listening (Local)... Speak now! ---")
        recognizer.pause_threshold = 1.3  # Seconds of silence before considering speech complete
        
        try:
            # Capture audio
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=15)
            
            # Save temporary file (Whisper needs a file, not a stream)
            with open("temp_command.wav", "wb") as f:
                f.write(audio.get_wav_data())
            
            # Transcribe locally
            segments, info = model.transcribe("temp_command.wav", beam_size=5)
            
            full_text = ""
            for segment in segments:
                full_text += segment.text
                
            print(f"✅ CLARA Heard: {full_text.strip()}")
            
            # Cleanup
            os.remove("temp_command.wav")
            return full_text.strip()

        except sr.WaitTimeoutError:
            print("❌ Silence.")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    listen_local()