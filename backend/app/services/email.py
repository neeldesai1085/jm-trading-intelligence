import hashlib,secrets,smtplib
from email.message import EmailMessage
from app.core.config import settings

def new_token(): return secrets.token_urlsafe(32)
def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()
def send_email(to_email:str,subject:str,body:str):
    if not (settings.smtp_host and settings.smtp_from): return False
    msg=EmailMessage();msg['From']=settings.smtp_from;msg['To']=to_email;msg['Subject']=subject;msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=20) as s:
        s.starttls()
        if settings.smtp_user:s.login(settings.smtp_user,settings.smtp_password or '')
        s.send_message(msg)
    return True
