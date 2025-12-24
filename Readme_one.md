1. requirements.txt
Overwrite your current file with this. I included onnxruntime-gpu explicitly to ensure the RTX 3050 is used.

Plaintext

# --- CORE SYSTEM ---
requests
numpy
colorama
pyaudio

# --- EARS (Hearing) ---
faster-whisper

# --- MOUTH (Speech) ---
# Critical: ONNX Runtime GPU is required for fast neural speech on RTX 3050
kokoro-onnx
sounddevice
onnxruntime-gpu

# --- EYES (Vision) ---
transformers
pillow
einops
accelerate
torch
torchvision
torchaudio
2. README.md
This is the "Manual." It explains the architecture (Gatekeeper -> Executor) and how to handle the heavy files that Git ignores.

Markdown

# CLARA (AGENT_ZERO)

**Centralized Local Autonomous Responsive Agent**
A fully local, multi-modal AI agent designed for **RTX 3050 (4GB VRAM)** hardware.

## 🧠 The Architecture (The "God Stack")
CLARA runs on a strict memory budget (4GB VRAM) by offloading logic to the cloud while keeping sensors local.

| Module | Engine | VRAM Cost | Description |
| :--- | :--- | :--- | :--- |
| **Gatekeeper** | Grok (API) | 0 GB | The "Pre-frontal Cortex." Decides intent (TASK vs CHAT) and manages memory. |
| **Ears** | Faster-Whisper | ~1.2 GB | Real-time transcription (Medium.en model). |
| **Mouth** | Kokoro v0.19 | ~0.8 GB | Neural TTS running on ONNX/CUDA. Tuned for "Witty/Seductive" tone. |
| **Eyes** | Moondream2 | ~1.6 GB | Lightweight Vision Transformer for image analysis. |

---

## 🛠️ Prerequisites
Before installing Python libraries, ensure your Windows environment is ready:

1.  **NVIDIA CUDA Toolkit:** Required for GPU acceleration.
2.  **eSpeak NG (Critical):** * Download from [GitHub Releases](https://github.com/espeak-ng/espeak-ng/releases).
    * **Action:** Add `C:\Program Files\eSpeak NG` to your System PATH.
3.  **FFmpeg:**
    * Run `winget install ffmpeg` in PowerShell.

---

## 🚀 Installation Guide

### 1. Clone the Repo
```bash
git clone [https://github.com/Angry-Nutrino/AGENT_ZERO.git](https://github.com/Angry-Nutrino/AGENT_ZERO.git)
cd AGENT_ZERO
2. Set up Python Environment
Bash

python -m venv venv
.\venv\Scripts\activate
3. Install Dependencies (The "Torch" Dance)
To ensure GPU support works, install PyTorch before the requirements file.

Bash

# 1. Install PyTorch with CUDA 12.1 support
pip install torch torchvision torchaudio --index-url [https://download.pytorch.org/whl/cu121](https://download.pytorch.org/whl/cu121)

# 2. Install the rest of the stack
pip install -r requirements.txt
4. Restore the Models (Crucial Step)
Since heavy model weights are ignored by Git to save space, you must restore them.

For the Mouth (Kokoro): Run the included setup script. It will download kokoro-v0_19.onnx and voices.bin automatically.

Bash

python setup_mouth.py
For the Eyes (Moondream): The first time you run the vision module, it will automatically download the weights from HuggingFace to your cache.

Bash

python core_logic/eyes.py
🎮 Usage
1. The Main Brain (Gatekeeper Loop)
This runs the full loop: Listen -> Gatekeeper Decision -> Action -> Speak.

Bash

python main.py
2. Module Testing
You can test individual senses to debug issues.

Test Hearing: python core_logic/ears.py

Test Speech: python core_logic/mouth.py (Checks for CUDA/eSpeak errors)

Test Vision: python core_logic/eyes.py (Analyzes a test image)

⚠️ Troubleshooting
"DLL load failed" (Kokoro): * You forgot to install eSpeak NG or add it to your PATH. Restart your terminal after installing.

Voice sounds robotic/slow: * Check if onnxruntime-gpu is installed. If it's running on CPU, the latency will be high.

Git Push Failures:

If you add large files (weights), Git will block the push. Ensure .gitignore is active.


### Final Instructions for You
1.  Save these two files.
2.  Run the git commands one last time to push the documentation:

```powershell
git add requirements.txt README.md
git commit -m "Add proper documentation and requirements"
git push