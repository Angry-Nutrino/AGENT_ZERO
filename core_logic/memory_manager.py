import torch
import gc

def free_gpu_memory(model=None, tokenizer=None):
    """
    Aggressively clears GPU memory by deleting Python references
    and forcing PyTorch to release cached VRAM.
    """
    print("🧹 Cleaning GPU memory...")

    # 1. Delete the Python objects if they exist
    if model:
        del model
        print("   Model deleted.")
    if tokenizer:
        del tokenizer
        print("   Tokenizer deleted.")
    
    # 2. Force Python's internal Garbage Collector to run
    # This cleans up the deleted variables from RAM
    gc.collect()
    print("   Python garbage collector invoked.")
    
    # 3. Force PyTorch to release the reserved VRAM back to the GPU
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        print("   PyTorch GPU cache cleared.")
    
    # Optional: Verify cleanup (comment out if too spammy)
    # print(f"   VRAM Allocated: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
    # print(f"   VRAM Reserved:  {torch.cuda.memory_reserved() / 1024**3:.2f} GB")
    
    print("✨ GPU Memory flushed.")