import os
import requests
import shutil

# --- CONFIGURATION ---
# Define the target directory relative to this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "core_logic", "models")

# URLs for Kokoro v0.19 (ONNX + Voices)
URL_MODEL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
URL_VOICES = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"

def download_file(url, target_folder, filename):
    target_path = os.path.join(target_folder, filename)
    
    if os.path.exists(target_path):
        print(f"✅ Found existing: {filename}")
        return

    print(f"⬇️  Downloading {filename}...")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            with open(target_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    # Simple text progress bar
                    if total_size > 0:
                        percent = int(100 * downloaded / total_size)
                        print(f"\r   [{'#' * (percent // 5):<20}] {percent}%", end="")
        print(f"\n✅ Downloaded {filename} successfully!")
        
    except Exception as e:
        print(f"\n❌ Failed to download {filename}: {e}")

if __name__ == "__main__":
    print(f"🚀 Initializing CLARA's Mouth Setup...")
    print(f"📂 Target Directory: {MODELS_DIR}")
    
    # 1. Create Directory
    if not os.path.exists(MODELS_DIR):
        print("   -> Creating 'models' directory...")
        os.makedirs(MODELS_DIR)
    
    # 2. Download Files
    download_file(URL_MODEL, MODELS_DIR, "kokoro-v0_19.onnx")
    download_file(URL_VOICES, MODELS_DIR, "voices.bin")
    
    print("\n✨ Setup Complete. You can now run 'core_logic/mouth.py'.")