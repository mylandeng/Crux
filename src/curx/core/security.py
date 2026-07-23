import hashlib
import hmac
import secrets

ACCESS_KEY_MARKER = "curx"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


class InvalidAccessKeyFormat(ValueError):
    pass


def generate_access_key() -> tuple[str, str]:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    return f"{ACCESS_KEY_MARKER}_{prefix}_{secret}", prefix


def access_key_prefix(raw_key: str) -> str:
    marker, separator, remainder = raw_key.partition("_")
    prefix, second_separator, secret = remainder.partition("_")
    if (
        marker != ACCESS_KEY_MARKER
        or not separator
        or not second_separator
        or len(prefix) != 8
        or not secret
    ):
        raise InvalidAccessKeyFormat("Invalid Curx access key format.")
    return prefix


def hash_access_key(raw_key: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        raw_key.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return (
        f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}"
        f"${salt.hex()}${digest.hex()}"
    )


def verify_access_key(raw_key: str, encoded_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded_hash.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            raw_key.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
