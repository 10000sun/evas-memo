"""웹 푸시용 VAPID 키 한 쌍을 만든다. 출력된 세 줄을 .env에 붙여 넣는다(한 번만, 바꾸면 기존 구독이 모두 무효가 된다)."""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
k = ec.generate_private_key(ec.SECP256R1())
print("VAPID_PRIVATE_KEY=" + b64(k.private_numbers().private_value.to_bytes(32, "big")))
print("VAPID_PUBLIC_KEY=" + b64(k.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)))
print("VAPID_SUBJECT=mailto:본인메일@example.com")
