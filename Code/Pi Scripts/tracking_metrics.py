"""
tracking_metrics.py
───────────────────
Capstone measurement logger for the surf-tracker.

Logs the four primary quantitative metrics from the project brief for
offline statistical analysis:

  1. Percentage of time on target
       proportion of frames where a target was detected, over total frames
       during the active session window
  2. Mean absolute pixel error
       average Euclidean distance (in pixels) between the chosen target's
       centre and the frame's centre
  3. Reacquisition latency
       wall-clock time between a target being LOST (no detection) and
       being REACQUIRED (next detection). Mean / median / variance are
       computed at session-close.
  4. Alert precision and recall
       counts of system-raised alerts (e.g. "prolonged_submersion") with
       optional ground-truth annotation. precision = TP/(TP+FP),
       recall = TP/(TP+FN). Ground truth can be set live OR filled in
       offline by editing alerts.csv after the session.

Folder layout — each run creates its own folder so the data for one run
stays grouped:

  <project_root>/results/
    2026-05-18_14-32-15_vision-only/
      session_meta.json     # mode, notes, config, timestamps
      detections.csv        # one row per frame
      loss_events.csv       # one row per loss → reacquisition pair
      alerts.csv            # one row per alert event
      summary.json          # computed stats, written on session close

Usage from a main loop:

    from tracking_metrics import SessionRecorder

    with SessionRecorder(mode="vision-only",
                         notes="overcast, low swell",
                         config={"hfov_deg": 67.0, "min_pan_deg": 0.5}) as rec:
        while running:
            ok, frame = cap.read()
            ...
            if chosen_target_found:
                rec.log_detection(
                    surfer_cx, surfer_cy, frame_w, frame_h,
                    confidence=conf, label="surfer",
                    pan_deg=pan_deg, tilt_deg=tilt_deg,
                    base_steps=base_steps, hinge_steps=hinge_steps,
                )
            else:
                rec.log_no_detection(frame_w, frame_h)

            if some_event_triggered:
                rec.log_alert("prolonged_immobility",
                              system_predicted=True, ground_truth=None)

The context manager auto-closes the recorder and writes summary.json on
exit (including KeyboardInterrupt / errors). For long sessions, call
rec.flush() periodically (e.g. once a second) so a crash doesn't lose data.

Pairs with — but is independent of — the tracker scripts:
  Code/Pi Scripts/isolated_yolo_test.py     (current Mac/Arduino test rig)
  Code/Pi Scripts/heltec_bridge_test.py     (future Heltec-integrated rig)
"""

import csv
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path


# ── Default results root: <project_root>/results ──────────────────────────
SCRIPT_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT  = SCRIPT_DIR.parent.parent
DEFAULT_ROOT  = PROJECT_ROOT / "results"


class SessionRecorder:
    """Records per-frame tracking data + events into a timestamped run folder."""

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def __init__(self, mode, notes="", config=None, results_root=None):
        """
        mode          'vision-only' | 'vision+gnss' | any free-text run label
        notes         Free-text conditions ("overcast, 1m swell, 14°C", etc.)
        config        Dict of arbitrary settings snapshot (HFOV, thresholds,
                      model path, ...) — written verbatim into session_meta.json
        results_root  Override the default results/ location (Path or str)
        """
        ts   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        slug = mode.replace(" ", "-").replace("+", "_").replace("/", "-")
        root = Path(results_root) if results_root else DEFAULT_ROOT
        self.session_dir = root / f"{ts}_{slug}"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self.mode    = mode
        self.notes   = notes
        self.config  = config or {}
        self.start_time = time.time()
        self.end_time   = None

        # Open all CSV writers
        self._open_csvs()

        # Loss/reacquisition state machine
        self._last_in_frame = False    # we start "off target" until first detection
        self._loss_start    = self.start_time

        # Running stats (also recomputable from CSVs offline)
        self._frame_count        = 0
        self._frames_in_target   = 0
        self._abs_pixel_errors   = []   # Euclidean distance from centre, in px
        self._loss_events        = []   # list of {"loss_start", "reacq", "latency_s"}
        self._alert_events       = []   # list of dicts (system_predicted, ground_truth)

        self._write_meta()
        print(f"[recorder] Session opened → {self.session_dir}")

    # Context-manager support so `with SessionRecorder(...) as rec:` works
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False    # don't suppress exceptions

    # ── Logging API (called from main loop) ────────────────────────────────

    def log_detection(self, surfer_cx, surfer_cy, frame_w, frame_h,
                      confidence=None, label="",
                      pan_deg=None, tilt_deg=None,
                      base_steps=None, hinge_steps=None):
        """A target WAS detected in this frame."""
        now = time.time()
        cx, cy = frame_w / 2.0, frame_h / 2.0
        err_x  = surfer_cx - cx
        err_y  = surfer_cy - cy
        err_m  = math.hypot(err_x, err_y)

        self._det_w.writerow([
            datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
            f"{now:.6f}",
            1, label, _csv_num(confidence),
            f"{surfer_cx:.2f}", f"{surfer_cy:.2f}", frame_w, frame_h,
            f"{err_x:.2f}", f"{err_y:.2f}", f"{err_m:.2f}",
            _csv_num(pan_deg), _csv_num(tilt_deg),
            _csv_num(base_steps), _csv_num(hinge_steps),
        ])

        self._frame_count      += 1
        self._frames_in_target += 1
        self._abs_pixel_errors.append(err_m)

        # If we were in a loss state, this detection closes it.
        if self._loss_start is not None:
            latency = now - self._loss_start
            self._loss_w.writerow([
                datetime.fromtimestamp(self._loss_start).isoformat(timespec="milliseconds"),
                f"{self._loss_start:.6f}",
                datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                f"{now:.6f}",
                f"{latency:.3f}",
            ])
            self._loss_events.append({
                "loss_start": self._loss_start,
                "reacq":      now,
                "latency_s":  latency,
            })
            self._loss_start = None

        self._last_in_frame = True

    def log_no_detection(self, frame_w, frame_h):
        """No target detected this frame."""
        now = time.time()
        self._det_w.writerow([
            datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
            f"{now:.6f}",
            0, "", "", "", "", frame_w, frame_h,
            "", "", "", "", "", "", "",
        ])

        self._frame_count += 1

        # Mark the start of a loss window on the transition
        if self._last_in_frame and self._loss_start is None:
            self._loss_start = now
        self._last_in_frame = False

    def log_alert(self, alert_type, system_predicted=True, ground_truth=None):
        """A system event was raised (e.g. 'prolonged_submersion').

        ground_truth may be None (unknown — fill in offline by editing
        alerts.csv), True (real event), or False (false alarm).
        """
        now = time.time()
        self._alert_w.writerow([
            datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
            f"{now:.6f}",
            alert_type,
            int(bool(system_predicted)),
            "" if ground_truth is None else int(bool(ground_truth)),
        ])
        self._alert_events.append({
            "time":             now,
            "alert_type":       alert_type,
            "system_predicted": bool(system_predicted),
            "ground_truth":     ground_truth,
        })

    def flush(self):
        """Force all CSVs to disk. Cheap — safe to call every frame."""
        self._det_f.flush()
        self._loss_f.flush()
        self._alert_f.flush()

    # ── Shutdown ───────────────────────────────────────────────────────────

    def close(self):
        """Finalise: close any open loss window, write summary.json, close files."""
        if self.end_time is not None:
            return    # already closed
        self.end_time = time.time()

        # If we ended in a loss state, record the dangling event as un-reacquired
        if self._loss_start is not None:
            self._loss_w.writerow([
                datetime.fromtimestamp(self._loss_start).isoformat(timespec="milliseconds"),
                f"{self._loss_start:.6f}",
                "", "", "",        # never reacquired before session end
            ])
            self._loss_start = None

        self._write_summary()
        self._det_f.close()
        self._loss_f.close()
        self._alert_f.close()
        print(f"[recorder] Session closed. Summary → {self.session_dir / 'summary.json'}")

    # ── Internals ──────────────────────────────────────────────────────────

    def _open_csvs(self):
        self._det_f = open(self.session_dir / "detections.csv", "w", newline="")
        self._det_w = csv.writer(self._det_f)
        self._det_w.writerow([
            "timestamp_iso", "epoch_s",
            "in_frame", "class", "confidence",
            "surfer_cx", "surfer_cy", "frame_w", "frame_h",
            "pixel_error_x", "pixel_error_y", "pixel_error_magnitude",
            "pan_deg", "tilt_deg", "base_steps", "hinge_steps",
        ])

        self._loss_f = open(self.session_dir / "loss_events.csv", "w", newline="")
        self._loss_w = csv.writer(self._loss_f)
        self._loss_w.writerow([
            "loss_iso", "loss_epoch_s",
            "reacq_iso", "reacq_epoch_s",
            "latency_s",
        ])

        self._alert_f = open(self.session_dir / "alerts.csv", "w", newline="")
        self._alert_w = csv.writer(self._alert_f)
        self._alert_w.writerow([
            "timestamp_iso", "epoch_s",
            "alert_type", "system_predicted", "ground_truth",
        ])

    def _write_meta(self):
        meta = {
            "mode":            self.mode,
            "notes":           self.notes,
            "config":          self.config,
            "start_iso":       datetime.fromtimestamp(self.start_time).isoformat(),
            "start_epoch_s":   self.start_time,
            "session_dir":     str(self.session_dir),
        }
        with open(self.session_dir / "session_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

    def _write_summary(self):
        duration = (self.end_time or time.time()) - self.start_time

        time_on_target_pct = (
            100.0 * self._frames_in_target / self._frame_count
            if self._frame_count > 0 else None
        )
        mean_abs_pixel_err = (
            sum(self._abs_pixel_errors) / len(self._abs_pixel_errors)
            if self._abs_pixel_errors else None
        )

        latencies = [e["latency_s"] for e in self._loss_events]
        if latencies:
            n = len(latencies)
            mean_lat = sum(latencies) / n
            sorted_l = sorted(latencies)
            median_lat = (sorted_l[n // 2] if n % 2 == 1
                          else (sorted_l[n // 2 - 1] + sorted_l[n // 2]) / 2)
            var_lat = sum((x - mean_lat) ** 2 for x in latencies) / n
            min_lat = sorted_l[0]
            max_lat = sorted_l[-1]
        else:
            mean_lat = median_lat = var_lat = min_lat = max_lat = None

        tp = sum(1 for e in self._alert_events
                 if e["system_predicted"] and e["ground_truth"] is True)
        fp = sum(1 for e in self._alert_events
                 if e["system_predicted"] and e["ground_truth"] is False)
        fn = sum(1 for e in self._alert_events
                 if not e["system_predicted"] and e["ground_truth"] is True)
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        recall    = tp / (tp + fn) if (tp + fn) > 0 else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision and recall else None)

        summary = {
            "duration_seconds":         duration,
            "frame_count":              self._frame_count,
            "frames_in_target":         self._frames_in_target,
            "time_on_target_pct":       time_on_target_pct,
            "mean_abs_pixel_error_px":  mean_abs_pixel_err,
            "reacquisition_latency_s": {
                "count":    len(latencies),
                "mean":     mean_lat,
                "median":   median_lat,
                "variance": var_lat,
                "min":      min_lat,
                "max":      max_lat,
            },
            "alerts": {
                "true_positives":   tp,
                "false_positives":  fp,
                "false_negatives":  fn,
                "precision":        precision,
                "recall":           recall,
                "f1":               f1,
                "note": ("Set ground_truth in alerts.csv (1=real event, 0=false "
                         "alarm) and re-run summary computation offline if you "
                         "annotate after the fact."),
            },
            "end_iso":     (datetime.fromtimestamp(self.end_time).isoformat()
                            if self.end_time else None),
            "end_epoch_s": self.end_time,
        }
        with open(self.session_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)


def _csv_num(x):
    """Format a number for CSV, blank if None."""
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{x:.4f}"
    return x
