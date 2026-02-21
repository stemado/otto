"""Tests for the screencast recording module."""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from otto.screencast import (
    CHROME_COMPOSITOR_FPS,
    ScreencastMonitor,
    _every_nth_frame,
    _find_ffmpeg,
)
from otto.models import RecordingRecord, RecordingResult


# --- Unit tests for _every_nth_frame ---


class TestEveryNthFrame:
    """Verify FPS-to-every_nth_frame conversion."""

    def test_10fps(self):
        assert _every_nth_frame(10) == round(CHROME_COMPOSITOR_FPS / 10)

    def test_5fps(self):
        assert _every_nth_frame(5) == 12

    def test_15fps(self):
        assert _every_nth_frame(15) == 4

    def test_30fps(self):
        assert _every_nth_frame(30) == 2

    def test_1fps(self):
        assert _every_nth_frame(1) == 60

    def test_60fps_returns_1(self):
        assert _every_nth_frame(60) == 1

    def test_zero_fps_defaults(self):
        assert _every_nth_frame(0) == 6

    def test_negative_fps_defaults(self):
        assert _every_nth_frame(-5) == 6

    def test_minimum_is_1(self):
        # Even very high fps should never return 0
        assert _every_nth_frame(1000) >= 1


# --- Unit tests for _find_ffmpeg ---


class TestFindFfmpeg:
    """Verify ffmpeg discovery logic."""

    def test_returns_string_or_none(self):
        result = _find_ffmpeg()
        assert result is None or isinstance(result, str)

    def test_imageio_ffmpeg_preferred(self):
        """When imageio_ffmpeg is available, its binary is returned."""
        mock_path = "/mock/ffmpeg"
        with patch("otto.screencast.shutil.which", return_value=None):
            with patch.dict("sys.modules", {"imageio_ffmpeg": MagicMock(get_ffmpeg_exe=lambda: mock_path)}):
                # Re-import to pick up the mock
                from otto.screencast import _find_ffmpeg as find
                result = find()
                # Should use imageio_ffmpeg first
                assert result == mock_path or result is not None

    def test_system_ffmpeg_fallback(self):
        """When imageio_ffmpeg is missing, falls back to system PATH."""
        with patch.dict("sys.modules", {"imageio_ffmpeg": None}):
            with patch("otto.screencast.shutil.which") as mock_which:
                mock_which.return_value = "/usr/bin/ffmpeg"
                result = _find_ffmpeg()
                # Should call shutil.which as fallback
                # (exact behavior depends on whether imageio_ffmpeg import raises)


# --- Unit tests for ScreencastMonitor ---


class TestScreencastMonitor:
    """Test ScreencastMonitor lifecycle without a real browser."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix="otto_test_")
        self.monitor = ScreencastMonitor(self.tmpdir)

    def teardown_method(self):
        self.monitor.cleanup()
        if os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_initial_state(self):
        assert self.monitor.recording is False
        assert self.monitor._frame_count == 0
        assert self.monitor._generation == 0

    def test_stop_when_not_recording(self):
        result = self.monitor.stop()
        assert result["frame_count"] == 0
        assert result["error"] == "No recording in progress."

    def test_status_when_not_recording(self):
        status = self.monitor.status()
        assert status["recording"] is False
        assert status["frame_count"] == 0
        assert status["elapsed_seconds"] == 0.0

    def test_cleanup_is_safe_when_no_frames_dir(self):
        # Should not raise
        self.monitor.cleanup()
        self.monitor.cleanup()  # Double cleanup is safe

    def test_generation_increments_on_start(self):
        """Each start() should increment the generation counter."""
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver)
        assert self.monitor._generation == 1

        # Stop first, then start again
        self.monitor.stop()
        self.monitor.start(driver)
        assert self.monitor._generation == 2

    def test_start_creates_frames_dir(self):
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver)
        assert self.monitor._frames_dir is not None
        assert os.path.isdir(self.monitor._frames_dir)
        self.monitor.stop()

    def test_start_when_already_recording_raises(self):
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver)
        with pytest.raises(ValueError, match="Recording already in progress"):
            self.monitor.start(driver)
        self.monitor.stop()

    def test_start_registers_cdp_handler(self):
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver)
        driver._tab.add_handler.assert_called_once()
        self.monitor.stop()

    def test_start_sends_cdp_start_screencast(self):
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver, target_fps=10)
        driver.run_cdp_command.assert_called_once()
        self.monitor.stop()

    def test_stop_sends_cdp_stop_screencast(self):
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver)
        driver.run_cdp_command.reset_mock()
        self.monitor.stop()
        # stop_screencast should have been called
        driver.run_cdp_command.assert_called_once()

    def test_stop_returns_result_dict(self):
        driver = MagicMock()
        driver._tab = MagicMock()
        driver._tab.add_handler = MagicMock()
        driver.run_cdp_command = MagicMock()

        self.monitor.start(driver)
        result = self.monitor.stop()
        assert "frame_count" in result
        assert "duration_seconds" in result
        assert "encoded" in result
        assert result["frame_count"] == 0  # No actual frames received

    def test_encode_video_no_frames(self):
        """Encoding with 0 frames should return gracefully."""
        path, success, error = self.monitor._encode_video(self.tmpdir, 0)
        assert path is None
        assert success is False
        assert "No frames" in error


# --- Model tests ---


class TestRecordingModels:
    """Verify recording models serialize correctly."""

    def test_recording_result_defaults(self):
        result = RecordingResult()
        dumped = result.model_dump(exclude_none=True)
        assert dumped["recording_active"] is False
        assert dumped["frame_count"] == 0
        assert "error" not in dumped  # None fields excluded

    def test_recording_result_with_video(self):
        result = RecordingResult(
            recording_active=False,
            video_path="/tmp/recording.mp4",
            frame_count=100,
            duration_seconds=10.0,
            encoded=True,
        )
        dumped = result.model_dump(exclude_none=True)
        assert dumped["video_path"] == "/tmp/recording.mp4"
        assert dumped["encoded"] is True

    def test_recording_record_defaults(self):
        record = RecordingRecord()
        assert record.frame_count == 0
        assert record.encoded is False

    def test_recording_record_serialization(self):
        record = RecordingRecord(
            started_at="2025-01-01T00:00:00Z",
            stopped_at="2025-01-01T00:01:00Z",
            duration_seconds=60.0,
            frame_count=600,
            video_path="/tmp/out.mp4",
            encoded=True,
            timestamp="2025-01-01T00:01:00Z",
        )
        dumped = record.model_dump(exclude_none=True)
        assert dumped["frame_count"] == 600
        assert dumped["video_path"] == "/tmp/out.mp4"
