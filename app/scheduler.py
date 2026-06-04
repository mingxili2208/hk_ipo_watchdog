"""调度器 — 定时任务管理。"""

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from app.settings import Settings
from app.storage.repository import Repository
from app.strategy.config_loader import StrategyConfig
from app.llm.client import LLMService
from app.models import IPOItem, AllotmentResult, GreyMarketQuote, StrategyDecision


def _llm_evaluation_is_stale(evaluation, created_at) -> bool:
    """判断缓存的 LLM 评估是否过期。"""
    from datetime import datetime, timedelta, timezone

    if any(
        not getattr(evaluation, field, "").strip()
        or "当前缺少可验证的事实依据" in getattr(evaluation, field, "")
        for field in (
            "business_quality_reason",
            "financial_health_reason",
            "valuation_fairness_reason",
            "growth_prospect_reason",
        )
    ):
        return True

    if created_at is None:
        return True
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    ttl = (
        timedelta(hours=6)
        if evaluation.evaluation_source == "fallback"
        else timedelta(hours=24)
    )
    return datetime.now(timezone.utc) - created_at >= ttl


class SchedulerApp:
    """定时任务调度器。"""

    def __init__(
        self,
        settings: Settings,
        strategy_config: StrategyConfig,
        llm_service: LLMService,
        repository: Repository,
        dry_run: bool = False,
    ):
        self.settings = settings
        self.strategy_config = strategy_config
        self.llm_service = llm_service
        self.repo = repository
        self.dry_run = dry_run
        self.scheduler = BlockingScheduler()
        self._notifiers = None

    def _get_notifiers(self) -> list:
        """懒加载 notifiers。"""
        if self._notifiers is not None:
            return self._notifiers

        import os
        notifiers = []
        notif = self.settings.notification

        if notif.telegram.enabled:
            token = os.environ.get(notif.telegram.bot_token_env, "")
            chat_id = os.environ.get(notif.telegram.chat_id_env, "")
            if token and chat_id:
                from app.notifier.telegram import TelegramNotifier
                notifiers.append(("telegram", TelegramNotifier(token, chat_id), notif.telegram.min_level))

        if notif.email.enabled:
            host = notif.email.smtp_host
            port = notif.email.smtp_port
            username = os.environ.get(notif.email.username_env, "")
            password = os.environ.get(notif.email.password_env, "")
            receivers = self.settings.recipients.email
            if username and password and receivers:
                from app.notifier.email import EmailNotifier
                notifiers.append(
                    (
                        "email",
                        EmailNotifier(host, port, username, password, receivers, notif.email.encryption),
                        notif.email.min_level,
                    )
                )
            else:
                logger.warning("Email enabled but SMTP credentials or recipients are not configured")

        if notif.bark.enabled:
            key = os.environ.get(notif.bark.device_key_env, "")
            if key:
                from app.notifier.bark import BarkNotifier
                notifiers.append(("bark", BarkNotifier(key), notif.bark.min_level))

        if notif.server_chan.enabled:
            key = os.environ.get(notif.server_chan.send_key_env, "")
            if key:
                from app.notifier.server_chan import ServerChanNotifier
                notifiers.append(("server_chan", ServerChanNotifier(key), notif.server_chan.min_level))

        self._notifiers = notifiers
        return notifiers

    def _send_notification(
        self,
        title: str,
        body: str,
        level: int,
        notification_key: str | None = None,
        stock_code: str | None = None,
        notification_type: str | None = None,
    ) -> list:
        """发送通知到所有已启用渠道。"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would send notification: {title}")
            return []
        if self._in_quiet_hours():
            logger.info(f"Notification suppressed during quiet hours: {notification_key or title}")
            return []
        if notification_key and self.repo.has_notification_been_sent(notification_key):
            logger.info(f"Notification already sent, skipping: {notification_key}")
            return []

        eligible = [
            (channel_name, notifier, min_level)
            for channel_name, notifier, min_level in self._get_notifiers()
            if level >= min_level
        ]
        delivered = (
            self.repo.get_delivered_notification_channels(notification_key)
            if notification_key
            else set()
        )
        results = []
        for channel_name, notifier, _ in eligible:
            if channel_name in delivered:
                continue

            channel_body = body
            if channel_name == "email":
                from app.notifier.formatter import append_daily_llm_usage

                channel_body = append_daily_llm_usage(
                    body, self.repo.get_llm_usage_for_hk_day()
                )
            result = notifier.send(title, channel_body)
            results.append(result)
            if result.success:
                delivered.add(channel_name)

        if notification_key and (results or delivered):
            target_channels = [channel_name for channel_name, _, _ in eligible]
            delivered_channels = [channel for channel in target_channels if channel in delivered]
            all_delivered = bool(target_channels) and set(target_channels).issubset(delivered)
            status = "sent" if all_delivered else ("partial" if delivered else "failed")
            errors = [
                f"{result.channel}: {result.error_message}"
                for result in results
                if not result.success and result.error_message
            ]
            try:
                self.repo.record_notification(
                    notification_key=notification_key,
                    stock_code=stock_code,
                    notification_type=notification_type or "unknown",
                    level=level,
                    channel=",".join(delivered_channels),
                    title=title,
                    body=body,
                    status=status,
                    error_message="; ".join(errors) or None,
                )
            except Exception as e:
                self.repo.session.rollback()
                logger.error(f"Failed to record notification: {e}")

        return results

    def _in_quiet_hours(self) -> bool:
        """判断当前香港时间是否处于配置的静默时间窗口。"""
        quiet = self.settings.notification.quiet_hours
        if not quiet.enabled:
            return False

        from datetime import time
        from app.utils.time_utils import now_hk

        start = time.fromisoformat(quiet.start)
        end = time.fromisoformat(quiet.end)
        current = now_hk().time().replace(tzinfo=None)
        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def _evaluate_and_notify(
        self,
        ipo: IPOItem,
        allotment: AllotmentResult | None = None,
        grey: GreyMarketQuote | None = None,
    ) -> StrategyDecision:
        """评分当前事件，并在满足策略和去重规则时发送通知。"""
        from app.notifier.formatter import format_notification
        from app.strategy.rule_engine import evaluate_ipo, finalize_notification_decision
        from app.strategy.scoring import (
            calculate_llm_score,
        )

        decision = evaluate_ipo(ipo, self.strategy_config, allotment, grey)

        # ── LLM 结构化评估（申购推荐阶段） ──
        llm_eval = self._refresh_llm_evaluation_if_needed(ipo)

        # ── 综合评分 ──
        if llm_eval is not None:
            llm_score = calculate_llm_score(llm_eval)
            if llm_score != decision.score:
                rule_score = decision.score
                logger.info(
                    f"AI judge score for {ipo.stock_code}: "
                    f"rule={rule_score} ai={llm_score}"
                )
                from app.strategy.scoring import decide_alert_level

                decision = decision.model_copy(
                    update={
                        "score": llm_score,
                        "level": decide_alert_level(llm_score, self.strategy_config),
                        "score_breakdown": [
                            f"AI 评委分: {llm_score}/100",
                            f"规则分仅作参考: {rule_score}/100",
                        ],
                    }
                )
                decision = finalize_notification_decision(
                    decision, ipo, self.strategy_config, allotment, grey
                )

        self.repo.save_strategy_score(decision)
        if not decision.should_notify or not decision.notification_key:
            return decision
        if self.repo.has_notification_been_sent(decision.notification_key):
            return decision

        summary = self.llm_service.summarize_ipo_alert(ipo, decision, allotment, grey)
        self.repo.save_llm_summary(ipo.stock_code, decision.notification_key, summary)
        title, body = format_notification(summary, decision, ipo, llm_eval=llm_eval)
        self._send_notification(
            title=title,
            body=body,
            level=decision.level,
            notification_key=decision.notification_key,
            stock_code=ipo.stock_code,
            notification_type=decision.notification_type,
        )
        return decision

    def _refresh_llm_evaluation_if_needed(
        self, ipo: IPOItem, force: bool = False
    ) -> "LLMEvaluation | None":
        """按状态和过期策略刷新 LLM 申购评估。"""
        if ipo.status not in (
            "planned",
            "hearing_passed",
            "subscription_open",
            "subscription_closed",
            "allotment_result_published",
            "grey_market_trading",
        ):
            return None

        latest = self.repo.get_latest_llm_evaluation_with_meta(ipo.stock_code)
        if latest and not force:
            evaluation, created_at = latest
            if not _llm_evaluation_is_stale(evaluation, created_at):
                return evaluation

        try:
            from app.strategy.scoring import calculate_llm_score

            financials = self._extract_prospectus_financials(ipo)
            sponsor_stats = self._get_sponsor_stats(ipo)
            market_heat_data = self._get_market_heat()

            evaluation = self.llm_service.evaluate_ipo_enriched(
                ipo,
                financials=financials,
                sponsor_stats=sponsor_stats,
                market_heat=market_heat_data,
            )
            llm_score = calculate_llm_score(evaluation)
            self.repo.save_llm_evaluation(ipo.stock_code, evaluation, llm_score)
            logger.info(
                f"LLM evaluation refreshed for {ipo.stock_code}: "
                f"score={llm_score}, action={evaluation.recommended_action}, "
                f"source={evaluation.evaluation_source}"
            )
            return evaluation
        except Exception as e:
            logger.warning(f"LLM evaluation failed for {ipo.stock_code}: {e}")
            return latest[0] if latest else None

    def _extract_prospectus_financials(
        self, ipo: IPOItem
    ) -> "ProspectusFinancials | None":
        """尝试从招股书提取财务数据。失败时返回 None。"""
        official = (ipo.raw_sources or {}).get("hkex_new_listing") or {}
        prospectus_url = official.get("prospectus_url")
        if not prospectus_url:
            return None

        try:
            from app.collectors.hkex_new_listing import HKEXNewListingCollector

            source_settings = self.settings.sources.hkex_new_listing
            collector = HKEXNewListingCollector(
                timeout=source_settings.timeout_seconds
            )
            text = collector._fetch_document_text(prospectus_url)
            if not text or len(text) < 200:
                return None

            financials = self.llm_service.extract_financials(text)
            if financials.revenue_hkd_million is not None:
                logger.info(
                    f"Prospectus financials extracted for {ipo.stock_code}: "
                    f"revenue={financials.revenue_hkd_million}M"
                )
            return financials
        except Exception as e:
            logger.debug(
                f"Prospectus financial extraction failed for "
                f"{ipo.stock_code}: {e}"
            )
            return None

    def _get_sponsor_stats(self, ipo: IPOItem) -> "SponsorStats | None":
        """获取保荐人历史表现统计。取第一个保荐人的数据。"""
        if not ipo.sponsors:
            return None
        try:
            stats = self.repo.get_sponsor_stats(ipo.sponsors[0])
            if stats:
                from app.models import SponsorStats

                return SponsorStats(**stats)
        except Exception as e:
            logger.debug(f"Sponsor stats lookup failed: {e}")
        return None

    def _get_market_heat(self) -> "MarketHeat | None":
        """获取近期 IPO 市场热度指标。"""
        try:
            data = self.repo.get_market_heat()
            from app.models import MarketHeat

            return MarketHeat(**data)
        except Exception as e:
            logger.debug(f"Market heat lookup failed: {e}")
            return None

    def _enrich_business_overview(self, ipo: IPOItem) -> IPOItem:
        """对缺失主营摘要的 IPO 从官方章程补充一次短概览。"""
        if ipo.business_overview:
            from app.collectors.hkex_new_listing import summarize_business_overview

            shortened = summarize_business_overview(ipo.business_overview)
            if shortened and shortened != ipo.business_overview:
                ipo = ipo.model_copy(update={"business_overview": shortened})
                self.repo.upsert_ipo(ipo)
                logger.info(f"IPO business overview shortened: {ipo.stock_code}")
            return ipo
        official = (ipo.raw_sources or {}).get("hkex_new_listing") or {}
        prospectus_url = official.get("prospectus_url")
        if not prospectus_url:
            return ipo

        try:
            from app.collectors.hkex_new_listing import HKEXNewListingCollector

            source_settings = self.settings.sources.hkex_new_listing
            collector = HKEXNewListingCollector(timeout=source_settings.timeout_seconds)
            overview = collector.fetch_business_overview(prospectus_url)
            if not overview:
                logger.warning(f"No IPO business overview extracted: {ipo.stock_code}")
                return ipo
            enriched = ipo.model_copy(update={"business_overview": overview})
            self.repo.upsert_ipo(enriched)
            logger.info(f"IPO business overview enriched: {ipo.stock_code}")
            return self.repo.get_ipo_by_code(ipo.stock_code) or enriched
        except Exception as e:
            logger.warning(f"IPO business overview enrichment failed for {ipo.stock_code}: {e}")
            return ipo

    def job_collect_ipo_calendar(self) -> None:
        """定时采集 IPO 日历。"""
        logger.info("Job: collect_ipo_calendar started")
        try:
            items = self._collect_all_ipo_sources()
            created_codes: set[str] = set()

            for item in items:
                result = self.repo.upsert_ipo(item)
                stored_item = self.repo.get_ipo_by_code(item.stock_code) or item
                stored_item = self._enrich_business_overview(stored_item)
                changed_fields = [
                    field
                    for field in result.changed_fields
                    if field not in {"raw_sources", "business_overview"}
                ]
                if result.created:
                    created_codes.add(stored_item.stock_code)
                    if stored_item.status == "subscription_open":
                        logger.info(f"New IPO found: {stored_item.stock_code} {stored_item.stock_name}")
                        self.repo.add_event(
                            stock_code=stored_item.stock_code,
                            event_type="new_ipo",
                            event_key=f"new_ipo_{stored_item.stock_code}_{stored_item.subscription_start_date or 'unknown'}",
                            title=f"发现新 IPO: {stored_item.stock_code} {stored_item.stock_name}",
                        )
                    else:
                        logger.info(f"IPO seeded for lifecycle tracking: {stored_item.stock_code} ({stored_item.status})")
                elif changed_fields and stored_item.stock_code not in created_codes:
                    logger.info(f"IPO updated: {stored_item.stock_code}, changed: {changed_fields}")
                    update_tag = (
                        stored_item.updated_at.isoformat()
                        if stored_item.updated_at
                        else "_".join(changed_fields)
                    )
                    self.repo.add_event(
                        stock_code=stored_item.stock_code,
                        event_type="ipo_updated",
                        event_key=f"ipo_updated_{stored_item.stock_code}_{update_tag}",
                        title=f"IPO 信息更新: {stored_item.stock_code} {stored_item.stock_name or ''}",
                        detail={"changed_fields": changed_fields},
                    )

                allotment = self.repo.get_latest_allotment(stored_item.stock_code)
                grey = self.repo.get_latest_grey_quote(stored_item.stock_code)
                self._evaluate_and_notify(stored_item, allotment, grey)

            logger.info(f"Job: collect_ipo_calendar done, {len(items)} items processed")
        except Exception as e:
            logger.error(f"Job: collect_ipo_calendar failed: {e}")

    def job_collect_announcements(self) -> None:
        """定时采集公告。"""
        logger.info("Job: collect_announcements started")
        try:
            announcements = self._collect_announcements()

            for ann in announcements:
                if (
                    ann.announcement_type == "allotment_result"
                    and ann.stock_code
                    and not self.repo.get_ipo_by_code(ann.stock_code)
                ):
                    logger.info(f"Skipping allotment for untracked IPO: {ann.stock_code}")
                    continue
                ann_id = self.repo.save_announcement(ann)

                if (
                    ann.announcement_type == "allotment_result"
                    and ann.stock_code
                    and ann.raw_text
                    and not self.repo.has_allotment_for_announcement(ann_id)
                ):
                    from app.parsers.allotment_parser import parse_allotment_result_text

                    allotment = parse_allotment_result_text(ann.raw_text, ann.stock_code)
                    allotment.announcement_id = ann_id
                    self.repo.save_allotment_result(allotment)

                    self.repo.add_event(
                        stock_code=ann.stock_code,
                        event_type="allotment_result",
                        event_key=f"allotment_{ann.stock_code}_{ann_id}",
                        title=f"配发结果: {ann.stock_code} {ann.stock_name or ''}",
                    )
                    ipo = self.repo.get_ipo_by_code(ann.stock_code)
                    if ipo:
                        self._evaluate_and_notify(ipo, allotment, self.repo.get_latest_grey_quote(ann.stock_code))

            logger.info(f"Job: collect_announcements done, {len(announcements)} items")
        except Exception as e:
            logger.error(f"Job: collect_announcements failed: {e}")

    def job_collect_grey_market(self, ignore_window: bool = False) -> None:
        """定时采集暗盘。"""
        if not ignore_window and not self._in_grey_market_window():
            logger.debug("Job: collect_grey_market skipped outside configured market window")
            return

        logger.info("Job: collect_grey_market started")
        try:
            from app.strategy.rule_engine import grey_market_alert_event_key

            active_ipos = self.repo.get_active_ipos()
            stock_codes = [ipo.stock_code for ipo in active_ipos]
            if not stock_codes:
                logger.debug("Job: collect_grey_market skipped with no active IPOs")
                return

            quotes = self._collect_grey_market(stock_codes)
            for quote in quotes:
                self.repo.save_grey_market_quote(quote)
                ipo = self.repo.get_ipo_by_code(quote.stock_code)
                if not ipo:
                    continue
                alert_event_key = grey_market_alert_event_key(quote, self.strategy_config)
                if alert_event_key:
                    self.repo.add_event(
                        stock_code=quote.stock_code,
                        event_type="grey_market_breakout",
                        event_key=f"{quote.stock_code}_{alert_event_key}",
                        title=f"暗盘异动: {quote.stock_code} {quote.change_percent:.1f}%",
                    )
                self._evaluate_and_notify(ipo, self.repo.get_latest_allotment(quote.stock_code), quote)

            logger.info(f"Job: collect_grey_market done, {len(quotes)} quotes")
        except Exception as e:
            logger.error(f"Job: collect_grey_market failed: {e}")

    def _in_grey_market_window(self) -> bool:
        """判断是否位于配置的香港暗盘采集时段。"""
        from datetime import time
        from app.utils.time_utils import now_hk

        sched = self.settings.schedule.grey_market
        current = now_hk()
        if sched.weekdays_only and current.weekday() >= 5:
            return False
        if not sched.window_start or not sched.window_end:
            return True

        start = time.fromisoformat(sched.window_start)
        end = time.fromisoformat(sched.window_end)
        current_time = current.time().replace(tzinfo=None)
        if start <= end:
            return start <= current_time <= end
        return current_time >= start or current_time <= end

    def job_send_daily_digest(self, resend: bool = False) -> None:
        """每日汇总推送。"""
        logger.info("Job: send_daily_digest started")
        try:
            from app.utils.time_utils import now_hk, today_hk
            from app.utils.dedup import make_notification_key

            event_key = str(today_hk())
            daily_key = make_notification_key("digest", "daily_digest", event_key)
            if not resend and self.repo.has_notification_been_sent(daily_key):
                logger.info(f"Daily digest already sent, skipping: {daily_key}")
                return
            notif_key = (
                f"{daily_key}:resend:{now_hk().strftime('%H%M%S%f')}"
                if resend
                else daily_key
            )

            self._refresh_digest_ai_evaluations()
            events = self._attach_digest_scores(self.repo.get_today_events())
            follow_ups = self._attach_follow_up_ai_evaluations(
                self.repo.get_ipo_follow_ups_for_digest()
            )
            active_evaluations = self.repo.get_active_ipos_for_digest()
            pending_evaluations = self.repo.get_ai_pending_ipos_for_digest()
            summary = self.llm_service.summarize_daily_digest(
                events + follow_ups + active_evaluations + pending_evaluations
            )
            self.repo.save_llm_summary(None, notif_key, summary)

            from app.notifier.formatter import format_daily_digest
            title, body = format_daily_digest(
                summary,
                events,
                follow_ups,
                active_evaluations,
                pending_evaluations,
                self.settings.notification.digest_version_update.model_dump(mode="json"),
            )
            if resend:
                title = f"[补发] {title}"
                body = f"补发说明: 本邮件为 {event_key} 日报的更新补发版本。\n\n{body}"

            self._send_notification(
                title=title,
                body=body,
                level=2,
                notification_key=notif_key,
                stock_code=None,
                notification_type="daily_digest",
            )

            logger.info(f"Job: send_daily_digest done{' (resend)' if resend else ''}")
        except Exception as e:
            logger.error(f"Job: send_daily_digest failed: {e}")

    def job_refresh_llm_evaluations(self, force: bool = False) -> None:
        """刷新活跃 IPO 的 LLM 申购评估。"""
        logger.info("Job: refresh_llm_evaluations started")
        try:
            refreshed = 0
            skipped = 0
            for ipo in self.repo.get_active_ipos():
                if ipo.status not in (
                    "planned",
                    "hearing_passed",
                    "subscription_open",
                    "subscription_closed",
                    "allotment_result_published",
                    "grey_market_trading",
                ):
                    skipped += 1
                    continue
                before = self.repo.get_latest_llm_evaluation_with_meta(ipo.stock_code)
                evaluation = self._refresh_llm_evaluation_if_needed(ipo, force=force)
                after = self.repo.get_latest_llm_evaluation_with_meta(ipo.stock_code)
                if evaluation and after and (not before or after[1] != before[1]):
                    refreshed += 1
                else:
                    skipped += 1
            logger.info(
                f"Job: refresh_llm_evaluations done, "
                f"{refreshed} refreshed, {skipped} skipped"
            )
        except Exception as e:
            logger.error(f"Job: refresh_llm_evaluations failed: {e}")

    def _attach_digest_scores(self, events: list[dict]) -> list[dict]:
        """仅保留已完成真实 AI 评审的日报事件，并附 AI 评委分。"""
        from datetime import datetime
        from app.strategy.scoring import calculate_llm_score, decide_alert_level

        decisions: dict[str, StrategyDecision] = {}
        filtered_events = []
        for event in events:
            stock_code = event.get("stock_code")
            if not stock_code:
                continue
            decision = decisions.get(stock_code)
            if decision is None:
                ipo = self.repo.get_ipo_by_code(stock_code)
                if not ipo:
                    continue
                llm_eval = self._refresh_llm_evaluation_if_needed(ipo)
                if not llm_eval or llm_eval.evaluation_source == "fallback":
                    continue
                ai_score = calculate_llm_score(llm_eval)
                decision = StrategyDecision(
                    stock_code=stock_code,
                    passed=True,
                    score=ai_score,
                    level=decide_alert_level(ai_score, self.strategy_config),
                    score_breakdown=[
                        f"AI 评委分: {ai_score}/100",
                        "日报主评分采用 AI 评审体系",
                    ],
                    evaluated_at=datetime.now(),
                )
                self.repo.save_strategy_score(decision)
                decisions[stock_code] = decision
            score_payload = decision.model_dump(mode="json")
            score_payload["score_source"] = "ai_judge"
            event["strategy_score"] = score_payload
            latest_eval = self.repo.get_latest_llm_evaluation(stock_code)
            if latest_eval:
                event["llm_evaluation"] = latest_eval.model_dump(mode="json")
            filtered_events.append(event)
        return filtered_events

    def _attach_follow_up_ai_evaluations(self, follow_ups: list[dict]) -> list[dict]:
        """仅保留已完成真实 AI 评审的持续跟踪项。"""
        from app.strategy.scoring import calculate_llm_score

        enriched = []
        for item in follow_ups:
            stock_code = item.get("stock_code")
            if not stock_code:
                continue
            ipo = self.repo.get_ipo_by_code(stock_code)
            if not ipo:
                continue
            llm_eval = self._refresh_llm_evaluation_if_needed(ipo)
            if not llm_eval or llm_eval.evaluation_source == "fallback":
                continue
            item["llm_evaluation"] = llm_eval.model_dump(mode="json")
            item["ai_score"] = calculate_llm_score(llm_eval)
            item["company_overview"] = ipo.business_overview or llm_eval.business_quality_reason
            enriched.append(item)
        return enriched

    def _refresh_digest_ai_evaluations(self) -> None:
        """日报生成前刷新所有活跃候选股票的 AI 评审。"""
        for ipo in self.repo.get_active_ipos():
            self._refresh_llm_evaluation_if_needed(ipo)

    def _collect_all_ipo_sources(self) -> list:
        """从所有启用的数据源采集 IPO 日历。"""
        items: list[IPOItem] = []
        sources = self.settings.sources

        if sources.hkex_new_listing.enabled:
            try:
                from app.collectors.hkex_new_listing import HKEXNewListingCollector
                collector = HKEXNewListingCollector(
                    url=sources.hkex_new_listing.url,
                    timeout=sources.hkex_new_listing.timeout_seconds,
                )
                items.extend(collector.collect())
            except Exception as e:
                logger.error(f"HKEX new listing collect failed: {e}")

        if sources.aastocks_ipo.enabled:
            try:
                from app.collectors.aastocks_ipo import AAStocksIPOCollector
                collector = AAStocksIPOCollector(
                    url=sources.aastocks_ipo.url,
                    timeout=sources.aastocks_ipo.timeout_seconds,
                )
                items.extend(collector.collect())
            except Exception as e:
                logger.error(f"AAStocks IPO collect failed: {e}")

        if not items:
            logger.warning("No IPO data collected from configured sources")

        return items

    def _collect_announcements(self) -> list:
        """采集公告。"""
        from app.models import Announcement
        announcements: list[Announcement] = []

        if self.settings.sources.hkex_news.enabled:
            try:
                from app.collectors.hkex_news import HKEXNewsCollector
                collector = HKEXNewsCollector(
                    url=self.settings.sources.hkex_news.url,
                    timeout=self.settings.sources.hkex_news.timeout_seconds,
                    lookback_hours=self.settings.sources.hkex_news.lookback_hours,
                )
                announcements.extend(collector.collect())
            except Exception as e:
                logger.error(f"HKEX News collect failed: {e}")

        return announcements

    def _collect_grey_market(self, stock_codes: list[str]) -> list:
        """采集暗盘。"""
        if not self.settings.sources.grey_market.enabled:
            return []

        from app.collectors.grey_market import GreyMarketCollector
        try:
            collector = GreyMarketCollector(
                sources=self.settings.sources.grey_market.sources,
                timeout=self.settings.sources.grey_market.timeout_seconds,
                collect_mode=self.settings.sources.grey_market.collect_mode,
            )
            return collector.collect(stock_codes)
        except Exception as e:
            logger.error(f"Grey market collect failed: {e}")
            return []

    def setup_jobs(self) -> None:
        """注册定时任务。"""
        sched = self.settings.schedule

        if sched.ipo_calendar.enabled and sched.ipo_calendar.time is None:
            self.scheduler.add_job(
                self.job_collect_ipo_calendar,
                "interval",
                minutes=sched.ipo_calendar.interval_minutes,
                id="collect_ipo_calendar",
                max_instances=1,
            )

        if sched.hkex_announcements.enabled and sched.hkex_announcements.time is None:
            self.scheduler.add_job(
                self.job_collect_announcements,
                "interval",
                minutes=sched.hkex_announcements.interval_minutes,
                id="collect_announcements",
                max_instances=1,
            )

        if sched.allotment_results.enabled and sched.allotment_results.time is None:
            self.scheduler.add_job(
                self.job_collect_announcements,
                "interval",
                minutes=sched.allotment_results.interval_minutes,
                id="collect_allotment_results",
                max_instances=1,
            )

        if sched.grey_market.enabled and sched.grey_market.time is None:
            self.scheduler.add_job(
                self.job_collect_grey_market,
                "interval",
                minutes=sched.grey_market.interval_minutes,
                id="collect_grey_market",
                max_instances=1,
            )

        if sched.daily_digest.enabled and sched.daily_digest.time:
            from apscheduler.triggers.cron import CronTrigger

            hour, minute = sched.daily_digest.time.split(":")
            self.scheduler.add_job(
                self.job_send_daily_digest,
                CronTrigger(
                    hour=int(hour),
                    minute=int(minute),
                    timezone=sched.daily_digest.timezone,
                ),
                id="daily_digest",
                max_instances=1,
            )

        if sched.llm_evaluation.enabled and sched.llm_evaluation.time:
            from apscheduler.triggers.cron import CronTrigger

            hour, minute = sched.llm_evaluation.time.split(":")
            self.scheduler.add_job(
                self.job_refresh_llm_evaluations,
                CronTrigger(
                    hour=int(hour),
                    minute=int(minute),
                    timezone=sched.llm_evaluation.timezone,
                ),
                id="refresh_llm_evaluations",
                max_instances=1,
            )

    def start(self) -> None:
        """启动调度器。"""
        self.setup_jobs()
        logger.info("Scheduler started")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped")
        finally:
            from app.utils.browser import BrowserManager
            BrowserManager.close_singleton()
