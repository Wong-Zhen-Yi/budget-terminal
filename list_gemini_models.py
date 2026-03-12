"""
Run this script to list all Gemini models available for your API key.
Usage:
    python list_gemini_models.py <YOUR_GOOGLE_API_KEY>
    python list_gemini_models.py  (reads GOOGLE_API_KEY env var)
"""
import sys
import os

def list_models(api_key):
    from google import genai
    client = genai.Client(api_key=api_key)
    print(f"\nAvailable Gemini models for your key:\n{'─'*55}")
    for m in client.models.list():
        methods = getattr(m, 'supported_actions', None) or []
        print(f"  {m.name}")
    print()

if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        print("Usage: python list_gemini_models.py <API_KEY>")
        sys.exit(1)
    list_models(key)
