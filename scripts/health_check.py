import time
import urllib.request

HEALTH_URL = "http://127.0.0.1:8000/health"

for attempt in range(30):
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            if response.status == 200:
                print("API is healthy")
                break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("API health check failed")
