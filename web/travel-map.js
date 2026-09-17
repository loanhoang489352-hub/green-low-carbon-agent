/**
 * P6.S.24: 出行方案地图渲染
 * 用 Leaflet + OpenStreetMap 瓦片绘制高德 polyline 折线 + 起点终点 marker。
 * 无 polyline / Leaflet 不可用时,前端 addMessage 降级到 CSS 路线条(PR-1 已实现)。
 *
 * 用法:
 *   renderTravelMap(containerEl, toolResult)
 *     - containerEl: DOM 元素(已存在的 .travel-card 容器)
 *     - toolResult: {origin, destination, origin_coord, destination_coord, routes: [{type, polyline, ...}]}
 *
 * 数据契约:
 *   - toolResult.routes[i].polyline: 高德编码字符串(lng,lat;lng,lat;...)
 *   - toolResult.origin_coord / destination_coord: {lat, lng} 用于 marker
 */
(function (global) {
    'use strict';

    /**
     * 解码高德 polyline 字符串 → [{lat, lng}, ...]
     * 格式:"lng1,lat1;lng2,lat2;..."
     * 兼容缺分号(逗号分隔)、缺逗号(空格分隔)的鲁棒解析
     */
    function decodeAmapPolyline(str) {
        if (!str || typeof str !== 'string') return [];
        var points = [];
        // 高德返回的 polyline 段间用 ; 分隔,坐标用 , 分隔
        var segments = str.split(';');
        for (var i = 0; i < segments.length; i++) {
            var seg = segments[i].trim();
            if (!seg) continue;
            // 兼容 "lng,lat" / "lng lat" 两种格式
            var parts = seg.split(/[,\s]+/);
            if (parts.length >= 2) {
                var lng = parseFloat(parts[0]);
                var lat = parseFloat(parts[1]);
                if (!isNaN(lng) && !isNaN(lat) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
                    points.push({ lat: lat, lng: lng });
                }
            }
        }
        return points;
    }

    /**
     * 计算一组 {lat,lng} 的中心点(用于 fitBounds)
     */
    function computeCenter(points) {
        if (!points || points.length === 0) return { lat: 39.9042, lng: 116.4074 }; // 北京兜底
        var sumLat = 0, sumLng = 0;
        for (var i = 0; i < points.length; i++) {
            sumLat += points[i].lat;
            sumLng += points[i].lng;
        }
        return { lat: sumLat / points.length, lng: sumLng / points.length };
    }

    /**
     * Bug16: 已完全移除 Leaflet 依赖(unpkg/leafletjs 国内屏蔽)
     * 现在只用高德静态地图代理 /api/staticmap + 内联 SVG 折线 overlay
     */


    /**
     * 渲染旅行地图到指定容器
     * P6.S.24 + Bug13: 双层兜底 — SVG 路线图(永远能渲染)+ Leaflet 增强(瓦片可能失败)
     * @param {HTMLElement} containerEl - .travel-card 内的 map 占位 div
     * @param {Object} toolResult - 后端 tool_result 数据
     * @param {number} [focusIndex] - 默认聚焦的路线索引(0-based),默认 0
     * @returns {boolean} - true=成功渲染, false=降级
     */
    function renderTravelMap(containerEl, toolResult, focusIndex) {
        if (!containerEl || !toolResult) return false;
        var routes = toolResult.routes || [];
        // 至少需要 1 条带 polyline 的路线才渲染地图
        var hasPolyline = routes.some(function (r) { return r && r.polyline; });
        if (!hasPolyline) {
            console.log('[TravelMap] 无 polyline 数据,降级 CSS 路线条');
            return false;
        }

        if (typeof focusIndex !== 'number' || focusIndex < 0 || focusIndex >= routes.length) {
            focusIndex = 0;
        }

        // P6.S.x: 高德 JS API 可用 → 交互地图(可拖拽/缩放,点卡片重画高亮);否则降级静态图
        if (typeof window.AMap !== 'undefined' && window.AMap && AMap.Map) {
            try {
                renderAMap(containerEl, toolResult, focusIndex);
                return true;
            } catch (e) {
                console.error('[TravelMap] AMap 渲染失败,降级静态图:', e);
            }
        }

        // P6.S.24 + Bug16: 静态图 + SVG 兜底(无外部 CDN 依赖)
        try {
            renderSVGMap(containerEl, toolResult, routes, focusIndex);
        } catch (e) {
            console.error('[TravelMap] 渲染失败:', e);
            containerEl.innerHTML = '<div class="travel-map-error">⚠️ 地图渲染失败:' + escapeHtml(String(e && e.message || e)) + '</div>';
            return false;
        }

        return true;
    }

    // P6.S.x: 高德 JS API 交互地图 —— 可拖拽/缩放,点卡片重画并高亮该方案
    var _amapInstances = {};
    function renderAMap(containerEl, toolResult, focusIndex) {
        var routes = toolResult.routes || [];
        var key = containerEl.getAttribute('data-message-id') || 'default';
        var center = (toolResult.origin_coord && toolResult.origin_coord.lng) ? toolResult.origin_coord
            : (toolResult.destination_coord || { lat: 39.9, lng: 116.4 });
        var map;
        if (_amapInstances[key]) {
            map = _amapInstances[key];
            // 显式移除所有 overlay(clearMap 在某些版本下清不干净,导致切卡片不刷新)
            try { map.remove(map.getAllOverlays()); } catch (e) { map.clearMap(); }
        } else {
            containerEl.style.height = '320px';
            containerEl.style.width = '100%';
            map = new AMap.Map(containerEl, {
                zoom: 13,
                center: [center.lng, center.lat],
                mapStyle: 'amap://styles/normal',
            });
            _amapInstances[key] = map;
        }
        // A/B 标记
        if (toolResult.origin_coord) {
            new AMap.Marker({
                position: [toolResult.origin_coord.lng, toolResult.origin_coord.lat],
                map: map, title: toolResult.origin || '起点',
                label: { content: 'A', offset: new AMap.Pixel(-10, -10) },
            });
        }
        if (toolResult.destination_coord) {
            new AMap.Marker({
                position: [toolResult.destination_coord.lng, toolResult.destination_coord.lat],
                map: map, title: toolResult.destination || '终点',
                label: { content: 'B', offset: new AMap.Pixel(10, -10) },
            });
        }
        // 路线折线:每条一个颜色(切换方案时颜色/粗细明显变化),聚焦=亮绿粗线
        var palette = ['#11998e', '#f59e0b', '#6366f1', '#dc2626', '#0ea5e9'];
        routes.forEach(function (r, idx) {
            if (!r.polyline) return;
            var pts = decodeAmapPolyline(r.polyline).map(function (p) { return [p.lng, p.lat]; });
            if (!pts.length) return;
            var isFocus = (typeof focusIndex === 'number' && focusIndex === idx);
            var color = isFocus ? '#11998e' : palette[idx % palette.length];
            new AMap.Polyline({
                path: pts, map: map,
                strokeColor: color,
                strokeWeight: isFocus ? 8 : 4,
                strokeOpacity: isFocus ? 1 : 0.7,
                lineJoin: 'round', lineCap: 'round',
                zIndex: isFocus ? 60 : 30,
                showDir: isFocus
            });
        });
        try { map.setFitView(); } catch (e) {}
        // 供点卡片重画时复用(存到容器上,index.html selectTravelRoute 会再调 renderTravelMap)
        containerEl._amapMap = map;
        containerEl._amapToolResult = toolResult;
    }

    /**
     * P6.S.24 + Bug13 + Bug15: 高德静态地图作底图 + 路线 overlay
     * 高德静态地图: 单 HTTP 请求返单张带真实道路/建筑/水系的 PNG
     * 我们用代理 /api/staticmap(避免 API key 暴露前端)
     * 然后叠 SVG 折线 + A/B 标记(独立于底图,永远能渲染)
     */
    function renderSVGMap(containerEl, toolResult, routes, focusIndex) {
        // 收集所有折线点
        var allPolylines = [];
        routes.forEach(function (r, idx) {
            if (!r.polyline) return;
            var pts = decodeAmapPolyline(r.polyline);
            if (pts.length > 0) {
                allPolylines.push({ index: idx, points: pts, route: r });
            }
        });

        if (allPolylines.length === 0) {
            containerEl.innerHTML = '<div class="travel-map-loading">⚠️ 路线数据为空</div>';
            return;
        }

        // 计算 bounding box
        var minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
        allPolylines.forEach(function (pl) {
            pl.points.forEach(function (p) {
                if (p.lat < minLat) minLat = p.lat;
                if (p.lat > maxLat) maxLat = p.lat;
                if (p.lng < minLng) minLng = p.lng;
                if (p.lng > maxLng) maxLng = p.lng;
            });
        });
        if (toolResult.origin_coord) {
            minLat = Math.min(minLat, toolResult.origin_coord.lat);
            maxLat = Math.max(maxLat, toolResult.origin_coord.lat);
            minLng = Math.min(minLng, toolResult.origin_coord.lng);
            maxLng = Math.max(maxLng, toolResult.origin_coord.lng);
        }
        if (toolResult.destination_coord) {
            minLat = Math.min(minLat, toolResult.destination_coord.lat);
            maxLat = Math.max(maxLat, toolResult.destination_coord.lat);
            minLng = Math.min(minLng, toolResult.destination_coord.lng);
            maxLng = Math.max(maxLng, toolResult.destination_coord.lng);
        }
        // 加 padding
        var latPad = (maxLat - minLat) * 0.15 || 0.02;
        var lngPad = (maxLng - minLng) * 0.15 || 0.02;
        minLat -= latPad; maxLat += latPad;
        minLng -= lngPad; maxLng += lngPad;

        // 计算 zoom(根据 bbox 跨度)
        // 简化:经度每度约 111km * cos(lat)
        var latSpan = maxLat - minLat;
        var lngSpan = maxLng - minLng;
        var approxKm = Math.max(latSpan * 111, lngSpan * 111 * Math.cos(minLat * Math.PI / 180));
        var zoom = 13;
        if (approxKm > 100) zoom = 8;
        else if (approxKm > 50) zoom = 9;
        else if (approxKm > 20) zoom = 10;
        else if (approxKm > 10) zoom = 11;
        else if (approxKm > 5) zoom = 12;
        else zoom = 13;

        // 高德静态图 markers(起点 A 绿色 / 终点 B 红色)
        var markersParam = '';
        if (toolResult.origin_coord) {
            markersParam += 'mid,0x11998e,A:' + toolResult.origin_coord.lng + ',' + toolResult.origin_coord.lat;
        }
        if (toolResult.destination_coord) {
            if (markersParam) markersParam += ';';
            markersParam += 'mid,0xef4444,B:' + toolResult.destination_coord.lng + ',' + toolResult.destination_coord.lat;
        }

        // 高德静态图 paths(高德一次只能 4 条,我们的 4 个方案刚好)
        var pathsParam = '';
        for (var pi = 0; pi < allPolylines.length && pi < 4; pi++) {
            var pl = allPolylines[pi];
            var isFocus = (pl.index === focusIndex);
            var color = isFocus ? '0x11998e' : '0x9ca3af';
            var weight = isFocus ? 6 : 3;
            var ptsStr = pl.points.map(function (p) { return p.lng + ',' + p.lat; }).join(';');
            if (pathsParam) pathsParam += '|';
            pathsParam += weight + ',' + color + ',1,' + ptsStr;  // 1 = solid
        }

        // 静态图 URL(走代理) —— 只要真实路网底图;路线折线与 A/B 标记由下方 SVG overlay 绘制。
        // (amap 静态图的 paths 参数报 UNKNOWN_ERROR,且 markers 会与 SVG 标记重复,故都不传)
        var bboxStr = minLng + ',' + minLat + ',' + maxLng + ',' + maxLat;
        var staticMapUrl = '/api/staticmap?bbox=' + encodeURIComponent(bboxStr) +
            '&size=800*500' +
            '&zoom=' + zoom +
            '&scale=1';

        // viewBox 尺寸
        var W = 800, H = 500;
        // 经纬度 → SVG 坐标(翻转 y,因为 lat 北大南小)
        function project(lat, lng) {
            var x = ((lng - minLng) / (maxLng - minLng || 1)) * W;
            var y = H - ((lat - minLat) / (maxLat - minLat || 1)) * H;
            return [x, y];
        }

        // 路线 paths(SVG overlay,可 hover 交互)
        // Bug17 修复: 浅色底图上白色不可见,改用对比色(4 方案 4 色)
        var pathsSvg = '';
        var palette = ['#11998e', '#f59e0b', '#6366f1', '#dc2626'];  // 绿/橙/紫/红
        allPolylines.forEach(function (pl) {
            var isFocus = (pl.index === focusIndex);
            var color = isFocus ? '#11998e' : palette[pl.index % palette.length];
            var width = isFocus ? 6 : 4;
            var opacity = isFocus ? 1.0 : 0.75;
            var samplePts = pl.points;
            if (samplePts.length > 500) {
                var step = Math.ceil(samplePts.length / 500);
                samplePts = samplePts.filter(function (_, i) { return i % step === 0; });
            }
            var d = samplePts.map(function (p, i) {
                var xy = project(p.lat, p.lng);
                return (i === 0 ? 'M' : 'L') + xy[0].toFixed(1) + ',' + xy[1].toFixed(1);
            }).join(' ');
            // 非聚焦路线: 先画白色粗描边,再画彩色主线(实现立体描边效果)
            if (!isFocus) {
                pathsSvg += '<path d="' + d + '" fill="none" stroke="white" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" opacity="0.9" data-mode="' + escapeHtml(pl.route.type || '') + '" data-route-index="' + pl.index + '" data-stroke="outline"></path>';
            }
            pathsSvg += '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="' + width + '" stroke-linecap="round" stroke-linejoin="round" opacity="' + opacity + '" data-mode="' + escapeHtml(pl.route.type || '') + '" data-route-index="' + pl.index + '"><title>' + escapeHtml(pl.route.type || '方案' + (pl.index + 1)) + '</title></path>';
        });

        // 起点/终点 marker
        function marker(lat, lng, label, color) {
            var xy = project(lat, lng);
            return '<g transform="translate(' + xy[0].toFixed(1) + ',' + xy[1].toFixed(1) + ')">' +
                '<circle r="16" fill="' + color + '" stroke="white" stroke-width="3" filter="drop-shadow(0 2px 4px rgba(0,0,0,0.3))" />' +
                '<text x="0" y="5" text-anchor="middle" fill="white" font-size="15" font-weight="800">' + label + '</text>' +
                '</g>';
        }
        var startMarker = '';
        var endMarker = '';
        if (toolResult.origin_coord) {
            startMarker = marker(toolResult.origin_coord.lat, toolResult.origin_coord.lng, 'A', '#11998e');
        }
        if (toolResult.destination_coord) {
            endMarker = marker(toolResult.destination_coord.lat, toolResult.destination_coord.lng, 'B', '#ef4444');
        }

        // 输出标头
        var headerText = escapeHtml(toolResult.origin || '起点') + ' → ' + escapeHtml(toolResult.destination || '终点');

        // 组装 HTML: 高德静态图作底图,SVG overlay 路线 + 标记
        var html = '<div class="travel-svg-map" data-message-id="' + escapeHtml(containerEl.getAttribute('data-message-id') || '') + '">' +
            '<div class="travel-staticmap-wrap" style="background-image:url(' + staticMapUrl + '); background-size:cover; background-position:center; background-repeat:no-repeat; width:100%; height:320px; position:relative;">' +
                '<svg class="travel-overlay-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;">' +
                    '<g class="svg-routes">' + pathsSvg + '</g>' +
                    '<g class="svg-markers">' + startMarker + endMarker + '</g>' +
                '</svg>' +
            '</div>' +
            '<div class="travel-svg-legend">🟢 起点 A · 🔴 终点 B · 🟢🟠🟣🔴 = 4 个方案(绿=推荐) · 底图来自高德地图</div>' +
            '</div>';

        containerEl.innerHTML = html;
        console.log('[TravelMap] 高德静态图+SVG 路线已渲染,共', allPolylines.length, '条折线');
    }


    // escapeHtml — 复用 addMessage 内的转义函数(若已存在),否则内联一份
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/`/g, '&#96;');
    }

    // 暴露到全局
    global.renderTravelMap = renderTravelMap;
    global.decodeAmapPolyline = decodeAmapPolyline;  // 测试用
    global.computeCenter = computeCenter;            // 测试用

})(window);
