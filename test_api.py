import json
import urllib.request
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = 'http://localhost:8000/api/chat'
data = {
    'user_id': 'test_user',
    'message': '你好',
    'conversation_id': None
}

req = urllib.request.Request(
    url,
    data=json.dumps(data).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    with urllib.request.urlopen(req, timeout=10) as response:
        result = response.read().decode('utf-8')
        print('API call successful!')
        resp = json.loads(result)
        print(f"Message: {resp['message'][:100]}...")
        print(f"Conversation ID: {resp['conversation_id']}")
except Exception as e:
    print(f'Error: {e}')
