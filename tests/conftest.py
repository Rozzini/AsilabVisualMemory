import os
import tempfile

# Must be set before backend.config is imported anywhere.
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="vm-test-")
# Not an Ollama URL: keeps the model manager from probing/pulling a real model during tests.
os.environ["VISION_BASE_URL"] = "http://127.0.0.1:9/v1"
