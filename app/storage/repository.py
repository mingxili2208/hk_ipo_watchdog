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
    LLMEvaluation,
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
    LLMEvaluationORM,
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

    def save_llm_evaluation(
        self, stock_code: str, evaluation: LLMEvaluation, llm_score: int
    ) -> int:
        """保存 LLM 结构化评估。"""
        orm = LLMEvaluationORM(
            stock_code=stock_code,
            business_quality=evaluation.business_quality,
            business_quality_reason=evaluation.business_quality_reason,
            financial_health=evaluation.financial_health,
            financial_health_reason=evaluation.financial_health_reason,
            valuation_fairness=evaluation.valuation_fairness,
            valuation_fairness_reason=evaluation.valuation_fairness_reason,
            growth_prospect=evaluation.growth_prospect,
            growth_prospect_reason=evaluation.growth_prospect_reason,
            risk_level=evaluation.risk_level,
            risk_factors_json=json.dumps(evaluation.risk_factors, ensure_ascii=False),
            comparable_companies_json=json.dumps(
                evaluation.comparable_companies, ensure_ascii=False
            ),
            recommended_action=evaluation.recommended_action,
            confidence=evaluation.confidence,
            reasoning=evaluation.reasoning,
            evaluation_source=evaluation.evaluation_source,
            llm_score=llm_score,
        )
        self.session.add(orm)
        self.session.commit()
        return orm.id

    def get_latest_llm_evaluation(self, stock_code: str) -> LLMEvaluation | None:
        """获取最新的 LLM 评估。"""
        row = self._latest_llm_evaluation_row(stock_code)
        if not row:
            return None
        return _llm_evaluation_from_orm(row)

    def get_latest_llm_evaluation_with_meta(
        self, stock_code: str
    ) -> tuple[LLMEvaluation, datetime] | None:
        """获取最新 LLM 评估及创建时间。"""
        row = self._latest_llm_evaluation_row(stock_code)
        if not row:
            return None
        return _llm_evaluation_from_orm(row), row.created_at

    def _latest_llm_evaluation_row(self, stock_code: str) -> LLMEvaluationORM | None:
        return (
            self.session.query(LLMEvaluationORM)
            .filter(LLMEvaluationORM.stock_code == stock_code)
            .order_by(LLMEvaluationORM.created_at.desc())
            .first()
        )

    def get_active_ipos_for_digest(self, limit: int = 10) -> list[dict]:
        """获取 AI 评委分排名最高的活跃 IPO 日报展示快照。"""
        items = self._active_ipo_digest_candidates(include_failed=False)
        items = [item for item in items if item.get("ai_review_status") == "ranked"]
        items.sort(key=_active_ipo_digest_sort_key, reverse=True)
        for index, item in enumerate(items[:limit], start=1):
            item["rank"] = index
        return items[:limit]

    def get_ai_pending_ipos_for_digest(self, limit: int = 10) -> list[dict]:
        """获取没有有效 AI 评审但仍应在日报说明的 IPO。"""
        items = self._active_ipo_digest_candidates(include_failed=True)
        pending = [item for item in items if item.get("ai_review_status") != "ranked"]
        pending.sort(key=_pending_ipo_digest_sort_key, reverse=True)
        return pending[:limit]

    def _active_ipo_digest_candidates(self, include_failed: bool) -> list[dict]:
        rows = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.status.notin_(["listed", "archived"]))
            .order_by(IPOItemORM.listing_date.asc(), IPOItemORM.stock_code.asc())
            .all()
        )
        items = []
        for row in rows:
            ipo = _orm_to_ipo(row)
            if not _is_actionable_ipo_for_digest(ipo):
                continue
            llm_row = self._latest_llm_evaluation_row(ipo.stock_code)
            llm_eval = _llm_evaluation_from_orm(llm_row) if llm_row else None
            is_reviewed = bool(llm_row and llm_row.evaluation_source != "fallback")
            exclusion_reasons = _top_exclusion_reasons(ipo, llm_eval) if is_reviewed else []
            review_status = (
                "ranked"
                if is_reviewed and not exclusion_reasons
                else ("not_ranked" if is_reviewed else "pending")
            )
            if not include_failed and not is_reviewed:
                continue
            item = {
                "stock_code": ipo.stock_code,
                "event_type": "active_ipo_evaluation",
                "title": f"AI 关注榜: {ipo.stock_code} {ipo.stock_name or ''}",
                "ipo": ipo.model_dump(
                    mode="json",
                    exclude={"raw_sources", "source_url", "created_at", "updated_at"},
                    exclude_none=True,
                ),
                "company_overview": _company_overview_for_digest(ipo, llm_eval),
                "ai_score": llm_row.llm_score if llm_row else None,
                "ai_review_status": review_status,
                "unknown_fields": _unknown_ipo_fields_for_digest(ipo),
                "ai_review_note": _ai_review_note_for_digest(ipo, llm_row),
                "top_exclusion_reasons": exclusion_reasons,
            }
            if llm_eval:
                item["llm_evaluation"] = llm_eval.model_dump(mode="json")
            items.append(item)
        return items

    def get_sponsor_stats(self, sponsor_name: str) -> dict | None:
        """获取保荐人历史表现统计。

        基于已评估过的 IPO 的 StrategyScore 计算平均分和高分比例。
        """
        # 找到所有包含该保荐人的 IPO
        ipos = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.sponsors_json.contains(f'"{sponsor_name}"'))
            .all()
        )
        if not ipos:
            return None

        codes = [ipo.stock_code for ipo in ipos]
        scores = (
            self.session.query(StrategyScoreORM)
            .filter(StrategyScoreORM.stock_code.in_(codes))
            .all()
        )
        if not scores:
            return None

        latest_scores: dict[str, StrategyScoreORM] = {}
        for score in scores:
            existing = latest_scores.get(score.stock_code)
            if existing is None or _is_newer_datetime(
                score.evaluated_at, existing.evaluated_at
            ):
                latest_scores[score.stock_code] = score
        score_values = [s.score for s in latest_scores.values() if s.score is not None]
        if not score_values:
            return None

        # 获取 LLM 评分
        llm_evals = (
            self.session.query(LLMEvaluationORM)
            .filter(LLMEvaluationORM.stock_code.in_(codes))
            .all()
        )
        latest_llm: dict[str, LLMEvaluationORM] = {}
        for evaluation in llm_evals:
            existing = latest_llm.get(evaluation.stock_code)
            if existing is None or _is_newer_datetime(
                evaluation.created_at, existing.created_at
            ):
                latest_llm[evaluation.stock_code] = evaluation
        llm_score_values = [
            e.llm_score for e in latest_llm.values() if e.llm_score is not None
        ]

        avg_score = sum(score_values) / len(score_values)
        avg_llm = (
            sum(llm_score_values) / len(llm_score_values)
            if llm_score_values
            else 0
        )
        high_ratio = sum(1 for s in score_values if s >= 60) / len(score_values)

        return {
            "sponsor_name": sponsor_name,
            "total_ipo_count": len(codes),
            "avg_score": round(avg_score, 1),
            "avg_llm_score": round(avg_llm, 1),
            "high_score_ratio": round(high_ratio, 2),
        }

    def get_market_heat(self) -> dict:
        """获取近期 IPO 市场热度指标。"""
        from datetime import timedelta
        from app.utils.time_utils import today_hk

        today = today_hk()
        cutoff = today - timedelta(days=30)

        # 近 30 天有评分的 IPO（每只 IPO 只取最新一次评分）
        recent_scores = (
            self.session.query(StrategyScoreORM)
            .filter(
                StrategyScoreORM.evaluated_at >= datetime.combine(
                    cutoff, datetime.min.time()
                )
            )
            .all()
        )

        active_count = (
            self.session.query(IPOItemORM)
            .filter(IPOItemORM.status.notin_(["listed", "archived"]))
            .count()
        )

        if not recent_scores:
            return {
                "recent_ipo_count_30d": 0,
                "avg_score_30d": 0,
                "high_score_count_30d": 0,
                "active_ipo_count": active_count,
            }

        latest_scores: dict[str, StrategyScoreORM] = {}
        for score in recent_scores:
            existing = latest_scores.get(score.stock_code)
            if existing is None or _is_newer_datetime(
                score.evaluated_at, existing.evaluated_at
            ):
                latest_scores[score.stock_code] = score
        score_values = [s.score for s in latest_scores.values() if s.score is not None]
        avg = sum(score_values) / len(score_values) if score_values else 0
        high = sum(1 for s in score_values if s >= 60)

        return {
            "recent_ipo_count_30d": len(score_values),
            "avg_score_30d": round(avg, 1),
            "high_score_count_30d": high,
            "active_ipo_count": active_count,
        }

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
                # 附带 LLM 评估数据（如果有）
                llm_eval = self.get_latest_llm_evaluation(r.stock_code)
                if llm_eval:
                    event["llm_evaluation"] = llm_eval.model_dump(mode="json")
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


def _llm_evaluation_from_orm(row: LLMEvaluationORM) -> LLMEvaluation:
    """ORM 转 LLMEvaluation。"""
    return LLMEvaluation(
        business_quality=row.business_quality or 5,
        business_quality_reason=_reason_or_missing(row.business_quality_reason),
        financial_health=row.financial_health or 5,
        financial_health_reason=_reason_or_missing(row.financial_health_reason),
        valuation_fairness=row.valuation_fairness or 5,
        valuation_fairness_reason=_reason_or_missing(row.valuation_fairness_reason),
        growth_prospect=row.growth_prospect or 5,
        growth_prospect_reason=_reason_or_missing(row.growth_prospect_reason),
        risk_level=row.risk_level or "medium",
        risk_factors=json.loads(row.risk_factors_json or "[]"),
        comparable_companies=json.loads(row.comparable_companies_json or "[]"),
        recommended_action=row.recommended_action or "watch",
        confidence=row.confidence or "low",
        reasoning=row.reasoning or "",
        evaluation_source=row.evaluation_source or "llm",
    )


def _reason_or_missing(value: str | None) -> str:
    if value and value.strip():
        return value
    return "当前缺少可验证的事实依据，需补充招股书或人工复核。"


def _is_actionable_ipo_for_digest(ipo: IPOItem) -> bool:
    """过滤债券、权证、供股权等未进入 IPO 生命周期的噪音记录。"""
    actionable_statuses = {
        "planned",
        "hearing_passed",
        "subscription_open",
        "subscription_closed",
        "allotment_result_published",
        "grey_market_trading",
    }
    if ipo.status in actionable_statuses:
        return True
    return bool(
        ipo.subscription_start_date
        or ipo.subscription_close_date
        or ipo.listing_date
        or ipo.business_overview
    )


def _company_overview_for_digest(
    ipo: IPOItem, evaluation: LLMEvaluation | None
) -> str:
    """优先使用官方章程摘要；缺失时给出可核查的评估摘录或缺失提示。"""
    if ipo.business_overview:
        return ipo.business_overview
    if evaluation and evaluation.business_quality_reason:
        return f"官方主营摘要缺失；AI 可核查业务线索: {evaluation.business_quality_reason}"
    return "暂无官方章程主营摘要；需等待招股书解析或人工补充。"


def _unknown_ipo_fields_for_digest(ipo: IPOItem) -> list[str]:
    fields = []
    checks = {
        "公司主营业务": ipo.business_overview,
        "行业": ipo.industry,
        "招股开始日": ipo.subscription_start_date,
        "招股截止日": ipo.subscription_close_date,
        "上市日": ipo.listing_date,
        "发售价": ipo.offer_price_min or ipo.offer_price_max or ipo.final_offer_price,
        "每手股数": ipo.lot_size,
        "入场费": ipo.entry_fee_hkd,
        "保荐人": ipo.sponsors,
    }
    for label, value in checks.items():
        if value in (None, "", [], {}):
            fields.append(label)
    return fields


def _ai_review_note_for_digest(
    ipo: IPOItem, row: LLMEvaluationORM | None
) -> str:
    if row is None:
        return "尚未取得有效 AI 评审结果。"
    if row.evaluation_source == "fallback":
        return "LLM 评审失败，当前仅有 fallback 结果；不作为 AI 评委分。"
    if _unknown_ipo_fields_for_digest(ipo):
        return "AI 已完成评审，但仍存在部分 unknown 字段。"
    return "AI 已完成评审。"


def _top_exclusion_reasons(
    ipo: IPOItem, evaluation: LLMEvaluation | None
) -> list[str]:
    """AI Top 榜只保留信息足够且未被 AI 判定为不适合的股票。"""
    reasons = []
    unknown = set(_unknown_ipo_fields_for_digest(ipo))
    critical_unknown = [
        field
        for field in ("公司主营业务", "招股截止日", "上市日", "入场费")
        if field in unknown
    ]
    if critical_unknown:
        reasons.append(f"关键字段 unknown: {'、'.join(critical_unknown)}")

    if not ipo.business_overview:
        reasons.append("缺少官方章程主营摘要")

    if evaluation:
        if evaluation.recommended_action == "skip":
            reasons.append("AI 建议放弃")
        if evaluation.risk_level == "very_high":
            reasons.append("AI 风险等级为极高")
    else:
        reasons.append("尚无真实 AI 评审")

    return reasons


def _active_ipo_digest_sort_key(item: dict) -> tuple:
    ipo = item.get("ipo") or {}
    score = item.get("ai_score")
    has_score = score is not None
    has_overview = bool(
        ipo.get("business_overview")
        or (item.get("company_overview") and "暂无官方" not in item["company_overview"])
    )
    status_rank = {
        "subscription_open": 5,
        "hearing_passed": 4,
        "planned": 3,
        "subscription_closed": 2,
        "allotment_result_published": 1,
        "grey_market_trading": 1,
    }.get(ipo.get("status"), 0)
    return (
        1 if has_score else 0,
        score or -1,
        1 if has_overview else 0,
        status_rank,
    )


def _pending_ipo_digest_sort_key(item: dict) -> tuple:
    ipo = item.get("ipo") or {}
    status_rank = {
        "subscription_open": 5,
        "hearing_passed": 4,
        "planned": 3,
        "subscription_closed": 2,
        "allotment_result_published": 1,
        "grey_market_trading": 1,
    }.get(ipo.get("status"), 0)
    known_count = 9 - len(item.get("unknown_fields") or [])
    return (status_rank, known_count)


def _is_newer_datetime(left: datetime | None, right: datetime | None) -> bool:
    """比较可能缺失或时区不一致的数据库时间戳。"""
    return _datetime_sort_value(left) > _datetime_sort_value(right)


def _datetime_sort_value(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


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
