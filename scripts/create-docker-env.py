"""Create fresh local Docker configuration without displaying secrets."""
from pathlib import Path
import os
import secrets


def main():
    path = Path('.env')
    if path.exists():
        raise SystemExit('.env already exists; preserved. Edit it instead.')
    values = {
        'POSTGRES_PASSWORD': secrets.token_urlsafe(32),
        'KNOWLEDGE_AI_SIGNING_SECRET': secrets.token_urlsafe(48),
        'KNOWLEDGE_AI_GEMINI_API_KEY': 'PASTE_YOUR_GEMINI_API_KEY_HERE',
        'KNOWLEDGE_AI_GEMINI_MODEL': 'gemini-flash-latest',
        'KNOWLEDGE_AI_IMAGE_TAG': 'demo',
        'KNOWLEDGE_AI_UI_PORT': '9630',
        'KNOWLEDGE_AI_API_PORT': '9631',
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
    print('Created private .env. Add your Gemini API key before starting Docker.')


if __name__ == '__main__':
    main()
