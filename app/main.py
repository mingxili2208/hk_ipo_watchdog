"""HK IPO Watchdog — 主入口。"""

import argparse
import sys

from loguru import logger


def main():
    parser = argparse.ArgumentParser(
        prog="python3 -m app.main",
        description="HK IPO Watchdog - 港股打新监控系统",
    )
    subparsers = parser.add_subparsers(dest="command")

    # init-db
    initdb_parser = subparsers.add_parser("init-db", help="初始化数据库")
    initdb_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    initdb_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # run
    run_parser = subparsers.add_parser("run", help="启动常驻服务")
    run_parser.add_argument("--dry-run", action="store_true", help="只运行不推送")

    # collect
    collect_parser = subparsers.add_parser("collect", help="手动采集数据")
    collect_parser.add_argument(
        "source",
        choices=["ipo-calendar", "announcements", "grey-market"],
        help="数据源",
    )
    collect_parser.add_argument("--once", action="store_true", help="只运行一次")
    collect_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    collect_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # strategy
    strategy_parser = subparsers.add_parser("strategy", help="策略操作")
    strategy_parser.add_argument(
        "action",
        choices=["scan"],
        help="策略动作",
    )
    strategy_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    strategy_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # digest
    digest_parser = subparsers.add_parser("digest", help="日报操作")
    digest_parser.add_argument(
        "type",
        choices=["daily"],
        help="日报类型",
    )
    digest_parser.add_argument(
        "--resend",
        action="store_true",
        help="补发当日日报，保留原发送记录并以补发记录单独追踪",
    )
    digest_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    digest_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # test-notification
    test_parser = subparsers.add_parser("test-notification", help="测试推送")
    test_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    test_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # test-llm
    llm_test_parser = subparsers.add_parser("test-llm", help="测试 LLM 摘要，不发送推送")
    llm_test_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    llm_test_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # test-e2e
    e2e_test_parser = subparsers.add_parser(
        "test-e2e",
        help="拉取真实 IPO，经 LLM 生成摘要并发送测试邮件",
    )
    e2e_test_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    e2e_test_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # usage
    usage_parser = subparsers.add_parser("usage", help="查看运行用量")
    usage_parser.add_argument("resource", choices=["llm"], help="用量类型")
    usage_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    usage_parser.add_argument("--log-level", default="INFO", help="日志级别")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # 加载配置
    from app.settings import load_settings
    from app.utils.logger import setup_logger

    log_level = getattr(args, "log_level", "INFO") or "INFO"
    config_dir = getattr(args, "config_dir", "config") or "config"

    setup_logger(log_level)

    settings = load_settings(config_dir=config_dir, log_level=log_level)

    if args.command == "init-db":
        _cmd_init_db(settings)
    elif args.command == "run":
        _cmd_run(settings, dry_run=args.dry_run)
    elif args.command == "collect":
        _cmd_collect(settings, source=args.source, once=args.once)
    elif args.command == "strategy":
        _cmd_strategy(settings, action=args.action)
    elif args.command == "digest":
        _cmd_digest(settings, dtype=args.type, resend=args.resend)
    elif args.command == "test-notification":
        _cmd_test_notification(settings)
    elif args.command == "test-llm":
        _cmd_test_llm(settings)
    elif args.command == "test-e2e":
        _cmd_test_e2e(settings)
    elif args.command == "usage":
        _cmd_usage(settings, resource=args.resource)


def _cmd_init_db(settings) -> None:
    """初始化数据库。"""
    from app.storage.db import init_db

    init_db(settings.database_url)
    logger.info("Database initialized successfully")


def _cmd_run(settings, dry_run: bool = False) -> None:
    """启动常驻服务。"""
    from app.storage.db import init_db
    from app.storage.repository import Repository
    from app.strategy.config_loader import load_strategy_config
    from app.llm.client import create_llm_provider, LLMService
    from app.scheduler import SchedulerApp

    init_db(settings.database_url)
    repo = Repository()
    strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")
    provider = create_llm_provider(settings.llm)
    llm_service = LLMService(provider, usage_recorder=repo.record_llm_usage)

    app = SchedulerApp(
        settings=settings,
        strategy_config=strategy_config,
        llm_service=llm_service,
        repository=repo,
        dry_run=dry_run,
    )

    if dry_run:
        logger.info("Running in dry-run mode")
        app.job_collect_ipo_calendar()
        logger.info("Dry run completed")
    else:
        app.start()


def _cmd_collect(settings, source: str, once: bool = False) -> None:
    """手动采集数据。"""
    from app.storage.db import init_db
    from app.storage.repository import Repository

    init_db(settings.database_url)
    repo = Repository()

    if source == "ipo-calendar":
        from app.strategy.config_loader import load_strategy_config
        from app.llm.client import create_llm_provider, LLMService
        from app.scheduler import SchedulerApp

        strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")
        provider = create_llm_provider(settings.llm)
        llm_service = LLMService(provider, usage_recorder=repo.record_llm_usage)

        app = SchedulerApp(
            settings=settings,
            strategy_config=strategy_config,
            llm_service=llm_service,
            repository=repo,
        )
        app.job_collect_ipo_calendar()

    elif source == "announcements":
        from app.strategy.config_loader import load_strategy_config
        from app.llm.client import create_llm_provider, LLMService
        from app.scheduler import SchedulerApp

        strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")
        provider = create_llm_provider(settings.llm)
        llm_service = LLMService(provider, usage_recorder=repo.record_llm_usage)

        app = SchedulerApp(
            settings=settings,
            strategy_config=strategy_config,
            llm_service=llm_service,
            repository=repo,
        )
        app.job_collect_announcements()

    elif source == "grey-market":
        from app.strategy.config_loader import load_strategy_config
        from app.llm.client import create_llm_provider, LLMService
        from app.scheduler import SchedulerApp

        strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")
        provider = create_llm_provider(settings.llm)
        llm_service = LLMService(provider, usage_recorder=repo.record_llm_usage)

        app = SchedulerApp(
            settings=settings,
            strategy_config=strategy_config,
            llm_service=llm_service,
            repository=repo,
        )
        app.job_collect_grey_market(ignore_window=True)

    logger.info(f"Collect {source} completed")


def _cmd_strategy(settings, action: str) -> None:
    """策略操作。"""
    from app.storage.db import init_db
    from app.storage.repository import Repository
    from app.strategy.config_loader import load_strategy_config
    from app.strategy.rule_engine import evaluate_ipo

    init_db(settings.database_url)
    repo = Repository()
    strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")

    if action == "scan":
        ipos = repo.get_active_ipos()
        logger.info(f"Scanning {len(ipos)} IPOs...")

        for ipo in ipos:
            allotment = repo.get_latest_allotment(ipo.stock_code)
            grey = repo.get_latest_grey_quote(ipo.stock_code)
            decision = evaluate_ipo(ipo, strategy_config, allotment, grey)
            repo.save_strategy_score(decision)

            logger.info(
                f"{ipo.stock_code} {ipo.stock_name}: score={decision.score}, level={decision.level}, passed={decision.passed}"
            )

        logger.info("Strategy scan completed")


def _cmd_digest(settings, dtype: str, resend: bool = False) -> None:
    """日报操作。"""
    from app.storage.db import init_db
    from app.storage.repository import Repository
    from app.llm.client import create_llm_provider, LLMService
    from app.strategy.config_loader import load_strategy_config
    from app.scheduler import SchedulerApp

    init_db(settings.database_url)
    repo = Repository()
    strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")
    provider = create_llm_provider(settings.llm)
    llm_service = LLMService(provider, usage_recorder=repo.record_llm_usage)

    app = SchedulerApp(
        settings=settings,
        strategy_config=strategy_config,
        llm_service=llm_service,
        repository=repo,
    )
    app.job_send_daily_digest(resend=resend)


def _cmd_test_notification(settings) -> None:
    """测试推送。"""
    import os
    from app.storage.db import init_db
    from app.storage.repository import Repository

    init_db(settings.database_url)
    repo = Repository()

    results = []

    notif = settings.notification
    if notif.telegram.enabled:
        token = os.environ.get(notif.telegram.bot_token_env, "")
        chat_id = os.environ.get(notif.telegram.chat_id_env, "")
        if token and chat_id:
            from app.notifier.telegram import TelegramNotifier
            t = TelegramNotifier(token, chat_id)
            r = t.send(
                title="港股打新监控 - 测试推送",
                body="如果你看到这条消息，说明 Telegram 推送配置正确。",
            )
            results.append(r)
            logger.info(f"Telegram: {'OK' if r.success else 'FAILED'} {r.error_message or ''}")
        else:
            logger.warning("Telegram enabled but token/chat_id not configured")

    if notif.email.enabled:
        username = os.environ.get(notif.email.username_env, "")
        password = os.environ.get(notif.email.password_env, "")
        receivers = settings.recipients.email
        if username and password and receivers:
            from app.notifier.email import EmailNotifier
            from app.notifier.formatter import append_daily_llm_usage
            e = EmailNotifier(
                notif.email.smtp_host,
                notif.email.smtp_port,
                username,
                password,
                receivers,
                notif.email.encryption,
            )
            r = e.send(
                title="港股打新监控 - 测试推送",
                body=append_daily_llm_usage(
                    "如果你看到这封邮件，说明 Email 推送和收件人列表配置正确。",
                    repo.get_llm_usage_for_hk_day(),
                ),
            )
            results.append(r)
            logger.info(f"Email: {'OK' if r.success else 'FAILED'} {r.error_message or ''}")
        else:
            logger.warning("Email enabled but SMTP credentials or recipients are not configured")

    if notif.bark.enabled:
        key = os.environ.get(notif.bark.device_key_env, "")
        if key:
            from app.notifier.bark import BarkNotifier
            b = BarkNotifier(key)
            r = b.send(
                title="港股打新监控 - 测试推送",
                body="如果你看到这条消息，说明 Bark 推送配置正确。",
            )
            results.append(r)
            logger.info(f"Bark: {'OK' if r.success else 'FAILED'} {r.error_message or ''}")

    if notif.server_chan.enabled:
        key = os.environ.get(notif.server_chan.send_key_env, "")
        if key:
            from app.notifier.server_chan import ServerChanNotifier
            s = ServerChanNotifier(key)
            r = s.send(
                title="港股打新监控 - 测试推送",
                body="如果你看到这条消息，说明 Server 酱推送配置正确。",
            )
            results.append(r)
            logger.info(f"Server Chan: {'OK' if r.success else 'FAILED'} {r.error_message or ''}")

    if not results:
        logger.warning("No notification channels enabled or configured")

    success_count = sum(1 for r in results if r.success)
    logger.info(f"Test notification: {success_count}/{len(results)} channels succeeded")


def _cmd_test_llm(settings) -> None:
    """使用虚拟事件测试 LLM 响应，不触发通知。"""
    from app.llm.client import create_llm_provider
    from app.llm.prompts import build_summary_prompt
    from app.llm.schemas import validate_summary_json
    from app.storage.db import init_db
    from app.storage.repository import Repository

    payload = {
        "ipo": {
            "stock_code": "TEST",
            "stock_name": "LLM Connectivity Test",
            "status": "subscription_open",
            "entry_fee_hkd": 5000,
        },
        "strategy_decision": {
            "score": 70,
            "level": 2,
            "trigger_reasons": ["LLM API connectivity test"],
            "risk_flags": ["This is synthetic test data"],
        },
    }

    init_db(settings.database_url)
    repo = Repository()
    provider = None
    try:
        provider = create_llm_provider(settings.llm)
        if settings.llm.provider == "mock":
            logger.warning("Testing mock LLM provider; no external API request will be made")
        response = provider.generate(build_summary_prompt(payload))
    except Exception as e:
        logger.error(f"LLM test failed: {e}")
        raise SystemExit(1)
    finally:
        if provider is not None:
            consume_usage = getattr(provider, "consume_usage", None)
            usage = consume_usage() if consume_usage else None
            if usage:
                repo.record_llm_usage("test_llm", usage)

    if not validate_summary_json(response):
        logger.error("LLM test failed: response does not match the required summary JSON schema")
        raise SystemExit(1)

    logger.info(
        f"LLM test succeeded: provider={settings.llm.provider}, model={settings.llm.model}"
    )


def _cmd_test_e2e(settings) -> None:
    """拉取真实 IPO，经真实 LLM 生成摘要并以测试邮件发送。"""
    import os

    from app.llm.client import create_llm_provider, LLMService
    from app.notifier.email import EmailNotifier
    from app.notifier.formatter import append_daily_llm_usage, format_notification
    from app.scheduler import SchedulerApp
    from app.storage.db import Base, init_db
    from app.storage.repository import Repository
    from app.strategy.config_loader import load_strategy_config
    from app.strategy.rule_engine import evaluate_ipo
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    email = settings.notification.email
    username = os.environ.get(email.username_env, "")
    password = os.environ.get(email.password_env, "")
    receivers = settings.recipients.email
    if not email.enabled or not username or not password or not receivers:
        logger.error("E2E test requires enabled Email, SMTP credentials, and recipients")
        raise SystemExit(1)

    # Persist paid API usage, while isolating collected IPO and notification test state.
    init_db(settings.database_url)
    usage_repo = Repository()
    temp_engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(temp_engine)
    repo = Repository(Session(bind=temp_engine))
    strategy_config = load_strategy_config(f"{settings.config_dir}/strategy.yaml")

    try:
        provider = create_llm_provider(settings.llm)
        llm_service = LLMService(provider, usage_recorder=usage_repo.record_llm_usage)
        app = SchedulerApp(settings, strategy_config, llm_service, repo, dry_run=True)
        collected = app._collect_all_ipo_sources()
    except Exception as e:
        logger.error(f"E2E test collection setup failed: {e}")
        raise SystemExit(1)

    if not collected:
        logger.error("E2E test failed: no IPO data collected from real configured sources")
        raise SystemExit(1)

    for item in collected:
        repo.upsert_ipo(item)

    merged_items = repo.get_active_ipos()
    if not merged_items:
        logger.error("E2E test failed: collected IPO data could not be normalized and merged")
        raise SystemExit(1)

    ipo = max(
        merged_items,
        key=lambda item: (
            item.status == "subscription_open",
            item.entry_fee_hkd is not None,
            item.subscription_close_date is not None,
            item.listing_date is not None,
        ),
    )
    decision = evaluate_ipo(ipo, strategy_config)
    logger.info(
        f"E2E real IPO selected: {ipo.stock_code} {ipo.stock_name or ''}; "
        f"score={decision.score}, would_notify={decision.should_notify}"
    )

    summary = llm_service.summarize_ipo_alert(ipo, decision, purpose="test_e2e")
    if summary.summary_source != "llm":
        logger.error("E2E test failed: LLM request fell back to rule summary; email was not sent")
        raise SystemExit(1)

    title, body = format_notification(summary, decision, ipo)
    title = f"[端到端测试] {title}"
    body = (
        "这是测试邮件：数据来自实时采集，摘要由当前 LLM 生成；"
        "本次发送不构成正式提醒，也不会写入正式通知记录。\n"
        f"按当前策略正式推送: {'是' if decision.should_notify else '否'}\n\n"
        f"{body}"
    )

    result = EmailNotifier(
        email.smtp_host,
        email.smtp_port,
        username,
        password,
        receivers,
        email.encryption,
    ).send(title=title, body=append_daily_llm_usage(body, usage_repo.get_llm_usage_for_hk_day()))
    if not result.success:
        logger.error(f"E2E test failed while sending Email: {result.error_message or ''}")
        raise SystemExit(1)

    logger.info(
        f"E2E test succeeded: collected={len(collected)}, merged={len(merged_items)}, "
        f"stock={ipo.stock_code}, provider={settings.llm.model}, email_recipients={len(receivers)}"
    )


def _cmd_usage(settings, resource: str) -> None:
    """显示本地持久化的运行用量汇总。"""
    from app.storage.db import init_db
    from app.storage.repository import Repository

    init_db(settings.database_url)
    if resource != "llm":
        raise ValueError(f"Unsupported usage resource: {resource}")

    summaries = Repository().get_llm_usage_summary()
    if not summaries:
        logger.info("No LLM token usage recorded")
        return

    total_calls = sum(item["calls"] for item in summaries)
    total_prompt = sum(item["prompt_tokens"] for item in summaries)
    total_completion = sum(item["completion_tokens"] for item in summaries)
    total_cached = sum(item["cached_tokens"] for item in summaries)
    total_tokens = sum(item["total_tokens"] for item in summaries)
    logger.info(
        "LLM usage total: "
        f"calls={total_calls}, prompt_tokens={total_prompt}, "
        f"completion_tokens={total_completion}, cached_tokens={total_cached}, "
        f"total_tokens={total_tokens}"
    )
    for item in summaries:
        logger.info(
            "LLM usage detail: "
            f"provider={item['provider']}, model={item['model']}, purpose={item['purpose']}, "
            f"calls={item['calls']}, prompt_tokens={item['prompt_tokens']}, "
            f"completion_tokens={item['completion_tokens']}, "
            f"cached_tokens={item['cached_tokens']}, total_tokens={item['total_tokens']}"
        )


if __name__ == "__main__":
    main()
