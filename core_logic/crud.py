import json
import os
from datetime import datetime

class crud:
    def __init__(self, filepath="core_logic/memory.json"):
        self.filepath = filepath
        self.memory = self._load_memory()

    def _load_memory(self):
        """
        Loads the JSON file. If it doesn't exist, creates a blank one.
        """
        if not os.path.exists(self.filepath):
            print("⚠️ Memory file not found. Creating new brain...")
            return self._create_default_memory()
        
        try:
            with open(self.filepath, 'r') as f:
                return json.load(f) # Converts JSON text -> Python Dict
        except json.JSONDecodeError:
            print("❌ Memory Corrupted! Starting fresh.")
            return self._create_default_memory()

    def _create_default_memory(self):
        # The structure we designed earlier
        return {
            "user_profile": {},
            "project_state": {},
            "episodic_log": []
        }

    def _save_memory(self):
        """Saves the current Python Dict back to the JSON file."""
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.memory, f, indent=2) # Converts Python Dict -> JSON text
        except Exception as e:
            print(f"❌ Failed to save memory: {e}")

    # --- PUBLIC TOOLS ---

    def get_full_context(self):
        """
        Formats memory into a string for the AI System Prompt.
        """
        profile = self.memory.get("user_profile", {})
        project = self.memory.get("project_state", {})
        
        # We build a clean string for the LLM to read
        context = "--- MEMORY CONTEXT ---\n"
        context += f"USER: {profile.get('name', 'Unknown')} | ROLE: {profile.get('role', 'User')}\n"
        context += f"PROJECT PHASE: {project.get('current_phase', 'Unknown')}\n"
        context += "----------------------"
        return context

    def add_episodic_log(self, summary, tags=[]):
        """
        Adds a history log and saves it.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "tags": tags
        }
        self.memory["episodic_log"].append(entry)
        self._save_memory() # Auto-save after adding
        print(f" 💾 Memory Saved: {summary}")
    
    def update_profile(self, category, key, value):
        """
        Allows the AI to update specific fields in the profile or project state.
        Usage: db.update_profile("project_state", "current_phase", "Building Soul")
        """
        if category in self.memory:
            self.memory[category][key] = value
            self._save_memory()
            print(f" 📝 Updated {category} -> {key}: {value}")
        else:
            print(f" ❌ Category '{category}' does not exist.")

# Self-test
if __name__ == "__main__":
    db = crud()
    print(db.get_full_context())