from __future__ import annotations


# ================================================================
# ORDINARY CONNECTION PROTOCOL
# ================================================================

PROTOCOL_VERSION = 2

# Cryptographic algorithms used by Ordinary V2.
IDENTITY_ALGORITHM = "ECDSA-P256"
KEY_EXCHANGE_ALGORITHM = "ECDH-P256"
KDF_ALGORITHM = "HKDF-SHA256"
CONFIRMATION_ALGORITHM = "HMAC-SHA256"


# ================================================================
# SECURITY PARAMETERS
# ================================================================

# One-time authentication secret.
AUTH_SECRET_DIGITS = 9
AUTH_SECRET_MIN = 100_000_000
AUTH_SECRET_MAX = 999_999_999

# Fresh nonce used by every ordinary session.
NONCE_SIZE = 32

# Ephemeral ECDH key uses P-256.
EPHEMERAL_KEY_CURVE = "P-256"

# Maximum number of authentication attempts.
MAX_AUTH_ATTEMPTS = 3


# ================================================================
# SESSION LIFETIME
# ================================================================

# Time during which a newly created ordinary session may
# complete authentication.
SESSION_TTL_SECONDS = 60.0

# Time during which the one-time secret is valid.
AUTH_SECRET_TTL_SECONDS = 60.0


# ================================================================
# MESSAGE TYPES
# ================================================================

MSG_AUTH_CHALLENGE = "ordinary_auth_challenge"
MSG_AUTH_RESPONSE = "ordinary_auth_response"
MSG_AUTH_SERVER_PROOF = "ordinary_auth_server_proof"
MSG_KEY_CONFIRMATION = "ordinary_key_confirmation"
MSG_AUTH_COMPLETE = "ordinary_auth_complete"
MSG_AUTH_REJECTED = "ordinary_auth_rejected"


# ================================================================
# SESSION STATES
# ================================================================

STATE_CREATED = "created"
STATE_WAITING_FOR_CLIENT = "waiting_for_client"
STATE_CLIENT_PROOF_VERIFIED = "client_proof_verified"
STATE_KEYS_DERIVED = "keys_derived"
STATE_WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
STATE_AUTHENTICATED = "authenticated"
STATE_REJECTED = "rejected"
STATE_EXPIRED = "expired"
STATE_CLOSED = "closed"