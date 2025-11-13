from cryptography.fernet import Fernet

key = b"-AJ6wEm6V3ZgwJbP2TMhhyCONHJUR3Lsmy2Q4wslrIM="
fernet = Fernet(key)

with open(".env.enc", "rb") as enc_file:
    decrypted = fernet.decrypt(enc_file.read())

with open(".env", "wb") as dec_file:
    dec_file.write(decrypted)

print("🔓 .env फाइल पुन्हा restore झाली.")
