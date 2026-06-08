"""
知识库增量更新器
定时检查并同步外部政策源变化
支持HTML解析、政策更新识别和智能合并
"""

import sys
import json
import hashlib
import re
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Tuple
from dataclasses import dataclass
from html.parser import HTMLParser

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))


@dataclass
class UpdateSource:
    """更新源"""
    name: str
    url: str
    type: str  # policy, news, knowledge
    last_check: Optional[str] = None
    last_hash: Optional[str] = None
    last_update_time: Optional[str] = None  # 上次检测到的更新时间

    def __hash__(self):
        return hash(self.name)


@dataclass
class UpdateResult:
    """更新结果"""
    source: str
    url: str
    has_update: bool
    new_content: List[str] = None
    update_time: Optional[str] = None  # 内容发布时间
    timestamp: str = ""
    error: Optional[str] = None


@dataclass
class ParsedContent:
    """解析后的内容"""
    title: str
    content: str
    update_time: Optional[str] = None
    source_url: str = ""
    category: str = ""


class HTMLContentParser(HTMLParser):
    """提取HTML中的正文内容"""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.content = []
        self.in_body = False
        self.in_title = False
        self.in_script = False
        self.in_style = False
        self.in_nav = False
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer', 'aside'}
        self.current_skip = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == 'title':
            self.in_title = True

        if tag in self.skip_tags:
            self.current_skip = tag
            return

        if tag == 'a' and 'href' in attrs_dict:
            self.links.append(attrs_dict['href'])

        if tag == 'body':
            self.in_body = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

        if tag == self.current_skip:
            self.current_skip = None

    def handle_data(self, data):
        text = data.strip()
        if not text or self.current_skip:
            return

        if self.in_title:
            self.title += text
        elif self.in_body:
            # 过滤短文本和噪声
            if len(text) > 10:
                self.content.append(text)

    def get_text(self) -> str:
        """获取提取的纯文本"""
        # 按段落分割
        paragraphs = []
        current = ""

        for line in self.content:
            if len(current) + len(line) < 500:
                current += line + "\n"
            else:
                if current.strip():
                    paragraphs.append(current.strip())
                current = line + "\n"

        if current.strip():
            paragraphs.append(current.strip())

        return "\n\n".join(paragraphs)


class PolicyDateExtractor:
    """识别政策文档中的更新时间"""

    # 常见日期模式
    DATE_PATTERNS = [
        # 2024年1月1日
        (r'(\d{4})年(\d{1,2})月(\d{1,2})日', '%Y年%m月%d日'),
        # 2024-01-01
        (r'(\d{4})-(\d{2})-(\d{2})', '%Y-%m-%d'),
        # 2024/01/01
        (r'(\d{4})/(\d{2})/(\d{2})', '%Y/%m/%d'),
        # 2024.01.01
        (r'(\d{4})\.(\d{2})\.(\d{2})', '%Y.%m.%d'),
        # 2024年1月
        (r'(\d{4})年(\d{1,2})月', '%Y年%m月'),
        # 2024年
        (r'(\d{4})年', '%Y年'),
    ]

    UPDATE_KEYWORDS = [
        '发布', '更新', '修订', '施行', '生效', '实施',
        '公布', '印发', '通知', '公告', '发布于'
    ]

    def extract_date(self, text: str) -> Optional[str]:
        """从文本中提取日期"""
        for pattern, date_format in self.DATE_PATTERNS:
            matches = re.finditer(pattern, text)
            for match in matches:
                try:
                    if '%Y年%m月%d日' in date_format:
                        date_str = f"{match.group(1)}年{match.group(2)}月{match.group(3)}日"
                    elif '%Y年%m月' in date_format:
                        date_str = f"{match.group(1)}年{match.group(2)}月"
                    elif '%Y年' in date_format:
                        date_str = f"{match.group(1)}年"
                    else:
                        date_str = match.group(0)

                    # 验证日期合理性（1950-2030）
                    year = int(match.group(1))
                    if 1950 <= year <= 2030:
                        return date_str
                except (ValueError, IndexError):
                    continue
        return None

    def extract_update_time(self, html_text: str) -> Optional[str]:
        """从HTML中提取发布日期"""
        # 查找 meta 标签中的日期
        meta_patterns = [
            r'<meta[^>]*content="[^"]*(\d{4}[-/]\d{2}[-/]\d{2})[^"]*"',
            r'<meta[^>]*name="(?:date|updated|pubdate)"[^>]*content="([^"]+)"',
        ]

        for pattern in meta_patterns:
            matches = re.search(pattern, html_text, re.IGNORECASE)
            if matches:
                date_str = matches.group(1)
                # 标准化日期格式
                date_str = date_str.replace('/', '-')
                return date_str

        return None

    def is_quarterly_update(self, date_str: str) -> bool:
        """判断是否是季度更新"""
        # 季度更新通常在 1/4/7/10 月
        month_match = re.search(r'(\d{1,2})月', date_str)
        if month_match:
            month = int(month_match.group(1))
            return month in [1, 4, 7, 10]
        return False

    def get_update_frequency(self, dates: List[str]) -> str:
        """根据历史更新日期推断更新频率"""
        if len(dates) < 2:
            return "unknown"

        # 简化处理：检查月份间隔
        try:
            months = []
            for d in dates:
                match = re.search(r'(\d{4})年?(\d{1,2})月?', d)
                if match:
                    months.append(int(match.group(1)) * 12 + int(match.group(2)))

            if len(months) >= 2:
                months.sort()
                intervals = [months[i+1] - months[i] for i in range(len(months)-1)]
                avg_interval = sum(intervals) / len(intervals)

                if avg_interval <= 3:
                    return "quarterly"  # 季度更新
                elif avg_interval <= 6:
                    return "biannual"   # 半年更新
                else:
                    return "annual"     # 年度更新
        except (ValueError, IndexError, KeyError):
            pass

        return "unknown"


class KnowledgeMerger:
    """知识库文档智能合并"""

    def __init__(self, knowledge_base_path: str):
        self.knowledge_base_path = Path(knowledge_base_path)

    def find_similar_documents(self, new_title: str, category: str = None) -> List[Path]:
        """查找相似的现有文档"""
        similar = []

        # 按标题关键词匹配
        title_keywords = re.findall(r'[\w]+', new_title)

        for md_file in self.knowledge_base_path.rglob("*.md"):
            # 检查分类
            if category:
                if category not in str(md_file):
                    continue

            # 标题相似度
            md_title = md_file.stem
            common = sum(1 for kw in title_keywords if kw in md_title)

            if common >= 2 or (len(title_keywords) >= 3 and common >= 3):
                similar.append(md_file)

        return similar

    def merge_content(self, existing_path: Path, new_content: ParsedContent) -> str:
        """合并新旧内容"""
        existing = existing_path.read_text(encoding='utf-8')

        # 提取现有文档的front matter和正文
        front_matter = ""
        body = existing

        if existing.startswith('---'):
            parts = existing.split('---', 2)
            if len(parts) >= 3:
                front_matter = parts[1]
                body = parts[2]

        # 构建新的front matter
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_front_matter = f"""---
title: {new_content.title}
source: {new_content.source_url}
last_updated: {timestamp}
original_update: {new_content.update_time or 'unknown'}
---

"""

        # 合并策略：将新内容追加到现有内容后
        merged_body = body.strip() + "\n\n---\n\n## 更新内容\n\n" + new_content.content

        return new_front_matter + merged_body

    def should_merge(self, new_content: ParsedContent) -> Tuple[bool, Path]:
        """判断是否需要合并"""
        similar = self.find_similar_documents(new_content.title, new_content.category)

        if similar:
            # 优先选择最相似的
            return True, similar[0]

        return False, None


class KnowledgeUpdater:
    """知识库增量更新器"""

    # 碳排放相关数据源（HTTP优先，避免SSL问题）
    CARBON_SOURCES = [
        {
            "name": "中国碳排放交易网",
            "url": "http://www.pcet.cn",
            "type": "carbon_market",
            "description": "碳交易与碳市场信息"
        },
        {
            "name": "碳排放交易网",
            "url": "http://www.tanpaifang.com",
            "type": "carbon_market",
            "description": "碳排放权交易信息"
        },
        {
            "name": "中国节能信息网",
            "url": "http://www.ceprei.com",
            "type": "energy",
            "description": "节能减排与能效信息"
        },
        {
            "name": "中国环境报",
            "url": "http://www.cenews.com.cn",
            "type": "news",
            "description": "环保新闻资讯"
        },
        {
            "name": "Carbon Monitor",
            "url": "https://carbonmonitor.org",
            "type": "data",
            "description": "全球碳排放实时监测"
        },
        {
            "name": "Eartho",
            "url": "https://earthos.taoclimate.com",
            "type": "climate",
            "description": "气候变化数据"
        }
    ]

    def __init__(self, knowledge_base_path: str = None, update_interval: int = 3600):
        """
        Args:
            knowledge_base_path: 知识库路径
            update_interval: 更新检查间隔（秒），默认1小时
        """
        if knowledge_base_path is None:
            knowledge_base_path = str(project_root / "knowledge_base")

        self.knowledge_base_path = Path(knowledge_base_path)
        self.updates_dir = self.knowledge_base_path / "增量更新"
        self.updates_dir.mkdir(exist_ok=True)

        self.update_interval = update_interval
        self.sources: List[UpdateSource] = []
        self._merger = KnowledgeMerger(knowledge_base_path)
        self._date_extractor = PolicyDateExtractor()
        self._load_sources()
        self._last_update_check = None

        # 定时更新相关
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._auto_update_enabled = False

    def _load_sources(self):
        """加载更新源配置"""
        config_file = self.knowledge_base_path / "sources.json"

        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data.get('sources', []):
                        self.sources.append(UpdateSource(
                            name=item['name'],
                            url=item['url'],
                            type=item.get('type', 'policy'),
                            last_check=item.get('last_check'),
                            last_hash=item.get('last_hash'),
                            last_update_time=item.get('last_update_time')
                        ))
            except Exception as e:
                print(f"[KnowledgeUpdater] 加载源配置失败: {e}")

        # 如果没有配置，使用碳排放相关源
        if not self.sources:
            for src in self.CARBON_SOURCES:
                self.sources.append(UpdateSource(
                    name=src['name'],
                    url=src['url'],
                    type=src['type']
                ))

    def _save_sources(self):
        """保存更新源配置"""
        config_file = self.knowledge_base_path / "sources.json"
        data = {
            'sources': [
                {
                    'name': s.name,
                    'url': s.url,
                    'type': s.type,
                    'last_check': s.last_check,
                    'last_hash': s.last_hash,
                    'last_update_time': s.last_update_time
                }
                for s in self.sources
            ]
        }
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[KnowledgeUpdater] 保存源配置失败: {e}")

    def add_source(self, name: str, url: str, source_type: str = "policy"):
        """添加更新源"""
        source = UpdateSource(name=name, url=url, type=source_type)
        if source not in self.sources:
            self.sources.append(source)
            self._save_sources()

    def remove_source(self, name: str):
        """移除更新源"""
        self.sources = [s for s in self.sources if s.name != name]
        self._save_sources()

    def _fetch_html(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """获取网页内容（带SSL错误处理和编码处理）"""
        import ssl
        import re

        # 创建不验证SSL的context
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Connection': 'keep-alive',
                }
            )

            # 优先尝试HTTPS with SSL bypass
            if url.startswith('https'):
                try:
                    with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
                        raw_content = response.read()
                        content_type = response.getheader('Content-Type', '')
                        return self._decode_html_content(raw_content, content_type), response.getheader('Last-Modified', '')
                except ssl.SSLError:
                    pass  # 尝试HTTP

            # 回退到普通方式
            with urllib.request.urlopen(req, timeout=15) as response:
                raw_content = response.read()
                content_type = response.getheader('Content-Type', '')
                return self._decode_html_content(raw_content, content_type), response.getheader('Last-Modified', '')

        except Exception as e:
            return None, None

    def _decode_html_content(self, raw_content: bytes, content_type: str = '') -> Optional[str]:
        """智能解码HTML内容，尝试多种编码"""
        # 1. 首先尝试从Content-Type获取编码
        charset = None
        if 'charset=' in content_type:
            match = re.search(r'charset=([^\s;]+)', content_type, re.IGNORECASE)
            if match:
                charset = match.group(1).strip()

        # 2. 尝试检测HTML中的meta charset
        if not charset:
            raw_str = raw_content[:500].decode('latin-1', errors='ignore')
            meta_match = re.search(r'<meta[^>]+charset=["\']?([^s"\'>]+)', raw_str, re.IGNORECASE)
            if meta_match:
                charset = meta_match.group(1).strip()

        # 3. 尝试不同编码
        encodings_to_try = []
        if charset:
            encodings_to_try.append(charset.upper())
        encodings_to_try.extend(['UTF-8', 'GB18030', 'GBK', 'BIG5', 'LATIN-1'])

        for encoding in encodings_to_try:
            try:
                content = raw_content.decode(encoding, errors='strict')
                # 验证：如果有中文字符且能正常显示，说明解码成功
                if '碳' in content or '低' in content or '绿' in content:
                    return content
                # 即使没有常见字，也返回（可能有其他内容）
                return content
            except (UnicodeDecodeError, LookupError):
                continue

        # 4. 最后回退到 UTF-8 with ignore
        return raw_content.decode('utf-8', errors='ignore')

    def _parse_html_content(self, html: str) -> ParsedContent:
        """解析HTML提取正文"""
        parser = HTMLContentParser()
        try:
            parser.feed(html)
        except Exception:
            pass

        text = parser.get_text()

        # 提取标题
        title = parser.title.strip() if parser.title else "未命名"

        # 提取更新日期
        update_time = self._date_extractor.extract_update_time(html)
        if not update_time:
            update_time = self._date_extractor.extract_date(text[:2000])

        return ParsedContent(
            title=title,
            content=text[:10000],  # 限制内容长度
            update_time=update_time,
            source_url=""
        )

    def _fetch_content_hash(self, url: str) -> str:
        """获取内容hash（用于检测变化）"""
        html, _ = self._fetch_html(url)
        if html:
            return hashlib.md5(html[:20000].encode('utf-8', errors='ignore')).hexdigest()
        return ""

    def check_updates(self) -> List[UpdateResult]:
        """检查所有源的更新"""
        results = []
        now = datetime.now().isoformat()

        print(f"[KnowledgeUpdater] 开始检查 {len(self.sources)} 个更新源...")

        for source in self.sources:
            result = self._check_source(source)
            result.timestamp = now
            results.append(result)

            # 更新源状态
            source.last_check = now
            if result.update_time:
                source.last_update_time = result.update_time

        self._save_sources()
        self._last_update_check = now

        # 保存更新记录
        self._save_update_log(results)

        return results

    def _check_source(self, source: UpdateSource) -> UpdateResult:
        """检查单个源的更新"""
        try:
            html, last_modified = self._fetch_html(source.url)

            if not html:
                return UpdateResult(
                    source=source.name,
                    url=source.url,
                    has_update=False,
                    error=f"无法获取页面",
                    timestamp=datetime.now().isoformat()
                )

            content_hash = hashlib.md5(html[:20000].encode('utf-8', errors='ignore')).hexdigest()

            if source.last_hash is None:
                # 首次检查，初始化hash
                source.last_hash = content_hash
                return UpdateResult(
                    source=source.name,
                    url=source.url,
                    has_update=False,
                    timestamp=datetime.now().isoformat()
                )

            if content_hash != source.last_hash:
                # 有更新，解析内容
                parsed = self._parse_html_content(html)
                parsed.source_url = source.url

                source.last_hash = content_hash

                return UpdateResult(
                    source=source.name,
                    url=source.url,
                    has_update=True,
                    new_content=[parsed.content],
                    update_time=parsed.update_time,
                    timestamp=datetime.now().isoformat()
                )

            return UpdateResult(
                source=source.name,
                url=source.url,
                has_update=False,
                timestamp=datetime.now().isoformat()
            )

        except Exception as e:
            return UpdateResult(
                source=source.name,
                url=source.url,
                has_update=False,
                error=str(e),
                timestamp=datetime.now().isoformat()
            )

    def _save_update_log(self, results: List[UpdateResult]):
        """保存更新日志"""
        log_file = self.updates_dir / "update_log.json"
        logs = []

        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            except Exception:
                pass

        # 添加新记录
        for result in results:
            logs.append({
                'source': result.source,
                'url': result.url,
                'has_update': result.has_update,
                'update_time': result.update_time,
                'timestamp': result.timestamp,
                'error': result.error
            })

        # 只保留最近100条记录
        logs = logs[-100:]

        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[KnowledgeUpdater] 保存更新日志失败: {e}")

    def process_updates(self, results: List[UpdateResult]):
        """处理更新内容：智能合并到知识库"""
        from events import get_event_bus, EventType

        affected_paths = []
        for result in results:
            if not result.has_update or not result.new_content:
                continue

            parsed = ParsedContent(
                title=f"{result.source} 更新",
                content=result.new_content[0] if result.new_content else "",
                update_time=result.update_time,
                source_url=result.url
            )

            # 判断是否需要合并
            should_merge, existing_path = self._merger.should_merge(parsed)

            if should_merge and existing_path:
                # 合并到现有文档
                merged_content = self._merger.merge_content(existing_path, parsed)
                existing_path.write_text(merged_content, encoding='utf-8')
                print(f"[KnowledgeUpdater] 已合并更新到: {existing_path.name}")
                affected_paths.append(str(existing_path))
            else:
                # 保存为新文档
                new_path = self._save_new_document(parsed, result.source)
                if new_path:
                    affected_paths.append(str(new_path))

        # 发布事件,让 RAG 引擎订阅并重载
        if affected_paths:
            get_event_bus().publish(
                EventType.KNOWLEDGE_UPDATED,
                paths=affected_paths,
                count=len(affected_paths),
            )

    def _save_new_document(self, content: ParsedContent, source_name: str) -> Optional[str]:
        """保存为新文档,返回保存的文件路径字符串"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r'[^\w一-鿿]+', '_', content.title)[:50]
        filename = f"{safe_title}_{timestamp}.md"
        filepath = self.updates_dir / filename

        try:
            front_matter = f"""---
title: {content.title}
source: {content.source_url}
update_time: {content.update_time or 'unknown'}
processed_at: {datetime.now().isoformat()}
---

"""
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(front_matter)
                f.write(content.content)
            print(f"[KnowledgeUpdater] 已保存新文档: {filename}")
            return str(filepath)
        except Exception as e:
            print(f"[KnowledgeUpdater] 保存文档失败: {e}")
            return None

    def save_updates(self, updates: List[UpdateResult]):
        """保存更新内容到知识库（兼容旧接口）"""
        self.process_updates(updates)

    def get_update_status(self) -> Dict:
        """获取更新状态"""
        return {
            'sources_count': len(self.sources),
            'last_check': self._last_update_check,
            'updates_dir': str(self.updates_dir),
            'sources': [
                {
                    'name': s.name,
                    'type': s.type,
                    'url': s.url,
                    'last_check': s.last_check,
                    'last_update_time': s.last_update_time
                }
                for s in self.sources
            ]
        }

    def schedule_updates(self, callback: Optional[Callable] = None):
        """调度定期更新（需要在主循环中调用）"""
        import time

        while True:
            print(f"[KnowledgeUpdater] 执行定期检查...")
            results = self.check_updates()

            if callback:
                callback(results)

            # 处理更新
            self.process_updates(results)

            print(f"[KnowledgeUpdater] 等待 {self.update_interval} 秒后进行下次检查...")
            time.sleep(self.update_interval)

    def schedule_daily_update(self, hour: int = 9, callback: Optional[Callable] = None):
        """每天定时更新（默认早上9点）

        Args:
            hour: 更新小时（0-23），默认9点
            callback: 更新完成后的回调函数
        """
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            print("[KnowledgeUpdater] 定时更新线程已在运行中")
            return

        self._stop_event.clear()
        self._auto_update_enabled = True

        def _daily_loop():
            print(f"[KnowledgeUpdater] 定时更新已启动（每天 {hour}:00）")
            while not self._stop_event.is_set():
                now = datetime.now()
                # 计算下次执行时间
                next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                if next_run <= now:
                    next_run = next_run + timedelta(days=1)
                seconds_until_next = (next_run - now).total_seconds()

                print(f"[KnowledgeUpdater] 下次更新: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                self._stop_event.wait(seconds_until_next)

                if self._stop_event.is_set():
                    break

                # 执行更新
                print(f"[KnowledgeUpdater] 执行每日更新...")
                try:
                    results = self.check_updates()
                    self.process_updates(results)
                    if callback:
                        callback(results)
                    print(f"[KnowledgeUpdater] 每日更新完成")
                except Exception as e:
                    print(f"[KnowledgeUpdater] 每日更新失败: {e}")

        self._scheduler_thread = threading.Thread(target=_daily_loop, daemon=True)
        self._scheduler_thread.start()

    def start_auto_update(self, interval_hours: int = 24) -> None:
        """启动后台自动更新线程（每24小时检查一次）"""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return

        self._auto_update_enabled = True
        interval_seconds = max(1, interval_hours) * 3600
        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                try:
                    self.check_updates()
                except Exception as e:
                    print(f"[KnowledgeUpdater] 自动更新失败: {e}")
                self._stop_event.wait(interval_seconds)

        self._scheduler_thread = threading.Thread(target=_loop, daemon=True)
        self._scheduler_thread.start()
        print(f"[KnowledgeUpdater] 自动更新已启动（间隔: {interval_hours}小时）")

    def stop_auto_update(self) -> None:
        """停止后台自动更新线程"""
        self._auto_update_enabled = False
        self._stop_event.set()
        print("[KnowledgeUpdater] 自动更新已停止")

    def force_update(self):
        """强制执行一次更新"""
        results = self.check_updates()
        if any(r.has_update for r in results):
            self.process_updates(results)
        return results


# 全局实例
_knowledge_updater = None


def get_knowledge_updater(knowledge_base_path: str = None) -> KnowledgeUpdater:
    """获取KnowledgeUpdater单例"""
    global _knowledge_updater
    if _knowledge_updater is None:
        _knowledge_updater = KnowledgeUpdater(knowledge_base_path)
    return _knowledge_updater


if __name__ == "__main__":
    print("=" * 60)
    print("知识库增量更新器测试")
    print("=" * 60)

    updater = KnowledgeUpdater()

    print("\n[1] 更新状态:")
    status = updater.get_update_status()
    for key, value in status.items():
        if key != 'sources':
            print(f"   {key}: {value}")

    print("\n[2] 可用源列表:")
    for source in status['sources']:
        print(f"   - {source['name']} ({source['type']})")
        print(f"     URL: {source['url']}")

    print("\n[3] 检查更新...")
    results = updater.check_updates()
    for result in results:
        status_str = '有更新' if result.has_update else '无更新'
        update_info = f" (更新时间: {result.update_time})" if result.update_time else ""
        print(f"   - {result.source}: {status_str}{update_info}")
        if result.error:
            print(f"     错误: {result.error}")

    print("\n[4] 处理更新...")
    updater.process_updates(results)

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)