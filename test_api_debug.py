# -*- coding: utf-8 -*-
import json
from http.client import HTTPConnection

conn = HTTPConnection('localhost', 8000)

# 发送详细日志的请求
body = json.dumps({"user_info": {"age_group": "25-35"}})
conn.request('POST', '/api/user/register', body=body, headers={
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': str(len(body))
})
resp = conn.getresponse()
print('Status:', resp.status)
print('Reason:', resp.reason)
headers = dict(resp.getheaders())
print('Headers:', headers)
body_bytes = resp.read()
print('Body length:', len(body_bytes))
try:
    print('Body:', body_bytes.decode('utf-8'))
except:
    print('Body (gbk):', body_bytes.decode('gbk', errors='replace'))
conn.close()