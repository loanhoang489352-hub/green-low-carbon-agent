import json
import urllib.request

from agent.tools.extended import TravelPlanningTool


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self):
        return json.dumps(self.payload).encode()


def provider(url, timeout=5, **kwargs):
    url = getattr(url, 'full_url', url)
    if 'geocode/geo' in url:
        coord = '116.30,39.90' if '%E8%A5%BF%E5%8D%95' in url else '116.45,39.92'
        return Response({'status': '1', 'geocodes': [{'location': coord}]})
    if 'transit/integrated' in url:
        return Response({'status': '1', 'route': {'transits': [{
            'duration': '2400', 'distance': '12000', 'cost': '4',
            'segments': [{'bus': {'buslines': [{'name': '真实公交线',
                'departure_stop': {'name': '甲站'}, 'arrival_stop': {'name': '乙站'},
                'via_num': '5', 'polyline': '116.30,39.90;116.40,39.91'}]}}],
        }]}})
    if 'v4/direction/bicycling' in url:
        return Response({'errcode': 0, 'data': {'paths': [{'distance': 12500,
            'duration': 2700, 'steps': [{'instruction': '沿真实道路骑行',
                'polyline': '116.30,39.90;116.35,39.91'}]}]}})
    if 'direction/driving' in url:
        return Response({'status': '1', 'route': {'paths': [{'distance': '15000',
            'duration': '1800', 'steps': [{'instruction': '沿真实驾车道路行驶',
                'polyline': '116.30,39.90;116.42,39.93'}]}]}})
    if 'direction/walking' in url:
        return Response({'status': '1', 'route': {'paths': [{'distance': '8000',
            'duration': '6000', 'steps': [{'instruction': '沿真实步行道路前行',
                'polyline': '116.30,39.90;116.33,39.90'}]}]}})
    if 'api.open-meteo.com' in url:
        return Response({'current_weather': {'temperature': 22, 'windspeed': 5,
                                              'weathercode': 1}})
    raise AssertionError(url)


def test_every_route_geometry_comes_from_its_provider(monkeypatch):
    monkeypatch.setenv('GAODE_API_KEY', 'test-real-provider-key')
    monkeypatch.setattr(urllib.request, 'urlopen', provider)
    result = TravelPlanningTool().execute(origin='西单', destination='国贸',
                                          city='北京', mode='all')
    assert result.success, result.error
    routes = {r['type']: r for r in result.data['routes']}
    assert {'公交+地铁', '骑行', '自驾', '步行'} <= routes.keys()
    assert routes['公交+地铁']['polyline'] != routes['自驾']['polyline']
    assert routes['骑行']['polyline'] != routes['步行']['polyline']
    assert all(r['navigation_url'].startswith('https://uri.amap.com/navigation?') for r in routes.values())
    assert routes['自驾']['cost_yuan'] is None
    assert routes['自驾']['cost_note'].startswith('未取得')
    assert routes['自驾']['carbon_kg'] is None
    assert routes['公交+地铁']['carbon_kg'] is None
    assert routes['骑行']['carbon_kg'] == 0
    assert routes['骑行']['carbon_boundary'] == 'direct_vehicle_operation_only'
    assert result.data['data_quality']['distance_duration'] == 'provider_observed'
    assert result.data['data_quality']['carbon_routes_available'] == 2
    assert result.data['weather']['source'] == 'Open-Meteo current weather'


def test_missing_key_and_provider_failure_never_fabricate(monkeypatch):
    monkeypatch.delenv('GAODE_API_KEY', raising=False)
    missing = TravelPlanningTool().execute(origin='西单', destination='国贸')
    assert not missing.success and missing.data['routes'] == []
    assert missing.data['code'] == 'ROUTE_PROVIDER_NOT_CONFIGURED'

    monkeypatch.setenv('GAODE_API_KEY', 'configured-but-down')
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(OSError('down')))
    failed = TravelPlanningTool().execute(origin='西单', destination='国贸')
    assert not failed.success and failed.data['routes'] == []
    source = __import__('pathlib').Path('src/agent/tools/extended.py').read_text(encoding='utf8')
    assert '_mock_route' not in source
    assert '4号线 → 6号线' not in source


def test_unknown_cost_is_neutral_not_free():
    routes = [
        {'type': '自驾', 'carbon_kg': 1, 'cost_yuan': None, 'duration_min': 10},
        {'type': '公交', 'carbon_kg': 1, 'cost_yuan': 0, 'duration_min': 10},
    ]
    TravelPlanningTool()._recommend_route(routes)
    assert routes[0]['score_breakdown']['cost'] == 0.5
    assert routes[1]['score_breakdown']['cost'] == 1.0
