"""调度器 — 定时任务管理。"""

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from app.settings import Settings
from app.storage.repository import Repository
from app.strategy.config_loader import StrategyConfig
from app.llm.client import LLMService
from app.models import IPOItem, AllotmentResult, GreyMarketQuote, StrategyDecision


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

            result = notifier.send(title, body)
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
        from app.strategy.rule_engine import evaluate_ipo

        decision = evaluate_ipo(ipo, self.strategy_config, allotment, grey)
        self.repo.save_strategy_score(decision)
        if not decision.should_notify or not decision.notification_key:
            return decision
        if self.repo.has_notification_been_sent(decision.notification_key):
            return decision

        summary = self.llm_service.summarize_ipo_alert(ipo, decision, allotment, grey)
        self.repo.save_llm_summary(ipo.stock_code, decision.notification_key, summary)
        title, body = format_notification(summary, decision, ipo)
        self._send_notification(
            title=title,
            body=body,
            level=decision.level,
            notification_key=decision.notification_key,
            stock_code=ipo.stock_code,
            notification_type=decision.notification_type,
        )
        return decision

    def job_collect_ipo_calendar(self) -> None:
        """定时采集 IPO 日历。"""
        logger.info("Job: collect_ipo_calendar started")
        try:
            items = self._collect_all_ipo_sources()
            created_codes: set[str] = set()

            for item in items:
                result = self.repo.upsert_ipo(item)
                stored_item = self.repo.get_ipo_by_code(item.stock_code) or item
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
                elif result.changed_fields and stored_item.stock_code not in created_codes:
                    logger.info(f"IPO updated: {stored_item.stock_code}, changed: {result.changed_fields}")
                    update_tag = (
                        stored_item.updated_at.isoformat()
                        if stored_item.updated_at
                        else "_".join(result.changed_fields)
                    )
                    self.repo.add_event(
                        stock_code=stored_item.stock_code,
                        event_type="ipo_updated",
                        event_key=f"ipo_updated_{stored_item.stock_code}_{update_tag}",
                        title=f"IPO 信息更新: {stored_item.stock_code} {stored_item.stock_name or ''}",
                        detail={"changed_fields": result.changed_fields},
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

    def job_collect_grey_market(self) -> None:
        """定时采集暗盘。"""
        logger.info("Job: collect_grey_market started")
        try:
            active_ipos = self.repo.get_active_ipos()
            stock_codes = [ipo.stock_code for ipo in active_ipos]

            quotes = self._collect_grey_market(stock_codes)
            for quote in quotes:
                self.repo.save_grey_market_quote(quote)
                ipo = self.repo.get_ipo_by_code(quote.stock_code)
                if not ipo:
                    continue
                if (
                    quote.change_percent is not None
                    and (
                        quote.change_percent >= self.strategy_config.grey_market.min_grey_gain_percent
                        or quote.change_percent <= self.strategy_config.grey_market.alert_if_below_percent
                    )
                ):
                    self.repo.add_event(
                        stock_code=quote.stock_code,
                        event_type="grey_market_breakout",
                        event_key=f"grey_{quote.stock_code}_{quote.source}_{quote.quoted_at.strftime('%Y%m%d%H%M')}",
                        title=f"暗盘异动: {quote.stock_code} {quote.change_percent:.1f}%",
                    )
                self._evaluate_and_notify(ipo, self.repo.get_latest_allotment(quote.stock_code), quote)

            logger.info(f"Job: collect_grey_market done, {len(quotes)} quotes")
        except Exception as e:
            logger.error(f"Job: collect_grey_market failed: {e}")

    def job_send_daily_digest(self) -> None:
        """每日汇总推送。"""
        logger.info("Job: send_daily_digest started")
        try:
            from app.utils.time_utils import today_hk
            from app.utils.dedup import make_notification_key

            event_key = str(today_hk())
            notif_key = make_notification_key("digest", "daily_digest", event_key)
            if self.repo.has_notification_been_sent(notif_key):
                logger.info(f"Daily digest already sent, skipping: {notif_key}")
                return

            events = self.repo.get_today_events()
            summary = self.llm_service.summarize_daily_digest(events)
            self.repo.save_llm_summary(None, notif_key, summary)

            from app.notifier.formatter import format_daily_digest
            title, body = format_daily_digest(summary, events)

            self._send_notification(
                title=title,
                body=body,
                level=2,
                notification_key=notif_key,
                stock_code=None,
                notification_type="daily_digest",
            )

            logger.info("Job: send_daily_digest done")
        except Exception as e:
            logger.error(f"Job: send_daily_digest failed: {e}")

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

    def start(self) -> None:
        """启动调度器。"""
        self.setup_jobs()
        logger.info("Scheduler started")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped")
