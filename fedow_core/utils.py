import base64
import json
import logging

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings

logger = logging.getLogger(__name__)

def data_to_b64(data: dict or list) -> bytes:
    data_to_json = json.dumps(data)
    json_to_bytes = data_to_json.encode('utf-8')
    bytes_to_b64 = base64.urlsafe_b64encode(json_to_bytes)
    return bytes_to_b64

def b64_to_data(b64: bytes) -> dict or list:
    b64_to_bytes = base64.urlsafe_b64decode(b64)
    bytes_to_json = b64_to_bytes.decode('utf-8')
    json_to_data = json.loads(bytes_to_json)
    return json_to_data


## OLD ##

def dict_to_b64(dico: dict) -> bytes:
    dict_to_json = json.dumps(dico)
    json_to_bytes = dict_to_json.encode('utf-8')
    bytes_to_b64 = base64.urlsafe_b64encode(json_to_bytes)
    return bytes_to_b64


def dict_to_b64_utf8(dico: dict) -> str:
    return dict_to_b64(dico).decode('utf-8')


def b64_to_dict(b64: bytes) -> dict:
    b64_to_bytes = base64.urlsafe_b64decode(b64)
    bytes_to_json = b64_to_bytes.decode('utf-8')
    json_to_dict = json.loads(bytes_to_json)
    return json_to_dict


def utf8_b64_to_dict(b64_string: str) -> dict:
    return b64_to_dict(b64_string.encode('utf-8'))


def get_request_ip(request) -> str:
    # logger.info(request.META)
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        x_real_ip = request.META.get('HTTP_X_REAL_IP')

        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        elif x_real_ip:
            ip = x_real_ip
        else:
            ip = request.META.get('REMOTE_ADDR')

        return ip
    return "0.0.0.0"


### FERNET CRYPTOGRAPHY ##
def kdf_generator() -> PBKDF2HMAC:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=settings.SALT.encode('utf-8'),
        iterations=480000,
    )
    return kdf


def fernet_encrypt(message: str) -> str:
    message = message.encode('utf-8')
    encryptor = Fernet(settings.FERNET_KEY)
    return encryptor.encrypt(message).decode('utf-8')


def fernet_decrypt(message: str) -> str:
    message = message.encode('utf-8')
    decryptor = Fernet(settings.FERNET_KEY)
    return decryptor.decrypt(message).decode('utf-8')


### RSA CRYPTOGRAPHY ##

def rsa_generator() -> tuple[str, str]:
    # Génération d'une paire de clés RSA
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

    # Extraction de la clé publique associée à partir de la clé privée
    public_key = private_key.public_key()

    # Sérialisation des clés au format PEM
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(settings.SECRET_KEY.encode('utf-8'))
    )

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem.decode('utf-8'), public_pem.decode('utf-8')


def get_private_key(private_pem: str) -> rsa.RSAPrivateKey | bool:
    try:
        private_key = serialization.load_pem_private_key(
            private_pem.encode('utf-8'),
            password=settings.SECRET_KEY.encode('utf-8'),
        )
        if not isinstance(private_key, rsa.RSAPrivateKey):
            return False
        return private_key

    except Exception as e:
        logger.error(f"Erreur de validation get_private_key : {e}")
        return False


def get_public_key(public_key_pem: str) -> rsa.RSAPublicKey | bool:
    try:
        # Charger la clé publique au format PEM
        public_key = serialization.load_pem_public_key(public_key_pem.encode('utf-8'), backend=default_backend())

        # Vérifier que la clé publique est au format RSA
        if not isinstance(public_key, rsa.RSAPublicKey):
            return False
        return public_key

    except Exception as e:
        logger.error(f"Erreur de validation get_public_key : {e}")
        raise e


def sign_message(message: bytes = None,
                 private_key: rsa.RSAPrivateKey = None) -> bytes:
    # Signer le message
    signature = private_key.sign(
        message,
        padding=padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        algorithm=hashes.SHA256()
    )
    return base64.urlsafe_b64encode(signature)


def verify_signature(public_key: rsa.RSAPublicKey,
                     message: bytes,
                     signature: str) -> bool:
    # Vérifier la signature
    try:
        public_key.verify(
            base64.urlsafe_b64decode(signature),
            message,
            padding=padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            algorithm=hashes.SHA256()
        )
        return True
    except InvalidSignature:
        return False



def rsa_encrypt_string(utf8_string=None, public_key: rsa.RSAPublicKey=None) -> str:
    message = utf8_string.encode('utf-8')
    ciphertext = public_key.encrypt(
        message,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return base64.urlsafe_b64encode(ciphertext).decode('utf-8')

def rsa_decrypt_string(utf8_enc_string: str, private_key: rsa.RSAPrivateKey) -> str:
    ciphertext = base64.urlsafe_b64decode(utf8_enc_string)
    plaintext = private_key.decrypt(
        ciphertext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return plaintext.decode('utf-8')