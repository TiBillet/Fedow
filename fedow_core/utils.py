import base64
from cryptography.fernet import Fernet

def get_client_ip(request):
    # import ipdb; ipdb.set_trace()

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    x_real_ip = request.META.get('HTTP_X_REAL_IP')

    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    elif x_real_ip:
        ip = x_real_ip
    else:
        ip = request.META.get('REMOTE_ADDR')

    return ip


def b64encode(string):
    return base64.urlsafe_b64encode(string.encode('utf-8')).decode('utf-8')

def b64decode(string):
    return base64.urlsafe_b64decode(string).decode('utf-8')


def gen_key():
    return Fernet.generate_key().decode('utf-8')

def get_request_ip(request):
    # logger.info(request.META)
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    x_real_ip = request.META.get('HTTP_X_REAL_IP')

    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    elif x_real_ip:
        ip = x_real_ip
    else:
        ip = request.META.get('REMOTE_ADDR')

    return ip