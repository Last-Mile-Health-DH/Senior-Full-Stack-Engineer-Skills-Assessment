#!/usr/bin/env python3
import os
import sys

# Define the relative path from this script to the project root on the host
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../../"))

# List of critical scaffolding files and agent profiles to verify
CRITICAL_FILES = [
    "ARCHITECTURE.md",
    "GEMINI.md",
    "agents.md",
    "DEPLOYMENT.md",
    ".env.example",
    "tests-README.md",
    ".gitignore",
    "agents-skills/Backend-engineer-SKILL.md",
    "agents-skills/Frontend-engineer-SKILL.md",
    "agents-skills/ML-engineer-SKILL.md",
    "agents-skills/test-engineer-SKILL.md",
    "agents-skills/skills.md",
]

def main():
    print("================================──────────────────────────────")
    print("   AUTOMATED WORKSPACE HYGIENE & SCAFFOLDING VERIFIER")
    print("================================──────────────────────────────")
    print(f"Project Host Root: {PROJECT_ROOT}\n")
    
    passed_count = 0
    failed_count = 0
    
    for relative_path in CRITICAL_FILES:
        file_path = os.path.join(PROJECT_ROOT, relative_path)
        
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"[-] FAILED: Missing file -> {relative_path}")
            failed_count += 1
            continue
            
        # Check if file is empty
        size_bytes = os.path.getsize(file_path)
        if size_bytes == 0:
            print(f"[-] FAILED: Empty file   -> {relative_path} (0 bytes)")
            failed_count += 1
            continue
            
        print(f"[+] PASSED: Verified     -> {relative_path} ({size_bytes} bytes)")
        passed_count += 1
        
    print("\n--------------------------------──────────────────────────────")
    print(f"SUMMARY: {passed_count} verified, {failed_count} failed.")
    print("================================──────────────────────────────")
    
    if failed_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
