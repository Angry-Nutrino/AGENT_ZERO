from huggingface_hub import snapshot_download

print("--- 📥 Downloading Moondream to local folder... ---")
# This downloads all files to the folder './moondream_brain'
snapshot_download(
    repo_id="vikhyatk/moondream2",
    local_dir="./moondream_brain",
    local_dir_use_symlinks=False  # Force actual files, not links
)
print("--- ✅ Download Complete! You can delete this script now. ---")