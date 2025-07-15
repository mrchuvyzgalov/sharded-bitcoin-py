import ecdsa
import hashlib
import base64
import os


def generate_keypair() -> (str, str):
    sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()

    privkey_b64 = base64.b64encode(sk.to_string()).decode()
    pubkey_b64 = base64.b64encode(vk.to_string()).decode()
    return privkey_b64, pubkey_b64


def pubkey_to_address(pubkey_b64: str) -> str:
    pubkey_bytes = base64.b64decode(pubkey_b64)
    return hashlib.sha256(pubkey_bytes).hexdigest()


def save_wallet(filename: str, privkey_b64: str) -> None:
    with open(filename, 'w') as f:
        f.write(privkey_b64)


def load_wallet(filename: str) -> str:
    if not os.path.exists(filename):
        raise FileNotFoundError("Wallet not found")
    with open(filename, 'r') as f:
        return f.read()


def sign(message: str, privkey_b64: str) -> str:
    sk = ecdsa.SigningKey.from_string(base64.b64decode(privkey_b64), curve=ecdsa.SECP256k1)
    signature = sk.sign(message.encode())
    return base64.b64encode(signature).decode()


def verify(message: str, signature_b64: str, pubkey_b64: str) -> bool:
    vk = ecdsa.VerifyingKey.from_string(base64.b64decode(pubkey_b64), curve=ecdsa.SECP256k1)
    try:
        vk.verify(base64.b64decode(signature_b64), message.encode())
        return True
    except ecdsa.BadSignatureError:
        return False

