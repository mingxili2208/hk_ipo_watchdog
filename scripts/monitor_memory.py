#!/usr/bin/env python3
"""进程内存监控工具。

用法：
    # 监控本机进程（按名称匹配）
    python3 scripts/monitor_memory.py --process chromium --interval 30

    # 监控 Docker 容器
    python3 scripts/monitor_memory.py --container hk-ipo-watchdog --interval 30

    # 同时监控容器 + Chromium 子进程
    python3 scripts/monitor_memory.py --container hk-ipo-watchdog --process chromium --interval 15

    # 输出到文件
    python3 scripts/monitor_memory.py --container hk-ipo-watchdog --interval 30 --log-file logs/memory.csv

输出 CSV 格式：timestamp, container_mem_mb, container_cpu_pct, chromium_pids, chromium_mem_mb, python_mem_mb
"""

import argparse
import csv
import re
import subprocess
import sys
import time
from datetime import datetime


def get_docker_stats(container: str) -> dict | None:
    """获取 Docker 容器的内存和 CPU 使用情况。"""
    try:
        result = subprocess.run(
            [
                "docker", "stats", container,
                "--no-stream",
                "--format", "{{.MemUsage}},{{.CPUPerc}},{{.MemPerc}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        # 格式: "123.4MiB / 15.63GiB, 0.12%, 0.78%"
        parts = result.stdout.strip().split(",")
        if len(parts) < 3:
            return None

        mem_usage = parts[0].strip()  # "123.4MiB / 15.63GiB"
        cpu_pct = parts[1].strip().rstrip("%")  # "0.12"
        mem_pct = parts[2].strip().rstrip("%")  # "0.78"

        # 提取实际使用量（/ 前面的部分）
        used_part = mem_usage.split("/")[0].strip()
        mem_mb = _parse_size_to_mb(used_part)

        return {
            "mem_mb": round(mem_mb, 1),
            "cpu_pct": float(cpu_pct),
            "mem_pct": float(mem_pct),
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return None


def get_process_memory(process_name: str) -> list[dict]:
    """按进程名匹配，返回匹配进程的 PID 和 RSS 内存。"""
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        matches = []
        for line in result.stdout.splitlines():
            if process_name.lower() in line.lower() and "grep" not in line.lower():
                parts = line.split()
                if len(parts) >= 6:
                    pid = parts[1]
                    rss_kb = parts[5]  # RSS in KB
                    try:
                        rss_mb = int(rss_kb) / 1024
                        matches.append({"pid": pid, "rss_mb": round(rss_mb, 1)})
                    except ValueError:
                        continue
        return matches
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _parse_size_to_mb(text: str) -> float:
    """将 Docker 的内存格式（如 '123.4MiB'、'1.2GiB'）转为 MB。"""
    text = text.strip()
    match = re.match(r"([\d.]+)\s*([a-zA-Z]+)", text)
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2).upper()
    if unit in ("B",):
        return value / (1024 * 1024)
    elif unit in ("KIB", "KB"):
        return value / 1024
    elif unit in ("MIB", "MB"):
        return value
    elif unit in ("GIB", "GB"):
        return value * 1024
    elif unit in ("TIB", "TB"):
        return value * 1024 * 1024
    return value


def collect_snapshot(container: str | None, process_name: str | None) -> dict:
    """采集一次内存快照。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot = {"timestamp": ts}

    if container:
        stats = get_docker_stats(container)
        if stats:
            snapshot["container_mem_mb"] = stats["mem_mb"]
            snapshot["container_cpu_pct"] = stats["cpu_pct"]
            snapshot["container_mem_pct"] = stats["mem_pct"]
        else:
            snapshot["container_mem_mb"] = None
            snapshot["container_cpu_pct"] = None
            snapshot["container_mem_pct"] = None

    if process_name:
        procs = get_process_memory(process_name)
        snapshot["process_count"] = len(procs)
        snapshot["process_total_mem_mb"] = round(
            sum(p["rss_mb"] for p in procs), 1
        )
        if procs:
            snapshot["process_pids"] = ";".join(p["pid"] for p in procs)
        else:
            snapshot["process_pids"] = ""

    return snapshot


def print_snapshot(snapshot: dict, prev: dict | None) -> None:
    """打印一行人类可读的摘要。"""
    ts = snapshot["timestamp"]
    parts = [f"[{ts}]"]

    if "container_mem_mb" in snapshot:
        mem = snapshot["container_mem_mb"]
        cpu = snapshot["container_cpu_pct"]
        if mem is not None:
            delta = ""
            if prev and prev.get("container_mem_mb") is not None:
                diff = mem - prev["container_mem_mb"]
                if abs(diff) >= 0.5:
                    delta = f" (Δ{diff:+.1f}MB)"
            parts.append(f"容器: {mem:.1f}MB {cpu}% CPU{delta}")
        else:
            parts.append("容器: 无法获取")

    if "process_count" in snapshot:
        count = snapshot["process_count"]
        total = snapshot["process_total_mem_mb"]
        pids = snapshot.get("process_pids", "")
        if count > 0:
            delta = ""
            if prev and prev.get("process_total_mem_mb") is not None:
                diff = total - prev["process_total_mem_mb"]
                if abs(diff) >= 0.5:
                    delta = f" (Δ{diff:+.1f}MB)"
            parts.append(f"进程: {count}个, {total:.1f}MB{delta}")
        else:
            parts.append("进程: 未找到")

    print(" | ".join(parts), flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="进程/容器内存监控工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--container", "-c",
        help="Docker 容器名称或 ID",
    )
    parser.add_argument(
        "--process", "-p",
        help="要监控的进程名（模糊匹配，如 chromium、python）",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=30,
        help="采集间隔（秒），默认 30",
    )
    parser.add_argument(
        "--log-file", "-o",
        help="输出 CSV 文件路径（不指定则只打印到终端）",
    )
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=0,
        help="监控持续时间（秒），0 表示一直运行",
    )
    parser.add_argument(
        "--alert-mb",
        type=int,
        default=500,
        help="容器内存超过此值（MB）时报警，默认 500",
    )
    args = parser.parse_args()

    if not args.container and not args.process:
        parser.error("至少指定 --container 或 --process 之一")

    csv_writer = None
    csv_file = None
    if args.log_file:
        csv_file = open(args.log_file, "a", newline="")
        csv_writer = csv.writer(csv_file)
        # 写表头（如果文件为空）
        if csv_file.tell() == 0:
            headers = ["timestamp"]
            if args.container:
                headers += ["container_mem_mb", "container_cpu_pct", "container_mem_pct"]
            if args.process:
                headers += ["process_count", "process_total_mem_mb", "process_pids"]
            csv_writer.writerow(headers)

    print(f"内存监控启动 — 间隔 {args.interval}s，Ctrl+C 退出")
    if args.container:
        print(f"  容器: {args.container}")
    if args.process:
        print(f"  进程: {args.process}")
    if args.log_file:
        print(f"  日志: {args.log_file}")
    print("-" * 60)

    prev = None
    start = time.time()
    alerts = 0

    try:
        while True:
            if args.duration > 0 and (time.time() - start) >= args.duration:
                break

            snapshot = collect_snapshot(args.container, args.process)
            print_snapshot(snapshot, prev)

            if csv_writer:
                row = [snapshot["timestamp"]]
                if args.container:
                    row += [
                        snapshot.get("container_mem_mb"),
                        snapshot.get("container_cpu_pct"),
                        snapshot.get("container_mem_pct"),
                    ]
                if args.process:
                    row += [
                        snapshot.get("process_count"),
                        snapshot.get("process_total_mem_mb"),
                        snapshot.get("process_pids", ""),
                    ]
                csv_writer.writerow(row)
                csv_file.flush()

            # 内存报警
            mem = snapshot.get("container_mem_mb") or snapshot.get("process_total_mem_mb") or 0
            if mem > args.alert_mb:
                alerts += 1
                print(f"  ⚠️  内存报警: {mem:.1f}MB > {args.alert_mb}MB 阈值 (累计 {alerts} 次)")

            prev = snapshot
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n监控已停止")
    finally:
        if csv_file:
            csv_file.close()


if __name__ == "__main__":
    main()
