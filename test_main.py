"""Unit tests for ai_daily_ed.

These tests focus on the pure-Python helpers — no network, no Telegram,
no AI calls. They run with stdlib `unittest` so no extra dependencies.
Run with:  python -m unittest test_main.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

# Make main.py importable when running tests from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main  # noqa: E402


class TestNormalizeUrl(unittest.TestCase):
    def test_lowercase_and_https(self) -> None:
        self.assertEqual(
            main.normalize_url("HTTP://Example.com/Foo/"),
            "https://example.com/foo",
        )

    def test_strip_trailing_slash(self) -> None:
        self.assertEqual(
            main.normalize_url("https://example.com/foo/"),
            "https://example.com/foo",
        )

    def test_strip_utm_trackers(self) -> None:
        self.assertEqual(
            main.normalize_url("https://example.com/a?utm_source=x&id=1"),
            "https://example.com/a?id=1",
        )

    def test_strip_dangling_separator(self) -> None:
        # After removing utm_*, only "?id=1" should remain (no dangling "?").
        self.assertEqual(
            main.normalize_url("https://example.com/a?utm_source=x"),
            "https://example.com/a",
        )


class TestCleanHtml(unittest.TestCase):
    def test_strips_tags_and_entities(self) -> None:
        self.assertEqual(
            main.clean_html("<p>Hello&nbsp;world</p>  "),
            "Hello world",
        )

    def test_handles_empty(self) -> None:
        self.assertEqual(main.clean_html(""), "")
        self.assertEqual(main.clean_html(None), "")


class TestIsValidNews(unittest.TestCase):
    def test_blocks_podcast_keyword(self) -> None:
        self.assertFalse(main.is_valid_news("AI Weekly Podcast #42"))

    def test_blocks_persian_keyword(self) -> None:
        self.assertFalse(main.is_valid_news("راهنمای خرید لپ‌تاپ"))

    def test_accepts_clean_title(self) -> None:
        self.assertTrue(main.is_valid_news("OpenAI releases new model"))


class TestExtractPostText(unittest.TestCase):
    def test_extracts_post_tag(self) -> None:
        raw = "<decision>NEWS_ID: 1, STYLE: SHORT_PUNCHY</decision>\n<post>Hello world</post>"
        self.assertEqual(main.extract_post_text(raw), "Hello world")

    def test_returns_none_when_missing(self) -> None:
        self.assertIsNone(main.extract_post_text("no tags here"))


class TestExtractNewsId(unittest.TestCase):
    def test_parses_news_id(self) -> None:
        raw = "<decision>NEWS_ID: 7, STYLE: ANALYTICAL_DEEP</decision><post>…</post>"
        self.assertEqual(main.extract_news_id(raw), 7)

    def test_returns_none_when_missing(self) -> None:
        self.assertIsNone(main.extract_news_id("<post>x</post>"))


class TestFormatPostForTelegram(unittest.TestCase):
    NEWS = [
        {
            "source": "TechCrunch",
            "title": "X",
            "link": "https://techcrunch.com/story",
            "norm_link": "https://techcrunch.com/story",
            "summary": "summary",
        },
        {
            "source": "Wired",
            "title": "Y",
            "link": "https://wired.com/story-2",
            "norm_link": "https://wired.com/story-2",
            "summary": "summary",
        },
    ]

    def test_bolds_first_line(self) -> None:
        text, _link = main.format_post_for_telegram(
            "این یک تیتر است\nاین بدنه پست است.",
            self.NEWS,
            chosen_news_id=1,
        )
        self.assertIsNotNone(text)
        self.assertIn("<b>این یک تیتر است</b>", text)
        self.assertIn("این بدنه پست است.", text)

    def test_strips_ai_echoed_link(self) -> None:
        # The AI may echo the URL back into the body. We strip it from the
        # body, but the system re-attaches the source link at the bottom.
        text, _link = main.format_post_for_telegram(
            "خبر مهم\nhttps://wired.com/story-2 یک متن",
            self.NEWS,
            chosen_news_id=2,
        )
        self.assertIsNotNone(text)
        # The URL should appear exactly ONCE — in the "منبع" link, not in body.
        self.assertEqual(text.count("https://wired.com/story-2"), 1)
        # …and the source link is reattached at the bottom.
        self.assertIn('href="https://wired.com/story-2"', text)

    def test_fallback_to_first_link(self) -> None:
        text, link = main.format_post_for_telegram(
            "بدون NEWS_ID\nمتن پست",
            self.NEWS,
            chosen_news_id=None,
        )
        self.assertIsNotNone(text)
        self.assertEqual(link, self.NEWS[0]["link"])

    def test_returns_none_for_empty_after_cleanup(self) -> None:
        # Body contains only the URL — should clean up to empty.
        text, link = main.format_post_for_telegram(
            "https://techcrunch.com/story",
            self.NEWS,
            chosen_news_id=1,
        )
        self.assertIsNone(text)
        self.assertIsNone(link)

    def test_truncates_when_over_limit(self) -> None:
        long_body = "این یک پست طولانی است. " * 500
        text, _ = main.format_post_for_telegram(
            "تیتر\n" + long_body,
            self.NEWS,
            chosen_news_id=1,
        )
        self.assertIsNotNone(text)
        self.assertLessEqual(len(text), main.TELEGRAM_MAX_LENGTH)


class TestHistoryStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "posted_history.json")
        self.store = main.HistoryStore(self.path, max_age_days=30)

    def tearDown(self) -> None:
        # Release any portalocker Lock objects first, then close file handles,
        # then delete the temporary files. The explicit close() prevents the
        # "file in use" PermissionError on Windows.
        try:
            self.store.close()
        except Exception:  # noqa: BLE001
            pass
        # Give Windows a moment to release the handle.
        import time
        time.sleep(0.05)
        for p in (self.path, self.path + ".lock", self.path + ".tmp"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except PermissionError:
                    pass  # best-effort cleanup on Windows
        os.rmdir(self.tmpdir)

    def test_creates_empty_when_missing(self) -> None:
        self.assertEqual(self.store.contains(["https://x.com/a"]), set())

    def test_mark_and_contains_roundtrip(self) -> None:
        self.store.mark_posted("https://x.com/a")
        self.store.mark_posted("https://x.com/b")
        self.assertEqual(
            self.store.contains(["https://x.com/a", "https://x.com/c"]),
            {"https://x.com/a"},
        )

    def test_migrates_legacy_list_format(self) -> None:
        # Write the OLD format (a flat JSON list of URLs).
        with open(self.path, "w", encoding="utf-8") as fp:
            json.dump(["https://legacy.example.com/old"], fp)
        # Reading should auto-migrate and return the legacy URL.
        self.assertEqual(
            self.store.contains(["https://legacy.example.com/old"]),
            {"https://legacy.example.com/old"},
        )
        # Writing back should now use the dict format.
        with open(self.path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        self.assertIsInstance(data, dict)
        self.assertIn("https://legacy.example.com/old", data)

    def test_prunes_old_entries_on_mark(self) -> None:
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        with open(self.path, "w", encoding="utf-8") as fp:
            json.dump({"https://old.example.com/": old_ts}, fp)
        # Mark a fresh URL — old one should be pruned during the operation.
        self.store.mark_posted("https://new.example.com/")
        with open(self.path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        self.assertNotIn("https://old.example.com/", data)
        self.assertIn("https://new.example.com/", data)

    def test_recovers_from_corrupt_file(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fp:
            fp.write("not valid json {{{")
        # Should NOT raise — it logs a warning and starts fresh.
        self.assertEqual(self.store.contains(["https://x.com/"]), set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
