import speech_recognition as sr
from faster_whisper import WhisperModel
import os
import pyttsx3 # Importing mouth to reply

# --- CONFIG ---
WAKE_WORD = "clara"  # Wake word to listen for

# 1. LOAD BRAIN (Do this once outside the loop)
print("--- 🧠 Loading Whisper Model... ---")
model = WhisperModel("small.en", device="cpu", compute_type="int8")
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

def speak(text):
    engine = pyttsx3.init()
    engine.setProperty('rate', 170)
    engine.say(text)
    engine.runAndWait()

def start_listening():
    recognizer = sr.Recognizer()
    MIC_INDEX = get_dynamic_mic_index("Microphone Array (Realtek(R)")
    with sr.Microphone(device_index=MIC_INDEX) as source:
        print("--- 🔇 Calibrating Noise... (Stay quiet) ---")
        # recognizer.adjust_for_ambient_noise(source, duration=0.5)
        recognizer.energy_threshold = 300  
        recognizer.dynamic_energy_threshold = False
        recognizer.pause_threshold = 1.2  # Seconds of silence before considering speech 
        print(f"--- 💤 Asleep. Waiting for '{WAKE_WORD}'... ---")

        while True:
            try:
                # Listen continuously
                # phrase_time_limit=3 -> Keep wake words short
                audio = recognizer.listen(source, timeout=None, phrase_time_limit=10)
                
                # Write to temp file
                with open("wake_temp.wav", "wb") as f:
                    f.write(audio.get_wav_data())
                
                # Transcribe
                segments, info = model.transcribe(
                    "wake_temp.wav", 
                    beam_size=1, 
                    initial_prompt="This is a conversation with my assistant Clara."
                )
                text = "".join([s.text for s in segments]).strip().lower()
                
                print(f"Heard: '{text}'") # Debug print
                
                # --- THE GATEKEEPER ---
                if WAKE_WORD in text:
                    print("🚨 WAKE WORD DETECTED! 🚨")
                    speak("Yes sir?")
                    # HERE is where we will trigger the main Agent later
                    
                else:
                    # Ignore everything else
                    pass
                
                os.remove("wake_temp.wav")

            except sr.WaitTimeoutError:
                pass # Just keep listening
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    start_listening()