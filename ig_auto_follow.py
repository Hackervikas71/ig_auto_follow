#!/usr/bin/env python3
"""
INSTAGRAM AUTO-FOLLOW BOT — No-Limit Mode
Author: HackerAI
Requirements: pip install instagrapi
"""

import os
import sys
import json
import time
import random
import logging
from datetime import datetime, timedelta
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError, LoginRequired, PleaseWaitFewMinutes,
    RecaptchaChallenge, ChallengeRequired, FeedbackRequired
)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

CONFIG = {
    # Credentials
    "username": os.getenv("IG_USERNAME", ""),
    "password": os.getenv("IG_PASSWORD", ""),

    # Strategy: "follow_followers" = follow followers of a target account
    #            "follow_tag"       = follow users who posted under a hashtag
    #            "follow_location"  = follow users who posted at a location
    "strategy": "follow_followers",

    # Target(s)
    "target_username": "example_account",       # for follow_followers
    "target_tag": "programming",                 # for follow_tag
    "target_location_id": None,                  # for follow_location

    # Limits — set high for "no limit" behavior
    "max_follow_per_session": 5000,              # upper bound per run
    "daily_limit": 1000,                         # Instagram soft limit; push it
    "min_delay_seconds": 25,                     # lower bound between actions
    "max_delay_seconds": 75,                     # upper bound (human-like)

    # Session persistence (avoids re-login every run)
    "session_file": "instagram_session.json",

    # Logging
    "log_file": "ig_bot.log",
    "log_level": "INFO",
}

# ─── SETUP LOGGING ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, CONFIG["log_level"].upper()),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(CONFIG["log_file"]),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── STATISTICS TRACKER ───────────────────────────────────────────────────────

class Stats:
    def __init__(self):
        self.followed = 0
        self.skipped = 0
        self.errors = 0
        self.start_time = datetime.now()

    def elapsed(self):
        return datetime.now() - self.start_time

    def summary(self):
        return (
            f"\n{'='*50}\n"
            f"SESSION COMPLETE\n"
            f"  Followed : {self.followed}\n"
            f"  Skipped  : {self.skipped}\n"
            f"  Errors   : {self.errors}\n"
            f"  Duration : {self.elapsed()}\n"
            f"{'='*50}"
        )

stats = Stats()

# ─── CLIENT SETUP ─────────────────────────────────────────────────────────────

def login():
    """Login with session persistence to avoid repeated 2FA/challenge."""
    cl = Client()
    cl.delay_range = [1, 3]  # small delay on all API requests

    if os.path.exists(CONFIG["session_file"]):
        try:
            cl.load_settings(CONFIG["session_file"])
            cl.login(CONFIG["username"], CONFIG["password"])
            log.info("Logged in using saved session.")
            return cl
        except Exception as e:
            log.warning(f"Session load failed: {e}. Re-logging...")

    try:
        cl.login(CONFIG["username"], CONFIG["password"])
        cl.dump_settings(CONFIG["session_file"])
        log.info("Logged in and session saved.")
    except ChallengeRequired:
        log.error("Challenge/2FA required. Solve manually, then re-run.")
        sys.exit(1)
    except RecaptchaChallenge:
        log.error("reCAPTCHA triggered. Instagram flagged the login.")
        sys.exit(1)

    return cl

# ─── CORE FOLLOW LOGIC ────────────────────────────────────────────────────────

def human_delay():
    """Sleep for a random interval to mimic human behavior."""
    delay = random.randint(CONFIG["min_delay_seconds"], CONFIG["max_delay_seconds"])
    log.debug(f"Sleeping {delay}s...")
    time.sleep(delay)

def safe_follow(cl, user_id, username):
    """Attempt to follow a user with error handling."""
    global stats
    try:
        # Check if already following
        try:
            relationship = cl.user_info(user_id)
            # instagrapi doesn't have a direct is_followed check this way,
            # so we attempt follow and catch if already following
        except:
            pass

        cl.user_follow(user_id)
        stats.followed += 1
        log.info(f"[{stats.followed}] Followed @{username} (ID: {user_id})")

        if stats.followed >= CONFIG["max_follow_per_session"]:
            log.info("Reached max_follow_per_session limit.")
            return False  # signal to stop

        human_delay()
        return True

    except ClientError as e:
        error_str = str(e).lower()

        if "already" in error_str and ("follow" in error_str or "following" in error_str):
            stats.skipped += 1
            log.info(f"Already following @{username}, skipping.")
            return True

        if "feedback_required" in error_str or FeedbackRequired:
            log.error(f"FEEDBACK REQUIRED — Instagram flagged the action. Stopping.")
            return False

        if "please wait" in error_str or PleaseWaitFewMinutes:
            log.warning("Rate limited. Waiting 10 minutes...")
            time.sleep(600)
            return True

        stats.errors += 1
        log.error(f"Failed to follow @{username}: {e}")
        human_delay()
        return True

    except Exception as e:
        stats.errors += 1
        log.error(f"Unexpected error on @{username}: {e}")
        human_delay()
        return True

# ─── STRATEGY: FOLLOW FOLLOWERS OF A TARGET ──────────────────────────────────

def follow_followers_strategy(cl):
    """Follow users who follow a specific target account."""
    log.info(f"Fetching followers of @{CONFIG['target_username']}...")

    try:
        target_id = cl.user_id_from_username(CONFIG["target_username"])
    except Exception as e:
        log.error(f"Could not resolve target username: {e}")
        return

    followers = cl.user_followers(target_id, amount=CONFIG["max_follow_per_session"])

    log.info(f"Found {len(followers)} followers. Starting follow cycle...")

    for user_id, user_info in followers.items():
        if stats.followed >= CONFIG["max_follow_per_session"]:
            break
        if not safe_follow(cl, user_id, user_info.username):
            break

# ─── STRATEGY: FOLLOW HASHTAG POSTERS ────────────────────────────────────────

def follow_tag_strategy(cl):
    """Follow users who recently posted under a hashtag."""
    log.info(f"Fetching recent posts for tag #{CONFIG['target_tag']}...")

    try:
        medias = cl.hashtag_medias_recent(CONFIG["target_tag"], amount=100)
    except Exception as e:
        log.error(f"Could not fetch hashtag medias: {e}")
        return

    followed_this_batch = 0
    for media in medias:
        if stats.followed >= CONFIG["max_follow_per_session"]:
            break
        user_id = media.user.pk
        username = media.user.username
        if not safe_follow(cl, user_id, username):
            break
        followed_this_batch += 1

    # Loop to get more users if we exhausted the first 100
    while stats.followed < CONFIG["max_follow_per_session"]:
        try:
            medias = cl.hashtag_medias_recent(CONFIG["target_tag"], amount=100)
            new_follows = 0
            for media in medias:
                if stats.followed >= CONFIG["max_follow_per_session"]:
                    break
                user_id = media.user.pk
                username = media.user.username
                if not safe_follow(cl, user_id, username):
                    return
                new_follows += 1
            if new_follows == 0:
                log.info("No new users found. Exiting.")
                break
        except Exception as e:
            log.error(f"Error in tag loop: {e}")
            break

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    global stats

    log.info("=" * 50)
    log.info("INSTAGRAM AUTO-FOLLOW BOT — STARTING")
    log.info(f"Strategy: {CONFIG['strategy']}")
    log.info(f"Max per session: {CONFIG['max_follow_per_session']}")
    log.info(f"Delay range: {CONFIG['min_delay_seconds']}-{CONFIG['max_delay_seconds']}s")
    log.info("=" * 50)

    if not CONFIG["username"] or not CONFIG["password"]:
        log.error("Username/password not set. Use env vars IG_USERNAME and IG_PASSWORD.")
        sys.exit(1)

    cl = login()

    # Route to chosen strategy
    strategy_map = {
        "follow_followers": follow_followers_strategy,
        "follow_tag": follow_tag_strategy,
    }

    strategy_func = strategy_map.get(CONFIG["strategy"])
    if not strategy_func:
        log.error(f"Unknown strategy: {CONFIG['strategy']}")
        sys.exit(1)

    try:
        strategy_func(cl)
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    except Exception as e:
        log.error(f"Fatal error: {e}")

    # Save session for next run
    try:
        cl.dump_settings(CONFIG["session_file"])
    except:
        pass

    log.info(stats.summary())

if __name__ == "__main__":
    main()