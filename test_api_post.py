# -*- coding: utf-8 -*-
import json
from http.client import HTTPConnection

conn = HTTPConnection('localhost', 8000)
body = json.dumps({"user_info": {"age_group": "25-35"}})
conn.request('POST', '/api/user/register', body=body, headers={'Content-Type': 'application/json; charset=utf-8'})
resp = conn.getresponse()
print('Status:', resp.status)
print('Body:', resp.read().decode('utf-8')[:500])
conn.close()