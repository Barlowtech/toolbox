"""
System Info — display machine information.

No params needed. Just hit Run.
"""

import os
import platform
import shutil
import sys


def run(params: dict, context: dict) -> dict:
    # Disk usage for home directory
    total, used, free = shutil.disk_usage(os.path.expanduser("~"))

    def fmt_bytes(b):
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"

    info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "N/A",
        "os": f"{platform.system()} {platform.release()}",
        "hostname": platform.node(),
        "cpu_count": os.cpu_count(),
        "disk_total": fmt_bytes(total),
        "disk_used": fmt_bytes(used),
        "disk_free": fmt_bytes(free),
        "cwd": os.getcwd(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
    }

    log_lines = [
        f"  Python:     {info['python_version'].split()[0]}",
        f"  Platform:   {info['platform']}",
        f"  Machine:    {info['machine']}",
        f"  Processor:  {info['processor']}",
        f"  OS:         {info['os']}",
        f"  Host:       {info['hostname']}",
        f"  CPUs:       {info['cpu_count']}",
        f"  Disk:       {info['disk_used']} used / {info['disk_total']} total ({info['disk_free']} free)",
        f"  User:       {info['user']}",
    ]

    return {
        "message": f"System info for {info['hostname']}",
        "log": log_lines,
        "data": info,
    }
