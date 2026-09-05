"""Phase-1 rendering reliability tests for ShortForge's FFmpeg render path.

Run (from the repo root):
    apps/api/.venv/Scripts/python.exe -m unittest discover -s apps/api/tests

Covers:
  * reproduction of the historical "No such filter: '0.445667)'" bug
  * escaped filter expressions render on Windows for landscape + portrait
  * output normalization: 1080x1920, 30 fps, yuv420p, SAR 1:1, DAR 9:16, faststart
  * zoom path no longer leaks odd sample-aspect-ratio values
  * graceful center-crop fallback when tracking is unreliable
  * useful RenderError (real FFmpeg stderr) instead of a bare return code
  * end-to-end render_plan concatenation + captions burning
"""

import json
import shutil
import time
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
from services import media  # noqa: E402
from services.subtitles import to_ass  # noqa: E402
from services.recreation import (  # noqa: E402
    _beat_env_expr,
    _default_mapping,
    _effect_filters,
    _local_beats,
    assign_segment_roles,
    distribute_all_assets,
    render_asset_segment,
    render_recreation,
    snap_segments_to_beats,
)
from services.assets import (  # noqa: E402
    AssetError,
    classify,
    list_assets,
    probe_asset,
    save_asset,
)


def synth_source(path, w, h, dur=4.0, fps=30, with_audio=True):
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={w}x{h}:rate={fps}:duration={dur}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
    ]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


def probe(path):
    data = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,width,height,pix_fmt,sample_aspect_ratio,display_aspect_ratio,r_frame_rate,avg_frame_rate",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
    )
    v = next(s for s in data["streams"] if s.get("codec_type") == "video")
    a = next((s for s in data["streams"] if s.get("codec_type") == "audio"), {})
    return {"video": v, "audio": a, "format": data["format"]}


def has_faststart(path):
    with open(path, "rb") as f:
        head = f.read(2 * 1024 * 1024)
    mv = head.find(b"moov")
    md = head.find(b"mdat")
    if mv == -1 or md == -1:
        return False
    return mv < md


def make_track(w, h):
    """A realistic multi-keyframe tracked subject."""
    return [
        {"time": 0.0, "x": w * 0.5, "y": h * 0.5, "confidence": 0.9, "track_id": 0},
        {
            "time": 0.445667,
            "x": w * 0.62,
            "y": h * 0.45,
            "confidence": 0.8,
            "track_id": 0,
        },
        {"time": 1.1, "x": w * 0.38, "y": h * 0.6, "confidence": 0.7, "track_id": 0},
        {"time": 1.6, "x": w * 0.5, "y": h * 0.5, "confidence": 0.75, "track_id": 0},
    ]


class MediaRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg/ffprobe not on PATH")
        cls._work = Path(tempfile.mkdtemp(prefix="sf-tests-"))
        cls.land = cls._work / "landscape.mp4"
        cls.port = cls._work / "portrait.mp4"
        synth_source(cls.land, 640, 360, dur=4.0)
        synth_source(cls.port, 480, 854, dur=4.0)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._work, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Filter construction & escaping                                     #

    def test_escape_expr_escapes_all_specials(self):
        self.assertEqual(media._escape_expr("a,b;c:d"), "a\\,b\\;c\\:d")
        self.assertEqual(media._escape_expr("C:/x/sub.ass"), "C\\:/x/sub.ass")
        # No raw comma/semicolon/colon survives without a backslash.
        for ch in (",", ";", ":"):
            esc = media._escape_expr(f"f({ch}1{ch}2)")
            self.assertNotIn(ch, esc.replace(f"\\{ch}", ""))

    def test_reproduce_legacy_no_such_filter_failure(self):
        """The historical bug: unescaped commas inside crop() expressions."""
        for src in (self.land, self.port):
            info = media.ffprobe(str(src))
            track = make_track(info.width, info.height)
            crop, _, _ = media._tracked_crop_filter(info.width, info.height, track)
            self.assertIn("\\,", crop)  # our version keeps commas escaped
            legacy = crop.replace("\\,", ",")  # revert to the broken form
            p = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    "0",
                    "-i",
                    str(src),
                    "-t",
                    "1",
                    "-vf",
                    legacy,
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                p.returncode, 0, "legacy unescaped filter unexpectedly succeeded"
            )
            self.assertIn(
                "No such filter",
                (p.stderr or ""),
                f"stderr was: {(p.stderr or '')[-800:]}",
            )

    def test_escaped_filter_renders_for_landscape_and_portrait(self):
        for src in (self.land, self.port):
            info = media.ffprobe(str(src))
            track = make_track(info.width, info.height)
            crop, _, _ = media._tracked_crop_filter(info.width, info.height, track)
            self.assertIn("\\,", crop)  # commas escaped inside the expression
            vf, is_complex = media._build_vertical_filter(
                info.width, info.height, track, zoom=1.0
            )
            if is_complex:
                # Landscape: blur-pad fit graph ends with the SAR guard.
                self.assertTrue(vf.endswith("setsar=1[vout]"), vf[-120:])
                self.assertIn("force_original_aspect_ratio=decrease", vf)
            else:
                self.assertTrue(vf.endswith("setsar=1"))
                self.assertTrue(vf.startswith("crop="))
            out = self._work / f"{src.stem}-escaped.mp4"
            media.render_vertical(str(src), str(out), 0.0, 1.5, track=track)
            self._assert_normalized(out, expected_duration=1.5)

    def test_fit_mode_selection_by_aspect(self):
        """Wide sources use blur-pad fit; 9:16-ish sources keep crop-fill."""
        for w, h in ((640, 360), (640, 640), (800, 1000), (720, 960), (1920, 1080)):
            vf, is_complex = media._build_vertical_filter(w, h, None, zoom=1.0)
            self.assertTrue(is_complex, f"{w}x{h} should use fit mode")
            self.assertIn("[bgb][fgs]overlay=(W-w)/2:(H-h)/2", vf)
            self.assertIn("force_original_aspect_ratio=decrease", vf)
        for w, h in ((480, 854), (540, 960), (720, 1280), (1080, 1920)):
            vf, is_complex = media._build_vertical_filter(w, h, None, zoom=1.0)
            self.assertFalse(is_complex, f"{w}x{h} should use crop-fill mode")
            self.assertTrue(vf.endswith("setsar=1"))
            self.assertTrue(vf.startswith("crop="))

    def test_wide_source_fit_render_not_overzoomed(self):
        """Regression for 'rendered short is too upscaled/big': a 640x360
        source must render through the blur-pad fit (whole frame visible,
        no 5x sliver upscale) with normalized output geometry."""
        info = media.ffprobe(str(self.land))
        self.assertGreater(
            info.width / info.height,
            media.FIT_MAX_SOURCE_AR,
            "test source should be wide enough to trigger fit mode",
        )
        out = self._work / "fit-mode.mp4"
        media.render_vertical(str(self.land), str(out), 0.0, 1.5, track=None)
        self._assert_normalized(out, expected_duration=1.5)

    def test_zoom_path_keeps_sar_1(self):
        """Odd-SAR leak regression: zoom must keep SAR 1:1 and DAR 9:16."""
        for src, zoom in ((self.land, 1.06), (self.port, 1.06), (self.land, 1.0)):
            info = media.ffprobe(str(src))
            out = self._work / f"{src.stem}-zoom{zoom}.mp4"
            media.render_vertical(
                str(src),
                str(out),
                0.0,
                1.5,
                zoom=zoom,
                track=make_track(info.width, info.height),
            )
            self._assert_normalized(out, expected_duration=1.5)

    def test_sanitize_track_falls_back_to_center_crop(self):
        garbage = [
            {"time": 0.0, "x": float("nan"), "y": 100.0, "confidence": 1.0},
            {"time": 1.0, "x": 1e18, "y": 100.0, "confidence": 1.0},
            {"time": 2.0, "x": 50.0, "y": 50.0, "confidence": 0.0},
            {"time": "x", "x": 50.0, "y": 50.0},
        ]
        self.assertIsNone(media._sanitize_track([], 640, 360, 4.0))
        self.assertIsNone(media._sanitize_track(None, 640, 360, 4.0))
        self.assertIsNone(media._sanitize_track(garbage, 640, 360, 4.0))
        ok = media._sanitize_track(
            [
                {"time": 2.0, "x": 100.0, "y": 100.0, "confidence": 0.9, "track_id": 0},
                {"time": 0.0, "x": 50.0, "y": 50.0, "confidence": 0.8, "track_id": 0},
            ],
            640,
            360,
            4.0,
        )
        self.assertEqual([p["time"] for p in ok], [0.0, 2.0])
        out = self._work / "garbage-track.mp4"
        media.render_vertical(str(self.land), str(out), 0.0, 1.0, track=garbage)
        self._assert_normalized(out, expected_duration=1.0)

    def test_ai_transition_metadata(self):
        """Auto-editor assigns preset-aware transitions, effects and a 0..1
        beat_intensity score per segment (the frontend's live beat-wave data)."""
        segs = [
            {"id": "a", "start": 0.0, "end": 1.0, "beat_sync": False, "speech_density": 0.1},
            {"id": "b", "start": 1.0, "end": 1.8, "beat_sync": False, "speech_density": 0.9},
            {"id": "c", "start": 1.8, "end": 2.0, "beat_sync": True, "speech_density": 0.9},
        ]
        tagged = media.apply_transition_metadata(segs, beats=[1.0, 2.0], preset="energy")
        self.assertEqual(tagged[0]["transition"], "none")

        # Beat-aligned scene -> punchy transition + motion effect.
        end = tagged[-1]
        self.assertIn(end["transition"], {"flash", "zoom", "pixelize"})
        self.assertIn(end["effect"], {"shake", "bw", "pulse"})
        for item in tagged:
            self.assertGreaterEqual(item["beat_intensity"], 0.0)
            self.assertLessEqual(item["beat_intensity"], 1.0)
            self.assertIsInstance(item["beat_intensity"], float)
        # Effects persist when already user-chosen; duplicates are untouched.
        tagged2 = media.apply_transition_metadata(
            [{"id": "x", "start": 0, "end": 1, "effect": "moody"}], preset="viral"
        )
        self.assertEqual(tagged2[0]["effect"], "moody")

    def test_render_plan_end_to_end(self):
        segments = [
            {"start": 0.0, "end": 1.2, "zoom": 1.0},
            {"start": 1.2, "end": 2.6, "zoom": 1.06},
            {"start": 2.6, "end": 3.5, "zoom": 1.0},
        ]
        info = media.ffprobe(str(self.port))
        out = self._work / "plan-out.mp4"
        media.render_plan(
            str(self.port),
            str(out),
            segments,
            track=make_track(info.width, info.height),
        )
        self._assert_normalized(out, expected_duration=3.5)

    def test_render_plan_single_segment_fast_path(self):
        out = self._work / "single.mp4"
        media.render_plan(
            str(self.land), str(out), [{"start": 0.5, "end": 2.0, "zoom": 1.0}]
        )
        self._assert_normalized(out, expected_duration=1.5)

    def test_captions_burned_on_windows_path(self):
        ass = self._work / "subs.ass"
        to_ass(
            [
                {
                    "start": 0.02,
                    "end": 1.5,
                    "text": "hello world",
                    "words": [
                        {"text": "hello", "start": 0.02, "end": 0.8, "emphasis": True},
                        {"text": "world", "start": 0.8, "end": 1.5, "emphasis": False},
                    ],
                }
            ],
            str(ass),
            "viral",
        )
        out = self._work / "captioned.mp4"
        media.render_vertical(
            str(self.land),
            str(out),
            0.0,
            1.5,
            subtitle_file=str(ass),
            track=make_track(640, 360),
        )
        self._assert_normalized(out, expected_duration=1.5)

    def test_render_error_carries_ffmpeg_stderr(self):
        with self.assertRaises(media.RenderError) as ctx:
            media.render_plan(
                str(self._work / "missing-file.mp4"),
                str(self._work / "nope.mp4"),
                [{"start": 0.0, "end": 1.0}],
            )
        self.assertIn("Could not read media file", str(ctx.exception))
        with self.assertRaises(media.RenderError) as ctx2:
            media._run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=0.5:size=32x32:rate=10",
                    "-vf",
                    "crop=16:16:if(lt(t\\,0.2),0,0),NoSuchFilterXyz",
                    "-frames:v",
                    "1",
                    str(self._work / "bad.mp4"),
                ]
            )
        self.assertIn("FFmpeg command failed", str(ctx2.exception))

    def test_api_endpoint_returns_useful_error(self):
        try:
            import main as api_main
        except Exception:
            self.skipTest("main.py deps unavailable")
        req = api_main.RenderPlanRequest(
            source_path=str(self._work / "does-not-exist.mp4"),
            output_path=str(self._work / "api-out.mp4"),
            segments=[{"start": 0.0, "end": 1.0}],
            captions=[],
        )
        with self.assertRaises(Exception) as ctx:
            api_main.render_plan_endpoint(req)
        self.assertIn("Could not read media file", str(ctx.exception))

    def test_full_api_pipeline_analyze_to_render(self):
        """End-to-end: /v1/analyze => /v1/render-plan => normalized MP4."""
        try:
            import main as api_main
        except Exception:
            self.skipTest("main.py deps unavailable")
        from fastapi.testclient import TestClient

        # Avoid heavy/remote model work: no person tracking, no whisper.
        api_main.detect_people = lambda *a, **k: []
        api_main.transcribe = lambda p: []
        api_main.find_broll = lambda d: []

        client = TestClient(api_main.app)
        with open(self.land, "rb") as f:
            up = client.post("/v1/upload", files={"file": ("clip.mp4", f, "video/mp4")})
        self.assertEqual(up.status_code, 200, up.text)
        source_path = up.json()["source_path"]

        # Analyze a 4s landscape clip.
        an = client.post(
            "/v1/analyze",
            json={
                "source_name": "clip.mp4",
                "source_path": source_path,
                "duration": 4.0,
                "width": 640,
                "height": 360,
                "fps": 30,
                "preset": "viral",
            },
        )
        self.assertEqual(an.status_code, 200, an.text)
        plan = an.json()
        self.assertTrue(plan["segments"], "analyze produced no segments")
        self.assertEqual(plan["status"], "ready")

        # Render the plan through the API using the exact frontend payload:
        # a relative "shortforge-render/<file>.mp4" output_path.
        rp = client.post(
            "/v1/render-plan",
            json={
                "source_path": source_path,
                "output_path": f"shortforge-render/api-pipeline-{time.time_ns()}.mp4",
                "segments": plan["segments"],
                "captions": plan["captions"],
                "reframe": plan["reframe"],
                "preset": "viral",
            },
        )
        self.assertEqual(rp.status_code, 200, rp.text)
        data = rp.json()
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["captions_burned"], bool(plan["captions"]))
        # The /outputs mount must serve the rendered file (regression for the
        # double-nested render-dir path that produced a 404 on GET).
        served = client.get(data["preview_url"])
        self.assertEqual(served.status_code, 200, served.text[:500])
        rendered = Path(data["output_path"])
        self.assertEqual(
            str(rendered.resolve()).startswith(str(api_main.RENDER_DIR.resolve())), True
        )
        self.assertTrue(rendered.exists())
        # The synthetic test pattern trips scene-cuts, so the plan may end a
        # fraction before the source; compare against the plan, not the source.
        plan_dur = sum(float(s["end"]) - float(s["start"]) for s in plan["segments"])
        self._assert_normalized(rendered, expected_duration=plan_dur)
        rendered.unlink(missing_ok=True)  # tidy the test output
        Path(source_path).unlink(missing_ok=True)  # tidy the test upload

    # ------------------------------------------------------------------ #
    # Output validation                                                  #

    def _assert_normalized(self, path, expected_duration):
        self.assertTrue(path.exists(), f"output missing: {path}")
        info = probe(path)
        v = info["video"]
        self.assertEqual(v["codec_name"], "h264")
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertEqual(v["pix_fmt"], "yuv420p")
        self.assertEqual(v["sample_aspect_ratio"], "1:1")
        self.assertEqual(v["display_aspect_ratio"], "9:16")
        self.assertEqual(v["r_frame_rate"], "30/1")
        self.assertAlmostEqual(
            float(info["format"]["duration"]), expected_duration, delta=0.35
        )
        self.assertTrue(has_faststart(path), f"faststart missing for {path}")
        if info["audio"]:
            self.assertEqual(info["audio"].get("codec_name"), "aac")


class RecreationTests(unittest.TestCase):
    """Recreation engine: user assets rendered into the reference structure."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="sf-recreation-"))
        # Reference clip WITH audio -> its track is muxed onto the recreation.
        cls.reference = cls.tmp / "ref.mp4"
        synth_source(cls.reference, 480, 854, dur=4.0, with_audio=True)
        # Portrait video asset and a wide (landscape) image asset, so both
        # geometry paths (portrait cover-crop with drift, wide blur-pad fit)
        # are exercised, and both asset kinds (video + still image).
        cls.video_asset = cls.tmp / "asset-video.mp4"
        synth_source(cls.video_asset, 720, 1280, dur=2.0, with_audio=True)
        cls.image_asset = cls.tmp / "asset-image.png"
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=orange:s=1280x720:d=1",
                "-frames:v", "1", str(cls.image_asset),
            ],
            check=True,
        )
        cls.segments = [
            {"id": "seg-1", "start": 0.0, "end": 1.0, "zoom": 1.0},
            {
                "id": "seg-2", "start": 1.0, "end": 2.2,
                "zoom": 1.1, "transition": "fade",
            },
            {"id": "seg-3", "start": 2.2, "end": 3.4, "zoom": 1.0},
        ]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_render_recreation_with_mapped_assets(self):
        out = self.tmp / "recreation.mp4"
        render_recreation(
            str(self.reference),
            self.segments,
            [probe_asset(self.video_asset), probe_asset(self.image_asset)],
            {"seg-1": self.video_asset.stem, "seg-2": self.image_asset.stem},
            str(out),
        )
        self.assertTrue(out.exists(), "recreation output missing")
        info = probe(out)
        v = info["video"]
        self.assertEqual(v["codec_name"], "h264")
        self.assertEqual((v["width"], v["height"]), (1080, 1920))
        self.assertEqual(v["pix_fmt"], "yuv420p")
        self.assertEqual(v["sample_aspect_ratio"], "1:1")
        self.assertEqual(v["display_aspect_ratio"], "9:16")
        self.assertEqual(v["r_frame_rate"], "30/1")
        # 1.0 + 1.2 + 1.2 = 3.4s of planned segments.
        self.assertAlmostEqual(
            float(info["format"]["duration"]), 3.4, delta=0.35
        )
        # Reference audio must be present (music/beat timing preserved).
        self.assertEqual(info["audio"].get("codec_name"), "aac")
        self.assertTrue(has_faststart(out), "faststart missing")
        out.unlink(missing_ok=True)

    def test_unmapped_segments_fall_back_and_render(self):
        out = self.tmp / "recreation-fallback.mp4"
        # No mapping at all: sequential fallback must still succeed.
        render_recreation(
            None, self.segments[:2],
            [probe_asset(self.image_asset), probe_asset(self.video_asset)],
            {}, str(out),
        )
        info = probe(out)
        self.assertEqual((info["video"]["width"], info["video"]["height"]), (1080, 1920))
        # No reference -> silent output is expected.
        self.assertEqual(info["audio"], {})
        out.unlink(missing_ok=True)

    def test_missing_asset_file_raises(self):
        with self.assertRaises(Exception):
            render_asset_segment(
                {"id": "x", "name": "gone.png", "path": str(self.tmp / "gone.png"),
                 "kind": "image", "width": 100, "height": 100, "duration": 0},
                1.0, 1.0, 0, self.tmp / "never.mp4",
            )

    def test_asset_registry_roundtrip(self):
        self.assertEqual(classify("photo.JPG"), "image")
        self.assertEqual(classify("clip.MOV"), "video")
        with self.assertRaises(AssetError):
            classify("song.mp3")
        saved = save_asset("my photo.png", b"\x89PNG-not-really", self.tmp)
        self.assertEqual(saved["kind"], "image")
        self.assertTrue(Path(saved["path"]).exists())
        names = [a["name"] for a in list_assets(self.tmp)]
        self.assertIn(saved["name"], names)
        Path(saved["path"]).unlink(missing_ok=True)

    def test_snap_segments_to_beats(self):
        segments = [
            {"id": "a", "start": 0.0, "end": 1.03},
            {"id": "b", "start": 1.03, "end": 2.5},
            {"id": "c", "start": 2.5, "end": 4.0},
        ]
        snapped = snap_segments_to_beats(segments, [1.0, 2.0, 3.0])
        # 1.03 sits within tolerance of beat 1.0 -> snapped.
        self.assertEqual(snapped[0]["end"], 1.0)
        self.assertEqual(snapped[1]["start"], 1.0)
        # 2.5 has no beat within 0.12s -> left alone.
        self.assertEqual(snapped[1]["end"], 2.5)
        self.assertEqual(snapped[2]["start"], 2.5)
        # Boundaries stay contiguous and durations renderable.
        for a, b in zip(snapped, snapped[1:]):
            self.assertEqual(a["end"], b["start"])
            self.assertGreaterEqual(a["end"] - a["start"], 0.2)
        # Empty beats -> plan returned unchanged.
        self.assertEqual(snap_segments_to_beats(segments, []), segments)

    def test_default_mapping_rules(self):
        assets = [
            {"id": "img-1", "kind": "image"},
            {"id": "img-2", "kind": "image"},
            {"id": "vid-1", "kind": "video"},
        ]
        segments = [
            {"id": "s1", "start": 0.0, "end": 0.3},  # ultra-short -> image
            {"id": "s2", "start": 0.3, "end": 1.4},
            {"id": "s3", "start": 1.4, "end": 2.6},
        ]
        m = _default_mapping(segments, assets)
        self.assertEqual(m["s1"], "img-1")
        # No asset repeats on consecutive segments.
        self.assertNotEqual(m["s2"], m["s1"])
        self.assertNotEqual(m["s3"], m["s2"])

    def test_zoom_transition_uses_real_xfade(self):
        # seg-2 enters with a fade and seg-3 with a zoom: all three live in
        # ONE xfade run (single extra encode), output stays normalized and
        # the reference audio is still muxed.
        segments = [
            {"id": "seg-1", "start": 0.0, "end": 1.0, "zoom": 1.0},
            {
                "id": "seg-2", "start": 1.0, "end": 2.0,
                "zoom": 1.1, "transition": "fade",
            },
            {
                "id": "seg-3", "start": 2.0, "end": 3.0,
                "zoom": 1.0, "transition": "zoom",
            },
        ]
        out = self.tmp / "recreation-xfade.mp4"
        render_recreation(
            str(self.reference),
            segments,
            [probe_asset(self.image_asset), probe_asset(self.video_asset)],
            {
                "seg-1": self.image_asset.stem,
                "seg-2": self.video_asset.stem,
                "seg-3": self.image_asset.stem,
            },
            str(out),
        )
        self.assertTrue(out.exists(), "xfade recreation output missing")
        info = probe(out)
        self.assertEqual(
            (info["video"]["width"], info["video"]["height"]), (1080, 1920)
        )
        self.assertEqual(info["video"]["sample_aspect_ratio"], "1:1")
        self.assertEqual(info["video"]["r_frame_rate"], "30/1")
        self.assertEqual(info["audio"].get("codec_name"), "aac")
        out.unlink(missing_ok=True)

    def test_assign_segment_roles(self):
        segments = [
            {"id": "s1", "start": 0.0, "end": 1.0},
            {"id": "s2", "start": 1.0, "end": 2.0},
            {"id": "bad", "start": "x", "end": 2.0},
        ]
        tracking = [{"time": 1.5}, {"time": 0.5}]
        roles = assign_segment_roles(segments, tracking)
        self.assertEqual(roles[0]["role"], "person")  # sample inside [0, 1]
        self.assertEqual(roles[1]["role"], "person")  # sample inside [1, 2]
        # Unparsable segments default to "scene" instead of raising.
        self.assertEqual(roles[2]["role"], "scene")
        # Without tracking everything is a scene.
        self.assertTrue(
            all(r["role"] == "scene" for r in assign_segment_roles(segments, []))
        )
        # Original dicts are not mutated.
        self.assertNotIn("role", segments[0])

    def test_default_mapping_prefers_orientation_by_role(self):
        assets = [
            {"id": "portrait-1", "kind": "image", "width": 720, "height": 1280},
            {"id": "wide-1", "kind": "image", "width": 1280, "height": 720},
        ]
        segments = [
            {"id": "p1", "start": 0.0, "end": 1.0, "role": "person"},
            {"id": "sc1", "start": 1.0, "end": 2.0, "role": "scene"},
        ]
        m = _default_mapping(segments, assets)
        self.assertEqual(m["p1"], "portrait-1")
        self.assertEqual(m["sc1"], "wide-1")
        # No role info -> still assigns something valid.
        m2 = _default_mapping(
            [{"id": "x", "start": 0.0, "end": 1.0}], assets
        )
        self.assertIn(m2["x"], {"portrait-1", "wide-1"})

    def test_distribute_all_assets_uses_every_file(self):
        """More assets than segments -> long segments split, all files used."""
        segments = [
            {"id": "a", "start": 0.0, "end": 3.0},
            {"id": "b", "start": 3.0, "end": 4.0},
            {"id": "c", "start": 4.0, "end": 7.0},
            {"id": "d", "start": 7.0, "end": 8.0},
        ]
        assets = [{"id": f"img{i}", "kind": "image"} for i in range(8)]
        segs, mapping = distribute_all_assets(segments, assets)
        self.assertEqual(len(segs), 8)
        used = set(mapping.values())
        self.assertEqual(used, {a["id"] for a in assets})
        # Contiguity and total duration are preserved.
        total_before = sum(s["end"] - s["start"] for s in segments)
        total_after = sum(s["end"] - s["start"] for s in segs)
        self.assertAlmostEqual(total_before, total_after, places=6)
        for i in range(len(segs) - 1):
            self.assertAlmostEqual(
                float(segs[i]["end"]), float(segs[i + 1]["start"]), places=6
            )
        # Split parts enter with a hard cut; durations stay >= 0.4s.
        for s in segs:
            self.assertGreaterEqual(s["end"] - s["start"], 0.4)
        splits = [s for s in segs if "-p" in str(s.get("id", ""))]
        for s in splits:
            self.assertEqual(s.get("transition"), "cut")

    def test_distribute_short_segments_prefers_stills(self):
        """Ultra-short slots swap a video for a still image when possible."""
        segments = [
            {"id": "fast", "start": 0.0, "end": 0.4},
            {"id": "long", "start": 0.4, "end": 2.4},
        ]
        assets = [
            {"id": "vid", "kind": "video"},
            {"id": "pic", "kind": "image"},
        ]
        _, mapping = distribute_all_assets(segments, assets)
        self.assertEqual(mapping["fast"], "pic")
        self.assertEqual(mapping["long"], "vid")

    def test_effect_filter_chains(self):
        """Named effects produce valid post-geometry chains; none -> empty."""
        self.assertEqual(_effect_filters(None, 0, 1.0), "")
        self.assertEqual(_effect_filters("none", 0, 1.0), "")
        for name in ("shake", "pulse", "rotate"):
            chain = _effect_filters(name, 1, 1.5)
            self.assertIn(f"crop={media.OUT_W}:{media.OUT_H}", chain)
        self.assertIn("vignette", _effect_filters("vignette", 0, 1.0))
        self.assertIn("eq=", _effect_filters("brighten", 0, 1.0))
        self.assertIn("hue=s=0", _effect_filters("bw", 0, 1.0))

    def test_beat_synced_effects_embed_energy_envelope(self):
        """Motion effects multiply amplitude by a beat-energy envelope when
        reference beats are supplied, but keep the exact same shape without
        beats (so old renders are unchanged)."""
        plain = _effect_filters("shake", 0, 1.0)
        synced = _effect_filters("shake", 0, 1.0, beats=[0.5, 1.0])
        self.assertNotEqual(synced, plain)
        self.assertIn("1-3*(", synced)
        self.assertIn("abs(t-0.", synced)
        self.assertIn(f"crop={media.OUT_W}:{media.OUT_H}", synced)
        # Local-beat shifting maps reference time into the segment clock:
        # beats 1.0/2.0 are inside the halo [-0.2, 3.2], 4.0/9.0 are not.
        local = _local_beats([1.0, 2.0, 4.0, 9.0], seg_start=0.5, dur=2.0)
        self.assertEqual(local, [0.5, 1.5])
        # beats-relative helper: no beats -> None (static amplitude).
        self.assertIsNone(_local_beats([], 0.0, 1.0))
        self.assertIsNone(_local_beats(None, 0.0, 1.0))
        # Static envelope stays identical to pre-beat behavior.
        self.assertEqual(_beat_env_expr([]), "1.0")
        self.assertIn("min(", _beat_env_expr([0.25, 1.0]))

    def test_beat_synced_effects_render_in_ffmpeg(self):
        """The beat-energy envelope expression must actually render: motion
        effects with reference beats keep producing a normalized segment."""
        for name in ("shake", "pulse"):
            out = self.tmp / f"beat-{name}.mp4"
            render_asset_segment(
                probe_asset(self.video_asset),
                1.0,
                1.1,
                0,
                out,
                effect=name,
                beats=[0.4, 0.7, 1.0],  # reference-time hits inside the segment
                seg_start=0.0,
            )
            self.assertTrue(out.exists(), f"beat-synced {name} render missing")
            info = probe(out)
            v = info["video"]
            self.assertEqual((v["width"], v["height"]), (1080, 1920))
            self.assertEqual(v["codec_name"], "h264")
            self.assertTrue(has_faststart(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
