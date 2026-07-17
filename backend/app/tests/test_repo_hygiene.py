import os
import pytest

# Define the relative path from this test file to the project root
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "../../../"))

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

def is_running_in_docker():
    """Detect if the test is running inside an isolated Docker container context."""
    # We are in docker if /.dockerenv exists, or if our typical root files are missing from parent
    return os.path.exists("/.dockerenv") or not os.path.exists(os.path.join(PROJECT_ROOT, ".gitignore"))

@pytest.mark.parametrize("relative_path", CRITICAL_FILES)
def test_scaffolding_file_exists_and_is_not_empty(relative_path):
    """Verify that each critical scaffolding or agent profile file exists and is not empty."""
    if is_running_in_docker():
        pytest.skip("Running inside isolated Docker build context (host root files are not mounted by default).")
    
    file_path = os.path.join(PROJECT_ROOT, relative_path)
    
    # Assert file exists
    assert os.path.exists(file_path), f"Critical scaffolding file missing: {relative_path} (Resolved path: {file_path})"
    
    # Assert file is not empty (size > 0 bytes)
    file_size = os.path.getsize(file_path)
    assert file_size > 0, f"Critical scaffolding file is empty: {relative_path}"
    
    print(f"Verified: {relative_path} exists and is healthy ({file_size} bytes)")
