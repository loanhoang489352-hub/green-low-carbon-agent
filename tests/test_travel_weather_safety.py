from agent.tools.extended import TravelPlanningTool


def routes():
    return [dict(type=mode, carbon_kg=0, cost_yuan=0, duration_min=20)
            for mode in ('骑行', '步行')]


STORM = {'weathercode': 95, 'description': '雷暴'}


def test_all_outdoor_routes_rejected_in_storm():
    options = routes()
    assert TravelPlanningTool()._recommend_route(options, STORM) == {}
    assert all('_disqualified' not in route for route in options)


def test_safe_transit_survives_weather_filter():
    options = routes() + [dict(type='地铁', carbon_kg=None, cost_yuan=4, duration_min=40)]
    assert TravelPlanningTool()._recommend_route(options, STORM)['type'] == '地铁'


def test_empty_routes_have_no_recommendation():
    assert TravelPlanningTool()._recommend_route([], STORM) == {}


def test_weather_change_clears_stale_warning():
    options = routes()
    tool = TravelPlanningTool()
    tool._recommend_route(options, STORM)
    assert tool._recommend_route(options, {'weathercode': 0}) in options
    assert all('weather_note' not in route for route in options)
