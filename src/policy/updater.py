"""
低碳政策更新器
定时更新和监控低碳政策信息
"""

import json
import sqlite3
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timedelta
import hashlib
import sys

# 添加项目根目录
project_root = Path(__file__).parent.parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

try:
    from config_loader import get_policy_sources

    _POLICY_SOURCES = get_policy_sources()
except Exception as e:
    import logging

    logging.getLogger(__name__).warning("[PolicyUpdater] 配置加载失败,使用空列表: %s", e)
    _POLICY_SOURCES = []
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class PolicyUpdater:
    """
    低碳政策更新器

    功能:
    - 监控政策数据源
    - 定时更新知识库
    - 版本控制和变更追踪
    - 政策分类和标签
    """

    # 政策来源配置(从 config/sources.yaml 加载,失败时回退到硬编码)
    POLICY_SOURCES = (
        _POLICY_SOURCES
        + [
            # 若 YAML 未配置 type/check_interval_hours 时,补默认值
        ]
    )
    for _src in POLICY_SOURCES:
        _src.setdefault("type", "national")
        _src.setdefault("check_interval_hours", 24)

    # 政策分类
    POLICY_CATEGORIES = [
        "国家战略",  # 双碳目标等国家级战略
        "能源政策",  # 新能源、可再生能源
        "交通政策",  # 新能源车、交通减排
        "建筑政策",  # 绿色建筑、节能改造
        "工业政策",  # 工业减排、绿色制造
        "消费政策",  # 绿色消费、以旧换新
        "碳市场政策",  # 碳交易、碳普惠
        "补贴激励",  # 财政补贴、税收优惠
        "地方政策",  # 各地具体政策
        "国际合作",  # 国际气候协议
    ]

    def __init__(self, db_path: str = None, knowledge_base_path: str = None):
        """
        初始化政策更新器

        Args:
            db_path: 数据库路径
            knowledge_base_path: 知识库路径
        """
        if db_path is None:
            db_path = project_root / "data" / "policy_updates.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if knowledge_base_path is None:
            knowledge_base_path = project_root / "knowledge_base" / "policy"

        self.knowledge_base_path = Path(knowledge_base_path)
        self.knowledge_base_path.mkdir(parents=True, exist_ok=True)

        self._init_database()

        print("📰 政策更新系统初始化完成")

    def _init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # 政策记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                policy_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                category TEXT,
                source TEXT,
                source_url TEXT,
                publish_date TEXT,
                effective_date TEXT,
                summary TEXT,
                key_points TEXT,
                impact_level TEXT,
                status TEXT DEFAULT 'active',
                hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked TEXT
            )
        """)

        # 更新日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS update_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                update_type TEXT NOT NULL,
                source TEXT,
                items_added INTEGER DEFAULT 0,
                items_updated INTEGER DEFAULT 0,
                items_removed INTEGER DEFAULT 0,
                status TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # 来源检查记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                last_checked TEXT NOT NULL,
                items_found INTEGER DEFAULT 0,
                status TEXT
            )
        """)

        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_policies_category
            ON policies(category)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_policies_publish_date
            ON policies(publish_date)
        """)

        # P6.S.1: 源健康表(失败 backoff,避免港 IP 下每次重试 13 个 .gov.cn 都浪费 90s)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_health (
                source_name TEXT PRIMARY KEY,
                consecutive_failures INTEGER DEFAULT 0,
                last_error TEXT,
                last_success TEXT,
                next_retry_at TEXT
            )
        """)

        conn.commit()
        conn.close()

    def add_policy(
        self,
        title: str,
        content: str,
        category: str,
        source: str,
        source_url: str = None,
        publish_date: str = None,
        summary: str = None,
        key_points: List[str] = None,
        impact_level: str = "medium",
    ) -> str:
        """
        添加政策记录

        Args:
            title: 政策标题
            content: 政策全文/摘要
            category: 政策分类
            source: 来源
            source_url: 来源URL
            publish_date: 发布日期
            summary: 摘要
            key_points: 关键点列表
            impact_level: 影响级别 (high/medium/low)

        Returns:
            政策ID
        """
        # 生成唯一ID
        policy_id = hashlib.md5(f"{title}{publish_date}".encode()).hexdigest()[:16]

        # 计算内容哈希
        content_hash = hashlib.md5(content.encode()).hexdigest()

        now = datetime.now().isoformat()

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO policies
                (policy_id, title, content, category, source, source_url, publish_date,
                 summary, key_points, impact_level, hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    category = excluded.category,
                    updated_at = excluded.updated_at
            """,
                (
                    policy_id,
                    title,
                    content,
                    category,
                    source,
                    source_url,
                    publish_date,
                    summary,
                    json.dumps(key_points, ensure_ascii=False),
                    impact_level,
                    content_hash,
                    now,
                    now,
                ),
            )

            conn.commit()

        finally:
            conn.close()

        return policy_id

    def get_policies(
        self, category: str = None, source: str = None, limit: int = 50, since_days: int = None
    ) -> List[Dict]:
        """
        获取政策列表

        Args:
            category: 政策分类过滤
            source: 来源过滤
            limit: 返回数量
            since_days: 返回最近多少天的政策

        Returns:
            政策列表
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        conditions = ["status = 'active'"]
        params = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if source:
            conditions.append("source = ?")
            params.append(source)

        if since_days:
            since_date = (datetime.now() - timedelta(days=since_days)).strftime("%Y-%m-%d")
            conditions.append("publish_date >= ?")
            params.append(since_date)

        params.append(limit)

        cursor.execute(
            f"""
            SELECT policy_id, title, category, source, source_url, publish_date,
                   summary, key_points, impact_level, updated_at
            FROM policies
            WHERE {" AND ".join(conditions)}
            ORDER BY publish_date DESC, updated_at DESC
            LIMIT ?
        """,
            params,
        )

        rows = cursor.fetchall()
        conn.close()

        policies = []
        for row in rows:
            policies.append(
                {
                    "id": row[0],
                    "title": row[1],
                    "category": row[2],
                    "source": row[3],
                    "source_url": row[4],
                    "publish_date": row[5],
                    "summary": row[6],
                    "key_points": json.loads(row[7]) if row[7] else [],
                    "impact_level": row[8],
                    "updated_at": row[9],
                }
            )

        return policies

    def get_policy_by_id(self, policy_id: str) -> Optional[Dict]:
        """获取单个政策详情"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM policies WHERE policy_id = ?
        """,
            (policy_id,),
        )

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return {
            "id": row[1],
            "title": row[2],
            "content": row[3],
            "category": row[4],
            "source": row[5],
            "source_url": row[6],
            "publish_date": row[7],
            "effective_date": row[8],
            "summary": row[9],
            "key_points": json.loads(row[10]) if row[10] else [],
            "impact_level": row[11],
            "status": row[12],
            "created_at": row[14],
            "updated_at": row[15],
        }

    def get_latest_policies(self, limit: int = 10) -> List[Dict]:
        """获取最新政策"""
        # 修改：不按日期过滤，只按更新时间排序
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT policy_id, title, category, source, source_url, publish_date,
                   summary, key_points, impact_level, updated_at
            FROM policies
            WHERE status = 'active'
            ORDER BY updated_at DESC, publish_date DESC
            LIMIT ?
        """,
            (limit,),
        )

        rows = cursor.fetchall()
        conn.close()

        policies = []
        for row in rows:
            policies.append(
                {
                    "id": row[0],
                    "title": row[1],
                    "category": row[2],
                    "source": row[3],
                    "source_url": row[4],
                    "publish_date": row[5],
                    "summary": row[6],
                    "key_points": json.loads(row[7]) if row[7] else [],
                    "impact_level": row[8],
                    "updated_at": row[9],
                }
            )

        return policies

    def get_policies_by_keyword(self, keyword: str, limit: int = 10) -> List[Dict]:
        """搜索政策"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT policy_id, title, category, source, publish_date, summary
            FROM policies
            WHERE status = 'active' AND (
                title LIKE ? OR content LIKE ? OR summary LIKE ?
            )
            ORDER BY publish_date DESC
            LIMIT ?
        """,
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
        )

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row[0],
                "title": row[1],
                "category": row[2],
                "source": row[3],
                "publish_date": row[4],
                "summary": row[5],
            }
            for row in rows
        ]

    def check_updates(self) -> Dict[str, Any]:
        """
        检查政策更新(P4-E.3 增强:失败计入日志)

        P6.S.1: 失败 backoff — 连续失败的源自动跳过一段时间,避免港 IP 下
        13 个 .gov.cn 站都浪费 7s+ 的连接等待。backoff 1h/6h/24h 指数,
        任意一次成功重置计数。

        Returns:
            更新报告
        """
        report = {
            "checked_at": datetime.now().isoformat(),
            "sources_checked": [],
            "sources_skipped": [],  # P6.S.1
            "new_policies": 0,
            "updated_policies": 0,
            "errors": [],
        }

        for source in self.POLICY_SOURCES:
            source_name = source.get("name", "unknown")
            try:
                # P6.S.1: 先看 backoff,跳过的源不计 errors
                if self._is_source_in_backoff(source_name):
                    report["sources_skipped"].append(f"{source_name} (backoff)")
                    continue

                last_check = self._get_last_check_time(source_name)
                should_check = self._should_check_source(source, last_check)

                if should_check:
                    added, err = self._fetch_and_ingest(source)
                    self._record_check(source_name, added, "checked" if not err else "error")
                    if err:
                        self._record_source_health(source_name, success=False, error=err)
                        report["errors"].append(f"{source_name}: {err}")
                        report["sources_checked"].append(f"{source_name} (失败: {err[:60]})")
                        self._log_update(source_name, status="error", error=err)
                    else:
                        self._record_source_health(source_name, success=True)
                        report["new_policies"] += added
                        report["sources_checked"].append(f"{source_name} (新增 {added} 条)")
                else:
                    report["sources_checked"].append(f"{source_name} (跳过: 未到更新时间)")

            except Exception as e:
                err_msg = f"{source_name}: {type(e).__name__}: {str(e)[:120]}"
                self._record_source_health(source_name, success=False, error=err_msg)
                report["errors"].append(err_msg)
                self._log_update(source_name, status="error", error=err_msg)

        return report

    # ============== P6.S.1: 源健康 + backoff ==============

    def _is_source_in_backoff(self, source_name: str) -> bool:
        """检查源是否在 backoff 期(连续失败 N 次后跳过一段时间)"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT consecutive_failures, next_retry_at FROM source_health WHERE source_name = ?",
            (source_name,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return False
        failures, next_retry = row
        if not failures or failures < 2:
            return False
        if not next_retry:
            return False
        try:
            return datetime.now() < datetime.fromisoformat(next_retry)
        except Exception:
            return False

    def _record_source_health(self, source_name: str, success: bool, error: str = None) -> None:
        """记录源结果,更新 backoff 状态
        backoff 阶梯:2 次失败→1h, 3 次→6h, 4+ 次→24h
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        if success:
            cursor.execute(
                """
                INSERT INTO source_health (source_name, consecutive_failures, last_success, next_retry_at)
                VALUES (?, 0, ?, NULL)
                ON CONFLICT(source_name) DO UPDATE SET
                    consecutive_failures = 0,
                    last_success = excluded.last_success,
                    next_retry_at = NULL
            """,
                (source_name, datetime.now().isoformat()),
            )
        else:
            cursor.execute(
                """
                SELECT consecutive_failures FROM source_health WHERE source_name = ?
            """,
                (source_name,),
            )
            row = cursor.fetchone()
            failures = (row[0] if row else 0) + 1
            # 阶梯 backoff
            if failures >= 4:
                backoff_hours = 24
            elif failures >= 3:
                backoff_hours = 6
            else:
                backoff_hours = 1
            next_retry = (datetime.now() + timedelta(hours=backoff_hours)).isoformat()
            cursor.execute(
                """
                INSERT INTO source_health (source_name, consecutive_failures, last_error, next_retry_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    consecutive_failures = excluded.consecutive_failures,
                    last_error = excluded.last_error,
                    next_retry_at = excluded.next_retry_at
            """,
                (source_name, failures, error[:200] if error else None, next_retry),
            )
        conn.commit()
        conn.close()

    def _log_update(
        self, source: str, status: str = "success", added: int = 0, error: str = None
    ) -> None:
        """写 update_logs(让失败可追溯)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO update_logs (update_type, source, items_added, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    "policy_fetch",
                    source,
                    added,
                    status,
                    error,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _get_last_check_time(self, source_name: str) -> Optional[str]:
        """获取最后检查时间"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT last_checked FROM source_checks
            WHERE source_name = ?
            ORDER BY last_checked DESC
            LIMIT 1
        """,
            (source_name,),
        )

        row = cursor.fetchone()
        conn.close()

        return row[0] if row else None

    def _should_check_source(self, source: Dict, last_check: str) -> bool:
        """判断是否应该检查"""
        if last_check is None:
            return True

        last_check_time = datetime.fromisoformat(last_check)
        hours_since = (datetime.now() - last_check_time).total_seconds() / 3600

        return hours_since >= source.get("check_interval_hours", 24)

    def _record_check(self, source_name: str, items_found: int, status: str):
        """记录检查结果"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO source_checks (source_name, last_checked, items_found, status)
            VALUES (?, ?, ?, ?)
        """,
            (source_name, datetime.now().isoformat(), items_found, status),
        )

        conn.commit()
        conn.close()

    # ============== P4-E.3: 实际抓取 ==============

    def _fetch_url(self, url: str, timeout: int = 30) -> Optional[str]:
        """P4-E.3 增强:抓取 URL HTML,失败抛出明确错误(给调用方记录)"""
        import httpx

        # 精细 headers 提升 SSL/反爬兼容性
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
        r.raise_for_status()
        # 强制 UTF-8(政府站常用 GBK,这里不能自动嗅探,依赖外层编码处理)
        if r.encoding and r.encoding.lower() not in ("utf-8", "utf8"):
            try:
                r.encoding = "utf-8"
            except Exception:
                pass
        return r.text

    def _extract_content(self, html: str, source_url: str = "") -> str:
        """P4-E.3: 从 HTML 提取正文

        优先级:
        1) BeautifulSoup 针对 mee.gov.cn / ndrc.gov.cn 已知源用 CSS selector
        2) trafilatura 通用提取(若已安装)
        3) 退化:返回 body 文本
        """
        text = ""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            # 优先:常见正文容器
            for selector in [
                "div.TRS_Editor",
                "div.article-content",
                "div.content",
                "div.main-content",
                "article",
                "main",
            ]:
                node = soup.select_one(selector)
                if node:
                    text = node.get_text(separator="\n", strip=True)
                    if len(text) > 200:
                        return text
            # 退化:body 全部文本
            body = soup.body
            if body:
                text = body.get_text(separator="\n", strip=True)
            return text
        except Exception:
            pass

        # 退化到 trafilatura(若可用)
        try:
            import trafilatura

            extracted = trafilatura.extract(html)
            if extracted:
                return extracted
        except ImportError:
            pass
        except Exception:
            pass

        return text

    def _fetch_and_ingest(self, source: Dict) -> tuple[int, Optional[str]]:
        """P4-E.3 增强:抓取源 → 提取 → 入库 → 发 KNOWLEDGE_UPDATED 事件

        Args:
            source: {name, url, type?, check_interval_hours?}

        Returns:
            (新增政策数量, 错误消息) — 错误消息 None 表示成功
        """
        url = source.get("url", "")
        if not url:
            return 0, "url 为空"
        try:
            html = self._fetch_url(url)
        except Exception as e:
            return 0, f"抓取失败: {type(e).__name__}: {str(e)[:100]}"
        if not html:
            return 0, "抓取返回空"

        try:
            content = self._extract_content(html, url)
        except Exception as e:
            return 0, f"提取失败: {type(e).__name__}: {str(e)[:100]}"
        if not content or len(content) < 100:
            return 0, f"提取内容过短 ({len(content) if content else 0} chars)"

        # 提取标题
        title = source.get("name", "未命名政策")
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.string:
                t = soup.title.string.strip()
                if t and len(t) < 200:
                    title = t
        except Exception:
            pass

        # 入库(去重靠 policy_id)
        try:
            self.add_policy(
                title=title,
                content=content[:10000],
                category=source.get("category", "其他"),
                source=source.get("name", "unknown"),
                source_url=url,
                publish_date=datetime.now().strftime("%Y-%m-%d"),
                summary=content[:200],
                key_points=[],
                impact_level="medium",
            )
        except Exception as e:
            return 0, f"入库失败: {type(e).__name__}: {str(e)[:100]}"

        # 发事件 → RAG 重建
        try:
            from events import get_event_bus, EventType

            get_event_bus().publish(
                EventType.KNOWLEDGE_UPDATED,
                paths=[url],
                count=1,
                source="policy_updater",
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "[PolicyUpdater] 发事件失败: %s",
                e,
            )

        return 1, None

    def generate_policy_summary(self, days: int = 7) -> str:
        """
        生成政策摘要

        Args:
            days: 最近多少天的政策

        Returns:
            格式化的政策摘要
        """
        policies = self.get_policies(since_days=days)

        if not policies:
            return "近期暂无重大政策更新。"

        summary_parts = [f"📰 近{days}天重要政策速递\n"]

        # 按分类汇总
        by_category = {}
        for policy in policies:
            cat = policy.get("category", "其他")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(policy)

        for cat, cat_policies in by_category.items():
            summary_parts.append(f"\n🏛️ {cat}:")
            for policy in cat_policies[:3]:  # 每个分类最多3条
                title = policy.get("title", "")
                date = policy.get("publish_date", "")
                summary_parts.append(f"  • {title} ({date})")

        return "\n".join(summary_parts)

    def export_to_markdown(self, output_path: str = None) -> str:
        """
        导出政策到Markdown文件

        Args:
            output_path: 输出路径

        Returns:
            导出文件的路径
        """
        if output_path is None:
            output_path = (
                self.knowledge_base_path / f"policy_update_{datetime.now().strftime('%Y%m%d')}.md"
            )

        policies = self.get_policies(limit=100, since_days=365)

        lines = [
            "# 低碳政策汇总",
            f"\n更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"\n共收录政策: {len(policies)} 项\n",
        ]

        for policy in policies:
            lines.append(f"\n## {policy['title']}")
            lines.append(f"\n- **分类**: {policy['category']}")
            lines.append(f"- **来源**: {policy['source']}")
            lines.append(f"- **发布日期**: {policy['publish_date'] or '未知'}")

            if policy.get("summary"):
                lines.append(f"\n**摘要**: {policy['summary']}")

            if policy.get("key_points"):
                lines.append("\n**要点**:")
                for point in policy["key_points"]:
                    lines.append(f"- {point}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return str(output_path)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM policies WHERE status = 'active'")
        total_active = cursor.fetchone()[0]

        cursor.execute("""
            SELECT category, COUNT(*) 
            FROM policies 
            WHERE status = 'active'
            GROUP BY category
        """)
        category_counts = dict(cursor.fetchall())

        cursor.execute("SELECT COUNT(*) FROM source_checks")
        total_checks = cursor.fetchone()[0]

        cursor.execute("""
            SELECT source_name, last_checked 
            FROM source_checks 
            ORDER BY last_checked DESC
        """)
        recent_checks = cursor.fetchall()

        conn.close()

        return {
            "total_active_policies": total_active,
            "category_distribution": category_counts,
            "total_checks": total_checks,
            "recent_checks": [
                {"source": row[0], "last_checked": row[1]} for row in recent_checks[:5]
            ],
        }

    def add_sample_policies(self):
        """添加示例政策数据"""
        sample_policies = [
            {
                "title": "关于加快经济社会发展全面绿色转型的意见",
                "content": "推动大规模设备更新和消费品以旧换新，加快构建绿色低碳高质量发展模式...",
                "category": "国家战略",
                "source": "中共中央 国务院",
                "publish_date": "2024-07-31",
                "summary": "系统部署全面绿色转型工作，明确碳达峰碳中和路线图",
                "key_points": [
                    "形成绿色低碳生活方式",
                    "推动大规模设备更新",
                    "完善绿色低碳发展体系",
                ],
                "impact_level": "high",
            },
            {
                "title": "2024年新能源汽车推广应用财政补贴政策",
                "content": "继续支持新能源汽车产业健康发展，完善财税政策体系...",
                "category": "交通政策",
                "source": "财政部 工信部",
                "publish_date": "2024-02-01",
                "summary": "明确新能源汽车补贴标准和申请条件",
                "key_points": [
                    "补贴标准根据续航里程确定",
                    "私人购车补贴延续",
                    "充电基础设施建设支持",
                ],
                "impact_level": "high",
            },
            {
                "title": "绿色建材下乡活动实施方案",
                "content": "继续开展绿色建材下乡活动，促进绿色消费...",
                "category": "消费政策",
                "source": "工信部 住建部",
                "publish_date": "2024-03-01",
                "summary": "推动绿色建材在农村地区应用，促进消费升级",
                "key_points": ["确定试点地区", "给予消费券补贴", "规范绿色建材认证"],
                "impact_level": "medium",
            },
            {
                "title": "碳排放权交易管理暂行条例",
                "content": "规范碳排放权交易及相关活动，促进温室气体减排...",
                "category": "碳市场政策",
                "source": "国务院",
                "publish_date": "2024-01-25",
                "summary": "首部碳排放权交易专门法规，明确交易机制和监管要求",
                "key_points": ["明确覆盖行业范围", "规范碳配额分配", "建立市场调节机制"],
                "impact_level": "high",
            },
            {
                "title": "以旧换新行动方案 - 汽车",
                "content": "开展汽车以旧换新，促进汽车消费和节能减排...",
                "category": "补贴激励",
                "source": "商务部等",
                "publish_date": "2024-04-01",
                "summary": "报废旧车购买新车可获补贴，推动汽车消费升级",
                "key_points": ["报废补贴7000-10000元", "国三以下排放标准为重点", "联动地方补贴"],
                "impact_level": "high",
            },
        ]

        for policy in sample_policies:
            self.add_policy(**policy)

        print(f"   已添加 {len(sample_policies)} 条示例政策")
