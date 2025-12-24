import pyttsx3

def speak(text):
    # 1. Initialize the engine
    engine = pyttsx3.init()
    
    # 2. Configure Voice (Optional: Make it faster/slower)
    # Rate = Speed (Default is usually 200)
    engine.setProperty('rate', 180) 
    
    # Volume (0.0 to 1.0)
    engine.setProperty('volume', 1.0)

    # 3. Choose a Voice (0 is usually Male/David, 1 is usually Female/Zira)
    voices = engine.getProperty('voices')
    # Use voices[1].id for female, voices[0].id for male
    engine.setProperty('voice', voices[1].id) 
    
    print(f"🗣️ CLARA says: {text}")
    
    # 4. Speak
    engine.say(text)
    engine.runAndWait()

def speak_all_voices(text):
    # 1. Initialize ONCE just to get the list of IDs
    temp_engine = pyttsx3.init()
    voices = temp_engine.getProperty('voices')
    # Save the IDs to a list so we can close the engine safely
    voice_map = [(v.id, v.name) for v in voices]
    del temp_engine  # Kill the temporary engine

    print(f"--- 🎤 FOUND {len(voice_map)} VOICES ---")

    # 2. Iterate manually
    for index, (v_id, v_name) in enumerate(voice_map):
        print(f"Testing Voice {index}: {v_name}")
        
        # 3. THE FIX: Create a FRESH engine for every single turn
        engine = pyttsx3.init()
        engine.setProperty('volume', 10.0)
        engine.setProperty('rate', 175)
        engine.setProperty('voice', v_id)
        
        engine.say(f"I am voice number {index}. My name is {v_name.split(' ')[1]}.")
        engine.runAndWait()
        
        # 4. Destroy it immediately
        del engine

if __name__ == "__main__":
    speak("System Online.")