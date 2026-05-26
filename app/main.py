"""HK IPO Watchdog — 主入口。"""

import argparse
import sys

from loguru import logger


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
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
    digest_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    digest_parser.add_argument("--log-level", default="INFO", help="日志级别")

    # test-notification
    test_parser = subparsers.add_parser("test-notification", help="测试推送")
    test_parser.add_argument("--config-dir", default="config", help="配置目录路径")
    test_parser.add_argument("--log-level", default="INFO", help="日志级别")

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
        _cmd_digest(settings, dtype=args.type)
    elif args.command == "test-notification":
        _cmd_test_notification(settings)


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
    llm_service = LLMService(provider)

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
        llm_service = LLMService(provider)

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
        llm_service = LLMService(provider)

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
        llm_service = LLMService(provider)

        app = SchedulerApp(
            settings=settings,
            strategy_config=strategy_config,
            llm_service=llm_service,
            repository=repo,
        )
        app.job_collect_grey_market()

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


def _cmd_digest(settings, dtype: str) -> None:
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
    llm_service = LLMService(provider)

    app = SchedulerApp(
        settings=settings,
        strategy_config=strategy_config,
        llm_service=llm_service,
        repository=repo,
    )
    app.job_send_daily_digest()


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
                body="如果你看到这封邮件，说明 Email 推送和收件人列表配置正确。",
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


if __name__ == "__main__":
    main()
