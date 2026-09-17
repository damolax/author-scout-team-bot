import secrets
from cryptography.fernet import Fernet

print("TELEGRAM_WEBHOOK_SECRET=" + secrets.token_urlsafe(32))
print("APP_SECRET=" + secrets.token_urlsafe(48))
print("TOKEN_ENCRYPTION_KEY=" + Fernet.generate_key().decode())
