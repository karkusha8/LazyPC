from security.trusted.database import LazyPCDatabase

db = LazyPCDatabase()

print("Database:", db.path)
print()

phones = db.list_phones()
if not phones:
    print("trusted_phones is EMPTY")
else:
    print(f"Found {len(phones)} trusted phone(s):")
    print()
    for row in phones:
        for key, value in row.items():
            if isinstance(value, (bytes, bytearray)):
                value = bytes(value).hex()[:16] + "..."   # public keys, abbreviated
            print(f"{key}: {value}")
        print("-" * 60)