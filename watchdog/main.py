#!/usr/bin/env python3
"""Watchdog Agent — main entry point.

Runs the AI agent on a configurable interval loop.
Can also be invoked once with --once for testing.
"""

import argparse
import logging
import sys
import time

from watchdog import config
from watchdog.agent import run_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("watchdog")


def main():
    parser = argparse.ArgumentParser(description="Matometa Watchdog AI Agent")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--interval", type=int, default=config.INTERVAL_AGENT_CYCLE,
                        help=f"Seconds between cycles (default: {config.INTERVAL_AGENT_CYCLE})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would be done without executing write operations")
    args = parser.parse_args()

    logger.info("Watchdog agent starting (model=%s, interval=%ds)",
                config.OLLAMA_MODEL, args.interval)

    if not config.OLLAMA_API_KEY:
        logger.error("OLLAMA_API_KEY not set. Cannot start.")
        sys.exit(1)

    if args.once:
        summary = run_cycle()
        print(f"\nCycle complete: {summary['tool_calls']} tool calls in {summary['duration_s']}s")
        if summary["final_message"]:
            print(f"\nAgent: {summary['final_message']}")
        return

    # Continuous loop
    consecutive_errors = 0
    while True:
        try:
            run_cycle()
            consecutive_errors = 0
        except KeyboardInterrupt:
            logger.info("Shutting down (keyboard interrupt)")
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error("Cycle failed: %s (consecutive: %d)", e, consecutive_errors)

            # Back off if too many consecutive errors
            if consecutive_errors >= 5:
                backoff = min(args.interval * 4, 3600)
                logger.warning("Too many errors, backing off for %ds", backoff)
                time.sleep(backoff)
                consecutive_errors = 0
                continue

        logger.info("Next cycle in %ds", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
