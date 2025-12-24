import sounddevice as sd
from kokoro_onnx import Kokoro
import os
import time

# --- CONFIGURATION ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(CURRENT_DIR, "models")
ONNX_PATH = os.path.join(MODELS_DIR, "kokoro-v0_19.onnx")
VOICES_PATH = os.path.join(MODELS_DIR, "voices.bin")

# --- INITIALIZATION ---
print("Loading Mouth...")
try:
    kokoro = Kokoro(ONNX_PATH, VOICES_PATH)
    print("✅ Mouth Loaded! (Running on RTX 3050 🚀)")
    print("✅ Mouth Loaded! (Voice: Bella)")
except Exception as e:
    print(f"❌ Error: {e}")
    kokoro = None

def speak(text):
    if not kokoro: return

    print(f"🗣️  Clara: {text}")
    
    # --- THE TUNING ---
    # Voice: 'af_bella' is warmer/deeper than 'af_sky'
    # Speed: 0.9 makes it more deliberate and intimate (Default is 1.0)
    # Lang: 'en-us'
    try:
        samples, sample_rate = kokoro.create(
            text, 
            voice="af_bella", 
            speed=1.2, 
            lang="en-us"
        )
        
        # Play audio
        # Slight delay before playback
        sd.play(samples, sample_rate)
        
        # --- THE CUT-OFF FIX ---
        # Calculate duration: samples / rate
        duration = len(samples) / sample_rate
        
        # We sleep for the duration + 0.2s padding to ensure no cut-off
        time.sleep(duration + 0.2)
        
    except Exception as e:
        print(f"❌ Speech Error: {e}")

if __name__ == "__main__":
    # Test the "acting" capabilities
    speak("   Ready  ")
    speak("Your clara is here to assist you, give me a command and I will obey.")