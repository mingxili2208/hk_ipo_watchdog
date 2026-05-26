"""数据访问层 — Repository 模式。"""

import json
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session
from loguru import logger

from app.models import (
    IPOItem,
    Announcement,
    AllotmentResult,
    GreyMarketQuote,
    StrategyDecision,
    LLMSummary,
    UpsertResult,
)
from app.storage.db import get_session
from app.storage.models import (
    IPOItemORM,
    AnnouncementORM,
    AllotmentResultORM,
    GreyMarketQuoteORM,
    IPOEventORM,
    StrategyScoreORM,
    LLMSummaryORM,
    LLMUsageORM,
    NotificationORM,
)


class Repository:
    """数据存储仓库。"""

    def __init__(self, session: Session | None = None):
        self._session = session

    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_session()
        return self._session

    def upsert_ipo(self, ipo: IPOItem) -> UpsertResult:
        """插入或更新 IPO。"""
        existing = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.stock_code == ipo.stock_code)
            .first()
        )

        if existing is None:
            orm = _ipo_to_orm(ipo)
            self.session.add(orm)
            self.session.commit()
            return UpsertResult(created=True, changed_fields=[])

        changed = []
        incoming_has_priority = _source_priority(ipo.source) >= _source_priority(existing.source)
        updates = {
            "stock_name": ipo.stock_name,
            "stock_name_en": ipo.stock_name_en,
            "market": ipo.market,
            "industry": ipo.industry,
            "business_overview": ipo.business_overview,
            "status": ipo.status,
            "subscription_start_date": str(ipo.subscription_start_date) if ipo.subscription_start_date else None,
            "subscription_close_date": str(ipo.subscription_close_date) if ipo.subscription_close_date else None,
            "listing_date": str(ipo.listing_date) if ipo.listing_date else None,
            "offer_price_min": ipo.offer_price_min,
            "offer_price_max": ipo.offer_price_max,
            "final_offer_price": ipo.final_offer_price,
            "lot_size": ipo.lot_size,
            "entry_fee_hkd": ipo.entry_fee_hkd,
            "market_cap_hkd": ipo.market_cap_hkd,
            "sponsors_json": json.dumps(ipo.sponsors, ensure_ascii=False),
            "cornerstone_investors_json": json.dumps(ipo.cornerstone_investors, ensure_ascii=False),
            "source": ipo.source,
            "source_url": ipo.source_url,
        }

        for field, new_val in updates.items():
            if new_val is None:
                continue
            if field == "status":
                if new_val == "unknown":
                    continue
                old_status = getattr(existing, field, None)
                if _status_rank(new_val) < _status_rank(old_status):
                    continue
                if old_status != new_val:
                    setattr(existing, field, new_val)
                    changed.append(field)
                continue
            if field in ("sponsors_json", "cornerstone_investors_json") and new_val == "[]":
                continue
            old_val = getattr(existing, field, None)
            old_is_missing = old_val in (None, "", "unknown", "[]", "{}")
            if old_val != new_val and (old_is_missing or incoming_has_priority):
                setattr(existing, field, new_val)
                changed.append(field)

        raw_sources = json.loads(existing.raw_sources_json or "{}")
        incoming_sources = ipo.raw_sources or ({ipo.source: {}} if ipo.source else {})
        merged_sources = {**raw_sources, **incoming_sources}
        raw_sources_json = json.dumps(merged_sources, ensure_ascii=False)
        if existing.raw_sources_json != raw_sources_json:
            existing.raw_sources_json = raw_sources_json
            changed.append("raw_sources")
        if changed:
            existing.updated_at = datetime.now()

        self.session.commit()
        return UpsertResult(created=False, changed_fields=changed)

    def save_announcement(self, ann: Announcement) -> int:
        """保存公告，去重。"""
        existing = (
            self.session.query(AnnouncementORM)
            .filter(
                AnnouncementORM.source == ann.source,
                AnnouncementORM.url == ann.url,
            )
            .first()
        )
        if existing:
            changed = False
            for field in ["stock_code", "stock_name", "published_at", "raw_text", "pdf_url"]:
                incoming = getattr(ann, field)
                if incoming and not getattr(existing, field):
                    setattr(existing, field, incoming)
                    changed = True
            if changed:
                self.session.commit()
            return existing.id

        orm = AnnouncementORM(
            stock_code=ann.stock_code,
            stock_name=ann.stock_name,
            title=ann.title,
            announcement_type=ann.announcement_type,
            source=ann.source,
            url=ann.url,
            published_at=ann.published_at,
            fetched_at=ann.fetched_at,
            raw_text=ann.raw_text,
            pdf_url=ann.pdf_url,
            parsed=1 if ann.parsed else 0,
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def save_allotment_result(self, result: AllotmentResult) -> int:
        """保存配发结果。"""
        # 更新 IPO 状态
        ipo = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.stock_code == result.stock_code)
            .first()
        )
        if ipo:
            ipo.status = "allotment_result_published"
            if result.final_offer_price:
                ipo.final_offer_price = result.final_offer_price

        orm = AllotmentResultORM(
            stock_code=result.stock_code,
            final_offer_price=result.final_offer_price,
            public_subscription_times=result.public_subscription_times,
            international_subscription_times=result.international_subscription_times,
            one_lot_success_rate=result.one_lot_success_rate,
            clawback_ratio=result.clawback_ratio,
            total_applicants=result.total_applicants,
            valid_applicants=result.valid_applicants,
            basis_of_allocation_url=result.basis_of_allocation_url,
            announcement_id=result.announcement_id,
            parse_confidence=result.parse_confidence,
            raw_fields_json=json.dumps(result.raw_fields, ensure_ascii=False),
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def save_grey_market_quote(self, quote: GreyMarketQuote) -> int:
        """保存暗盘报价。"""
        orm = GreyMarketQuoteORM(
            stock_code=quote.stock_code,
            source=quote.source,
            grey_price=quote.grey_price,
            offer_price=quote.offer_price,
            change_percent=quote.change_percent,
            turnover_hkd=quote.turnover_hkd,
            quoted_at=quote.quoted_at,
            source_url=quote.source_url,
            raw_fields_json=json.dumps(quote.raw_fields, ensure_ascii=False),
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def has_notification_been_sent(self, key: str) -> bool:
        """判断某类通知是否已经发送。"""
        return (
            self.session.query(NotificationORM)
            .filter(NotificationORM.notification_key == key, NotificationORM.status == "sent")
            .first()
            is not None
        )

    def get_delivered_notification_channels(self, key: str) -> set[str]:
        """返回该逻辑通知已经成功投递的渠道，用于仅重试失败渠道。"""
        orm = (
            self.session.query(NotificationORM)
            .filter(NotificationORM.notification_key == key)
            .first()
        )
        if orm is None or not orm.channel:
            return set()
        return {channel for channel in orm.channel.split(",") if channel}

    def record_notification(
        self,
        notification_key: str,
        stock_code: str | None,
        notification_type: str,
        level: int,
        channel: str,
        title: str,
        body: str,
        status: str = "sent",
        error_message: str | None = None,
    ) -> int:
        """记录推送结果。"""
        orm = (
            self.session.query(NotificationORM)
            .filter(NotificationORM.notification_key == notification_key)
            .first()
        )
        if orm is None:
            orm = NotificationORM(notification_key=notification_key)
            self.session.add(orm)
        orm.stock_code = stock_code
        orm.notification_type = notification_type
        orm.level = level
        orm.channel = channel
        orm.title = title
        orm.body = body
        orm.status = status
        orm.error_message = error_message
        orm.sent_at = datetime.now() if status == "sent" else None
        self.session.commit()
        return orm.id

    def add_event(
        self,
        stock_code: str | None,
        event_type: str,
        event_key: str | None = None,
        title: str | None = None,
        detail: dict | None = None,
    ) -> int:
        """记录事件。"""
        if event_key:
            existing = (
                self.session.query(IPOEventORM)
                .filter(IPOEventORM.event_key == event_key)
                .first()
            )
            if existing:
                return existing.id

        orm = IPOEventORM(
            stock_code=stock_code,
            event_type=event_type,
            event_key=event_key,
            title=title,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def save_strategy_score(self, decision: StrategyDecision) -> int:
        """保存策略评分。"""
        orm = StrategyScoreORM(
            stock_code=decision.stock_code,
            score=decision.score,
            level=decision.level,
            passed=1 if decision.passed else 0,
            matched_rules_json=json.dumps(decision.matched_rules),
            trigger_reasons_json=json.dumps(decision.trigger_reasons, ensure_ascii=False),
            risk_flags_json=json.dumps(decision.risk_flags, ensure_ascii=False),
            missing_fields_json=json.dumps(decision.missing_fields),
            evaluated_at=decision.evaluated_at,
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def has_allotment_for_announcement(self, announcement_id: int) -> bool:
        """判断公告是否已经转换为配发结果。"""
        return (
            self.session.query(AllotmentResultORM)
            .filter(AllotmentResultORM.announcement_id == announcement_id)
            .first()
            is not None
        )

    def save_llm_summary(
        self,
        stock_code: str | None,
        event_key: str | None,
        summary: LLMSummary,
    ) -> int:
        """保存 LLM 摘要。"""
        orm = LLMSummaryORM(
            stock_code=stock_code,
            event_key=event_key,
            title=summary.title,
            summary=summary.summary,
            key_points_json=json.dumps(summary.key_points, ensure_ascii=False),
            trigger_reasons_json=json.dumps(summary.trigger_reasons, ensure_ascii=False),
            risks_json=json.dumps(summary.risks, ensure_ascii=False),
            suggested_action=summary.suggested_action,
            confidence=summary.confidence,
            summary_source=summary.summary_source,
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def record_llm_usage(self, purpose: str, usage: dict) -> int:
        """保存一次由供应商响应返回的 LLM token 用量。"""
        orm = LLMUsageORM(
            purpose=purpose,
            provider=str(usage.get("provider") or "unknown"),
            model=str(usage.get("model") or "unknown"),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cached_tokens=int(usage.get("cached_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def get_llm_usage_summary(self) -> list[dict]:
        """按模型与用途汇总已记录的 token 用量。"""
        rows = (
            self.session.query(
                LLMUsageORM.provider,
                LLMUsageORM.model,
                LLMUsageORM.purpose,
                func.count(LLMUsageORM.id),
                func.sum(LLMUsageORM.prompt_tokens),
                func.sum(LLMUsageORM.completion_tokens),
                func.sum(LLMUsageORM.cached_tokens),
                func.sum(LLMUsageORM.total_tokens),
            )
            .group_by(LLMUsageORM.provider, LLMUsageORM.model, LLMUsageORM.purpose)
            .order_by(LLMUsageORM.provider, LLMUsageORM.model, LLMUsageORM.purpose)
            .all()
        )
        return [
            {
                "provider": row[0],
                "model": row[1],
                "purpose": row[2],
                "calls": int(row[3] or 0),
                "prompt_tokens": int(row[4] or 0),
                "completion_tokens": int(row[5] or 0),
                "cached_tokens": int(row[6] or 0),
                "total_tokens": int(row[7] or 0),
            }
            for row in rows
        ]

    def get_llm_usage_for_hk_day(self, day: date | None = None) -> dict:
        """汇总指定香港自然日的 LLM token 用量。"""
        from app.utils.time_utils import today_hk

        target_day = day or today_hk()
        hk_tz = timezone(timedelta(hours=8))
        start = datetime.combine(target_day, time.min, tzinfo=hk_tz).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        row = (
            self.session.query(
                func.count(LLMUsageORM.id),
                func.sum(LLMUsageORM.prompt_tokens),
                func.sum(LLMUsageORM.completion_tokens),
                func.sum(LLMUsageORM.cached_tokens),
                func.sum(LLMUsageORM.total_tokens),
            )
            .filter(LLMUsageORM.created_at >= start, LLMUsageORM.created_at < end)
            .one()
        )
        return {
            "date": str(target_day),
            "calls": int(row[0] or 0),
            "prompt_tokens": int(row[1] or 0),
            "completion_tokens": int(row[2] or 0),
            "cached_tokens": int(row[3] or 0),
            "total_tokens": int(row[4] or 0),
        }

    def get_active_ipos(self) -> list[IPOItem]:
        """获取所有活跃 IPO。"""
        rows = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.status.notin_(["listed", "archived"]))
            .all()
        )
        return [_orm_to_ipo(r) for r in rows]

    def get_ipo_by_code(self, stock_code: str) -> IPOItem | None:
        """根据代码获取 IPO。"""
        row = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.stock_code == stock_code)
            .first()
        )
        return _orm_to_ipo(row) if row else None

    def get_latest_allotment(self, stock_code: str) -> AllotmentResult | None:
        """获取最新配发结果。"""
        row = (
            self.session.query(AllotmentResultORM)
            .filter(AllotmentResultORM.stock_code == stock_code)
            .order_by(AllotmentResultORM.created_at.desc())
            .first()
        )
        if not row:
            return None
        return AllotmentResult(
            stock_code=row.stock_code,
            final_offer_price=row.final_offer_price,
            public_subscription_times=row.public_subscription_times,
            international_subscription_times=row.international_subscription_times,
            one_lot_success_rate=row.one_lot_success_rate,
            clawback_ratio=row.clawback_ratio,
            total_applicants=row.total_applicants,
            valid_applicants=row.valid_applicants,
            parse_confidence=row.parse_confidence or "unknown",
        )

    def get_latest_grey_quote(self, stock_code: str) -> GreyMarketQuote | None:
        """获取最新暗盘报价。"""
        row = (
            self.session.query(GreyMarketQuoteORM)
            .filter(GreyMarketQuoteORM.stock_code == stock_code)
            .order_by(GreyMarketQuoteORM.quoted_at.desc())
            .first()
        )
        if not row:
            return None
        return GreyMarketQuote(
            stock_code=row.stock_code,
            source=row.source,
            grey_price=row.grey_price,
            offer_price=row.offer_price,
            change_percent=row.change_percent,
            turnover_hkd=row.turnover_hkd,
            quoted_at=row.quoted_at or datetime.now(),
        )

    def get_today_events(self) -> list[dict]:
        """获取香港自然日内的事件，并附带可用于日报的当前数据快照。"""
        from app.utils.time_utils import today_hk

        today = today_hk()
        hk_tz = timezone(timedelta(hours=8))
        start = datetime.combine(today, time.min, tzinfo=hk_tz).astimezone(timezone.utc)
        end = start + timedelta(days=1)
        rows = (
            self.session.query(IPOEventORM)
            .filter(IPOEventORM.created_at >= start, IPOEventORM.created_at < end)
            .all()
        )
        result = []
        for r in rows:
            detail = json.loads(r.detail_json) if r.detail_json else {}
            event = {
                "id": r.id,
                "stock_code": r.stock_code,
                "event_type": r.event_type,
                "title": r.title,
                "detail": detail,
                "created_at": str(r.created_at),
            }
            if r.stock_code:
                ipo = self.get_ipo_by_code(r.stock_code)
                if ipo:
                    event["ipo"] = ipo.model_dump(
                        mode="json",
                        exclude={"raw_sources", "source_url", "created_at", "updated_at"},
                        exclude_none=True,
                    )
                if r.event_type == "allotment_result":
                    allotment = self.get_latest_allotment(r.stock_code)
                    if allotment:
                        event["allotment"] = allotment.model_dump(mode="json", exclude_none=True)
                if r.event_type == "grey_market_breakout":
                    grey = self.get_latest_grey_quote(r.stock_code)
                    if grey:
                        event["grey_market"] = grey.model_dump(mode="json", exclude_none=True)
            result.append(event)
        return result

    def get_ipo_follow_ups_for_digest(self) -> list[dict]:
        """获取此前发现、尚待上市且适合在日报继续提醒的 IPO。"""
        from app.utils.time_utils import today_hk

        today = today_hk()
        hk_tz = timezone(timedelta(hours=8))
        rows = (
            self.session.query(IPOEventORM)
            .filter(IPOEventORM.event_type == "new_ipo", IPOEventORM.stock_code.isnot(None))
            .order_by(IPOEventORM.created_at.asc())
            .all()
        )
        follow_ups = []
        included_codes: set[str] = set()
        for row in rows:
            if not row.stock_code or row.stock_code in included_codes:
                continue
            created_at = row.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            discovered_on = created_at.astimezone(hk_tz).date()
            if discovered_on >= today:
                continue

            ipo = self.get_ipo_by_code(row.stock_code)
            if (
                not ipo
                or not ipo.listing_date
                or ipo.listing_date < today
                or ipo.status in ("listed", "archived")
            ):
                continue

            detail_digest_key = f"digest:daily_digest:{discovered_on}"
            follow_ups.append(
                {
                    "stock_code": ipo.stock_code,
                    "event_type": "ipo_follow_up",
                    "title": f"持续跟踪: {ipo.stock_code} {ipo.stock_name or ''}",
                    "ipo": ipo.model_dump(
                        mode="json",
                        exclude={"raw_sources", "source_url", "created_at", "updated_at"},
                        exclude_none=True,
                    ),
                    "discovered_on": str(discovered_on),
                    "detail_digest_date": (
                        str(discovered_on)
                        if self.has_notification_been_sent(detail_digest_key)
                        else None
                    ),
                    "days_to_listing": (ipo.listing_date - today).days,
                }
            )
            included_codes.add(ipo.stock_code)
        return follow_ups


def _ipo_to_orm(ipo: IPOItem) -> IPOItemORM:
    """IPOItem 转 ORM。"""
    return IPOItemORM(
        stock_code=ipo.stock_code,
        stock_name=ipo.stock_name,
        stock_name_en=ipo.stock_name_en,
        market=ipo.market,
        industry=ipo.industry,
        business_overview=ipo.business_overview,
        status=ipo.status,
        subscription_start_date=str(ipo.subscription_start_date) if ipo.subscription_start_date else None,
        subscription_close_date=str(ipo.subscription_close_date) if ipo.subscription_close_date else None,
        listing_date=str(ipo.listing_date) if ipo.listing_date else None,
        offer_price_min=ipo.offer_price_min,
        offer_price_max=ipo.offer_price_max,
        final_offer_price=ipo.final_offer_price,
        lot_size=ipo.lot_size,
        entry_fee_hkd=ipo.entry_fee_hkd,
        market_cap_hkd=ipo.market_cap_hkd,
        sponsors_json=json.dumps(ipo.sponsors, ensure_ascii=False),
        cornerstone_investors_json=json.dumps(ipo.cornerstone_investors, ensure_ascii=False),
        raw_sources_json=json.dumps(ipo.raw_sources, ensure_ascii=False),
        source=ipo.source,
        source_url=ipo.source_url,
    )


def _orm_to_ipo(orm: IPOItemORM) -> IPOItem:
    """ORM 转 IPOItem。"""
    return IPOItem(
        stock_code=orm.stock_code,
        stock_name=orm.stock_name,
        stock_name_en=orm.stock_name_en,
        market=orm.market,
        industry=orm.industry,
        business_overview=orm.business_overview,
        status=orm.status or "unknown",
        subscription_start_date=_str_to_date(orm.subscription_start_date),
        subscription_close_date=_str_to_date(orm.subscription_close_date),
        listing_date=_str_to_date(orm.listing_date),
        offer_price_min=orm.offer_price_min,
        offer_price_max=orm.offer_price_max,
        final_offer_price=orm.final_offer_price,
        lot_size=orm.lot_size,
        entry_fee_hkd=orm.entry_fee_hkd,
        market_cap_hkd=orm.market_cap_hkd,
        sponsors=json.loads(orm.sponsors_json or "[]"),
        cornerstone_investors=json.loads(orm.cornerstone_investors_json or "[]"),
        raw_sources=json.loads(orm.raw_sources_json or "{}"),
        source=orm.source,
        source_url=orm.source_url,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _str_to_date(val: str | None) -> date | None:
    """字符串转日期。"""
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _source_priority(source: str | None) -> int:
    """官方来源应覆盖财经网站字段，低优先级来源仅补缺。"""
    priorities = {
        "mock": 0,
        "aastocks_ipo": 10,
        "futu_ipo": 20,
        "hkex_new_listing": 30,
        "hkex_news": 30,
    }
    return priorities.get(source or "", 0)


def _status_rank(status: str | None) -> int:
    lifecycle = {
        "unknown": 0,
        "planned": 1,
        "hearing_passed": 2,
        "subscription_open": 3,
        "subscription_closed": 4,
        "allotment_result_published": 5,
        "grey_market_trading": 6,
        "listed": 7,
        "archived": 8,
    }
    return lifecycle.get(status or "unknown", 0)
