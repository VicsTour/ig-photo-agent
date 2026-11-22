#!/usr/bin/env python3
"""Publisher — runs inside GitHub Actions, never inside Claude.

  python scripts/publish.py                 publish the oldest queued post whose time has come
  python scripts/publish.py --stats         refresh likes/comments for recent posts in log/posts.csv
  python scripts/publish.py --refresh-token FILE   write a refreshed 60-day token to FILE
  python scripts/publish.py --dry-run       show what would be published, call nothing
  python scripts/publish.py --check         confirm the token works and show the account

Needs env IG_ACCESS_TOKEN (GitHub secret). Uses only the Python standard library.
"""
import csv
import datetime as dt
import glob
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://graph.instagram.com"
VERSION = os.environ.get("IG_API_VERSION", "").strip("/")
BASE = f"{API}/{VERSION}" if VERSION else API
LOG = "log/posts.csv"
LOG_FIELDS = ["slug", "publish_at", "posted_at", "weekday", "hour_local", "media_id", "permalink",
              "like_count", "comments_count", "caption_first_line"]
MAX_ATTEMPTS = 3
LOCAL_TZ = dt.timezone(dt.timedelta(hours=7))  # WIB


def call(method, path, params, base=BASE):
    params = dict(params)
    params["access_token"] = os.environ["IG_ACCESS_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    url = f"{base}/{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {body}") from None


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def due_posts():
    posts = []
    for pj in glob.glob("queue/*/post.json"):
        with open(pj, encoding="utf-8") as f:
            p = json.load(f)
        p["_path"] = os.path.dirname(pj)
        if dt.datetime.fromisoformat(p["publish_at"]) <= now_utc():
            posts.append(p)
    return sorted(posts, key=lambda p: p["publish_at"])


def save(post):
    path = post.pop("_path")
    with open(os.path.join(path, "post.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, indent=2, ensure_ascii=False)
    post["_path"] = path


def move(post, dest_root):
    dest = os.path.join(dest_root, os.path.basename(post["_path"]))
    shutil.move(post["_path"], dest)
    post["_path"] = dest


def append_log(post):
    new = not os.path.exists(LOG)
    posted = dt.datetime.fromisoformat(post["posted_at"]).astimezone(LOCAL_TZ)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "slug": post["slug"], "publish_at": post["publish_at"], "posted_at": post["posted_at"],
            "weekday": posted.strftime("%a"), "hour_local": posted.strftime("%H:%M"),
            "media_id": post["media_id"], "permalink": post.get("permalink", ""),
            "like_count": "", "comments_count": "",
            "caption_first_line": post["caption"].splitlines()[0][:120],
        })


def publish_one(post, ig_id, image_url):
    params = {"image_url": image_url, "caption": post["caption"]}
    if post.get("alt_text"):
        params["alt_text"] = post["alt_text"]
    container = call("POST", f"{ig_id}/media", params)["id"]
    for _ in range(30):  # wait until Instagram has fetched and processed the image
        status = call("GET", container, {"fields": "status_code"}).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container} status {status}")
        time.sleep(5)
    media_id = call("POST", f"{ig_id}/media_publish", {"creation_id": container})["id"]
    meta = call("GET", media_id, {"fields": "permalink,timestamp"})
    return media_id, meta.get("permalink", "")


def run_publish(dry_run=False):
    posts = due_posts()
    if not posts:
        print("nothing due")
        return
    post = posts[0]  # one post per run keeps posts spaced out
    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    sha = os.environ.get("GITHUB_SHA", "main")
    image_url = f"https://raw.githubusercontent.com/{repo}/{sha}/{post['_path']}/photo.jpg"
    if dry_run:
        print(json.dumps({"would_publish": post["slug"], "image_url": image_url, "caption": post["caption"]}, indent=2, ensure_ascii=False))
        return
    me = call("GET", "me", {"fields": "user_id,username"})
    ig_id = me.get("user_id") or me["id"]
    try:
        media_id, permalink = publish_one(post, ig_id, image_url)
    except Exception as e:
        post["attempts"] = post.get("attempts", 0) + 1
        post["last_error"] = str(e)[:500]
        if post["attempts"] >= MAX_ATTEMPTS:
            post["status"] = "failed"
            save(post)
            move(post, "failed")
        else:
            save(post)
        print(f"::error::publish failed for {post['slug']}: {e}")
        sys.exit(1)
    post.update(status="posted", media_id=media_id, permalink=permalink,
                posted_at=now_utc().isoformat(timespec="seconds"))
    save(post)
    move(post, "posted")
    append_log(post)
    print(f"published {post['slug']} -> {permalink} as @{me.get('username')}")


def run_stats(days=30):
    if not os.path.exists(LOG):
        print("no log yet")
        return
    with open(LOG, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cutoff = now_utc() - dt.timedelta(days=days)
    for r in rows:
        if r.get("media_id") and dt.datetime.fromisoformat(r["posted_at"]) >= cutoff:
            try:
                m = call("GET", r["media_id"], {"fields": "like_count,comments_count"})
                r["like_count"] = m.get("like_count", "")
                r["comments_count"] = m.get("comments_count", "")
            except Exception as e:
                print(f"::warning::stats failed for {r['slug']}: {e}")
    with open(LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"stats updated for posts since {cutoff.date()}")


def run_refresh(outfile):
    r = call("GET", "refresh_access_token", {"grant_type": "ig_refresh_token"}, base=API)
    with open(outfile, "w") as f:
        f.write(r["access_token"])
    print(f"token refreshed, valid for {int(r.get('expires_in', 0)) // 86400} days")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        me = call("GET", "me", {"fields": "user_id,username,account_type"})
        print(f"connected as @{me.get('username')} ({me.get('account_type', 'professional')})")
    elif "--stats" in args:
        run_stats()
    elif "--refresh-token" in args:
        run_refresh(args[args.index("--refresh-token") + 1])
    else:
        run_publish(dry_run="--dry-run" in args)
