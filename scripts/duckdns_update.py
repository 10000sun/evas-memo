"""DuckDNS에 현재 집 IP를 알린다. 작업 스케줄러로 5분마다 돌린다.

.env의 DUCKDNS_DOMAIN(이름만, .duckdns.org 제외)과 DUCKDNS_TOKEN을 쓴다.
"""
import os
import sys
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()
domain, token = os.environ.get("DUCKDNS_DOMAIN"), os.environ.get("DUCKDNS_TOKEN")
if not (domain and token):
    sys.exit("DUCKDNS_DOMAIN / DUCKDNS_TOKEN이 .env에 없습니다")
# ip를 비워 보내면 DuckDNS가 요청이 들어온 곳의 공인 IP로 알아서 등록한다
url = "https://www.duckdns.org/update?" + urllib.parse.urlencode({"domains": domain, "token": token, "ip": ""})
body = urllib.request.urlopen(url, timeout=15).read().decode().strip()
print(body)
sys.exit(0 if body == "OK" else 1)  # 실패(KO)는 스케줄러 기록에 남도록 종료 코드로 알린다
