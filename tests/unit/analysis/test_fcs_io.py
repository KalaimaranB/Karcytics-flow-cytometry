"""Unit tests for fcs_io.py.

Covers the tolerant binary-read fallback in `_load_with_fcsparser` — the
plugin's core value is scientific correctness on real (often messy)
instrument output, so this exercises truncated files, mixed/non-float
DATA segments, and malformed headers using small synthetic FCS3.1 files
built by `_write_minimal_fcs` below (no dependency on the large real
sample files under `tests/data/fcs/`).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from karcytics_plugins.flow_cytometry.analysis.fcs_io import (
    FCSData,
    _auto_apply_spill,
    _build_fcs_data_from_daemon_response,
    _has_embedded_spill,
    _load_with_fcsparser,
    get_channel_marker_label,
    get_fluorescence_channels,
    load_fcs,
)


def _write_minimal_fcs(
    path: Path,
    data: np.ndarray,
    channels: list[str],
    *,
    datatype: str = "F",
    bits: int = 32,
    byte_order: str = "1,2,3,4",
    tot_override: int | None = None,
    par_override: int | None = None,
    pnb_overrides: dict[int, int] | None = None,
    extra_text: dict[str, str] | None = None,
    truncate_data_bytes: int = 0,
) -> None:
    """Write a minimal, spec-compliant FCS3.1 file for testing the tolerant reader.

    Builds a real HEADER + TEXT + DATA layout that `fcsparser` can parse,
    so tests exercise the actual binary-reading logic in `fcs_io.py`
    rather than mocked stand-ins.
    """
    n_events, n_params = data.shape
    assert n_params == len(channels)
    pnb_overrides = pnb_overrides or {}
    extra_text = extra_text or {}

    endian_prefix = "<" if byte_order.startswith("1") else ">"
    kind = {"F": "f", "D": "f", "I": "u"}[datatype]
    np_dtype = np.dtype(f"{endian_prefix}{kind}{bits // 8}")

    body = data.astype(np_dtype).tobytes()
    if truncate_data_bytes:
        body = body[: len(body) - truncate_data_bytes]

    delim = "/"
    text_start = 58  # fixed HEADER size

    keywords = {
        "$BYTEORD": byte_order,
        "$DATATYPE": datatype,
        "$MODE": "L",
        "$NEXTDATA": "0",
        "$PAR": str(par_override if par_override is not None else n_params),
        "$TOT": str(tot_override if tot_override is not None else n_events),
    }
    for i, ch in enumerate(channels, start=1):
        keywords[f"$P{i}N"] = ch
        keywords[f"$P{i}B"] = str(pnb_overrides.get(i, bits))
        keywords[f"$P{i}E"] = "0,0"
        keywords[f"$P{i}R"] = "262144"
    keywords.update(extra_text)

    def build_text(data_start: int, data_end: int) -> str:
        kw = dict(keywords)
        kw["$BEGINDATA"] = str(data_start)
        kw["$ENDDATA"] = str(data_end)
        pairs = [item for kv in kw.items() for item in kv]
        return delim + delim.join(pairs) + delim

    text_guess = build_text(0, 0)
    data_start = text_start + len(text_guess)
    data_end = data_start + len(body) - 1
    text = build_text(data_start, data_end)
    if len(text) != len(text_guess):
        # Offsets picked up an extra digit — rebuild once more with the new length.
        data_start = text_start + len(text)
        data_end = data_start + len(body) - 1
        text = build_text(data_start, data_end)

    def offset_field(n: int) -> str:
        return str(n).rjust(8)

    header = (
        "FCS3.1".ljust(6)
        + " " * 4
        + offset_field(text_start)
        + offset_field(text_start + len(text) - 1)
        + offset_field(data_start)
        + offset_field(data_end)
        + offset_field(0)
        + offset_field(0)
    )
    assert len(header) == 58

    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(text.encode("ascii"))
        f.write(body)


def _rng_events(n: int, channels: list[str], *, low=1000.0, high=50000.0, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(low, high, size=(n, len(channels)))


# ── FCSData / basic dataclass ────────────────────────────────────────────────


def test_fcs_data_dataclass():
    data = FCSData(
        file_path=Path("sample.fcs"),
        channels=["FSC-A", "SSC-A"],
        markers=["", ""],
        events=pd.DataFrame([[100.0, 200.0]], columns=["FSC-A", "SSC-A"]),
        raw_events=pd.DataFrame([[100.0, 200.0]], columns=["FSC-A", "SSC-A"]),
    )
    assert data.num_events == 1
    assert data.num_channels == 2


def test_load_fcs_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_fcs("non_existent_file.fcs")


# ── _auto_apply_spill ─────────────────────────────────────────────────────────


def test_auto_apply_spill():
    events_df = pd.DataFrame([[1000.0, 500.0]], columns=["FL1-A", "FL2-A"])
    metadata = {"$SPILLOVER": "2,FL1-A,FL2-A,1.0,0.1,0.05,1.0"}
    applied = _auto_apply_spill("sample.fcs", events_df, metadata)
    assert applied is True
    assert events_df.shape == (1, 2)


def test_auto_apply_spill_no_spill_key_is_noop():
    events_df = pd.DataFrame([[1000.0, 500.0]], columns=["FL1-A", "FL2-A"])
    original = events_df.copy()
    applied = _auto_apply_spill("sample.fcs", events_df, {})
    assert applied is False
    pd.testing.assert_frame_equal(events_df, original)


def test_auto_apply_spill_malformed_value_count_returns_false():
    events_df = pd.DataFrame([[1000.0, 500.0]], columns=["FL1-A", "FL2-A"])
    original = events_df.copy()
    # Header claims a 2x2 matrix (4 values) but only 2 are provided.
    metadata = {"$SPILLOVER": "2,FL1-A,FL2-A,1.0,0.1"}
    applied = _auto_apply_spill("sample.fcs", events_df, metadata)
    assert applied is False
    pd.testing.assert_frame_equal(events_df, original)


def test_auto_apply_spill_channels_not_in_dataframe_returns_false():
    events_df = pd.DataFrame([[1000.0, 500.0]], columns=["FL3-A", "FL4-A"])
    original = events_df.copy()
    metadata = {"$SPILLOVER": "2,FL1-A,FL2-A,1.0,0.1,0.05,1.0"}
    applied = _auto_apply_spill("sample.fcs", events_df, metadata)
    assert applied is False
    pd.testing.assert_frame_equal(events_df, original)


# ── _load_with_fcsparser: happy path ─────────────────────────────────────────


def test_load_with_fcsparser_happy_path(tmp_path):
    channels = ["FSC-A", "SSC-A", "FITC-A"]
    data = _rng_events(20, channels)
    path = tmp_path / "sample.fcs"
    _write_minimal_fcs(path, data, channels)

    result = _load_with_fcsparser(path)

    assert result.channels == channels
    assert result.num_events == 20
    np.testing.assert_allclose(result.events[channels].values, data, rtol=1e-5)


def test_has_embedded_spill_true_for_every_known_key_variant():
    for key in ("$SPILLOVER", "$SPILL", "SPILLOVER", "SPILL", "spill", "spillover"):
        assert _has_embedded_spill({key: "2,FL1-A,FL2-A,1.0,0.1,0.05,1.0"})


def test_has_embedded_spill_false_when_absent():
    assert _has_embedded_spill({}) is False
    assert _has_embedded_spill({"$TOT": "20"}) is False


def test_load_with_fcsparser_shares_raw_events_with_events_when_no_spill_key(tmp_path):
    """Priority 1 analysis #4 — no embedded spillover matrix means nothing
    ever mutates `events_df`, so `raw_events` sharing the same object as
    `events` is exactly equivalent to copying it, at zero cost.
    """
    channels = ["FSC-A", "SSC-A", "FITC-A"]
    data = _rng_events(20, channels)
    path = tmp_path / "sample.fcs"
    _write_minimal_fcs(path, data, channels)

    result = _load_with_fcsparser(path)

    assert result.raw_events is result.events


def _encode_array(arr: np.ndarray) -> str:
    import base64
    import io

    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_daemon_response_shares_raw_events_with_events_when_no_spill_key():
    channels = ["FSC-A", "SSC-A"]
    data = _rng_events(10, channels)
    res = {
        "channels": channels,
        "markers": ["", ""],
        "metadata": {},
        "events_b64": _encode_array(data),
    }

    result = _build_fcs_data_from_daemon_response(Path("sample.fcs"), res)

    assert result.raw_events is result.events


def test_daemon_response_copies_raw_events_when_spill_key_present():
    channels = ["FL1-A", "FL2-A"]
    data = np.array([[1000.0, 500.0]] * 5)
    res = {
        "channels": channels,
        "markers": ["", ""],
        "metadata": {"$SPILLOVER": "2,FL1-A,FL2-A,1.0,0.1,0.05,1.0"},
        "events_b64": _encode_array(data),
    }

    result = _build_fcs_data_from_daemon_response(Path("sample.fcs"), res)

    assert result.raw_events is not result.events
    np.testing.assert_allclose(result.raw_events[channels].values, data, rtol=1e-5)
    assert not np.allclose(result.events[channels].values, result.raw_events[channels].values)


def test_load_with_fcsparser_copies_raw_events_when_spill_key_present(tmp_path):
    """An embedded spillover matrix does mutate `events_df` in place
    (`_auto_apply_spill`), so `raw_events` must still be an independent
    copy preserving the pre-compensation values in this case.
    """
    channels = ["FL1-A", "FL2-A"]
    data = np.array([[1000.0, 500.0]] * 5)
    path = tmp_path / "sample.fcs"
    _write_minimal_fcs(
        path,
        data,
        channels,
        extra_text={"$SPILLOVER": "2,FL1-A,FL2-A,1.0,0.1,0.05,1.0"},
    )

    result = _load_with_fcsparser(path)

    assert result.raw_events is not result.events
    np.testing.assert_allclose(result.raw_events[channels].values, data, rtol=1e-5)
    assert not np.allclose(result.events[channels].values, result.raw_events[channels].values)


# ── _load_with_fcsparser: tolerant binary-read fallback ──────────────────────


def test_load_with_fcsparser_recovers_partial_events_from_truncated_file(tmp_path):
    channels = ["FSC-A", "SSC-A", "FITC-A"]
    n = 100
    data = _rng_events(n, channels)
    path = tmp_path / "truncated.fcs"
    bytes_per_event = 4 * len(channels)
    # Drop 10 full events' worth of bytes so the header's $TOT overclaims.
    _write_minimal_fcs(path, data, channels, truncate_data_bytes=10 * bytes_per_event)

    result = _load_with_fcsparser(path)

    assert result.channels == channels
    assert result.num_events == n - 10
    np.testing.assert_allclose(result.events[channels].values, data[: n - 10], rtol=1e-5)


def test_load_with_fcsparser_strips_non_finite_and_below_threshold_events(tmp_path):
    channels = ["FSC-A", "SSC-A", "FITC-A"]
    n = 50
    data = _rng_events(n, channels)
    # Plant two garbage events inside the range that will survive truncation:
    # one non-finite, one with an implausibly low (denormal-artefact) FSC-A.
    data[5] = [np.nan, 100.0, 100.0]
    data[10] = [0.5, 100.0, 100.0]
    path = tmp_path / "garbage.fcs"
    bytes_per_event = 4 * len(channels)
    _write_minimal_fcs(path, data, channels, truncate_data_bytes=2 * bytes_per_event)

    result = _load_with_fcsparser(path)

    # n - 2 (truncated) - 2 (garbage) = 46 surviving events.
    assert result.num_events == n - 2 - 2
    assert result.events["FSC-A"].isna().sum() == 0
    assert (result.events["FSC-A"] >= 1.0).all()


def test_load_with_fcsparser_reports_diagnostics_when_strip_ratio_high(tmp_path, monkeypatch):
    from karcytics_sdk.plugin.runtime_services import diagnostics

    channels = ["FSC-A", "SSC-A"]
    n = 100
    data = _rng_events(n, channels)
    path = tmp_path / "mostly_truncated.fcs"
    bytes_per_event = 4 * len(channels)
    # Drop more than FCS_STRIP_RATIO_WARN (5%) of claimed events.
    _write_minimal_fcs(path, data, channels, truncate_data_bytes=20 * bytes_per_event)

    reported: list[str] = []
    monkeypatch.setattr(diagnostics, "report_error", lambda msg, fatal=False: reported.append(msg))

    result = _load_with_fcsparser(path)

    assert result.num_events == n - 20
    assert len(reported) == 1
    assert "truncated or corrupted" in reported[0]


def test_load_with_fcsparser_integer_datatype_recovered_correctly(tmp_path):
    channels = ["FSC-A", "SSC-A"]
    n = 30
    data = np.random.default_rng(1).integers(0, 60000, size=(n, len(channels))).astype(np.float64)
    path = tmp_path / "integer.fcs"
    bytes_per_event = 2 * len(channels)  # 16-bit ints
    _write_minimal_fcs(
        path,
        data,
        channels,
        datatype="I",
        bits=16,
        truncate_data_bytes=3 * bytes_per_event,
    )

    result = _load_with_fcsparser(path)

    assert result.num_events == n - 3
    np.testing.assert_allclose(result.events[channels].values, data[: n - 3])


def test_load_with_fcsparser_mixed_pnb_bit_widths_logs_warning(tmp_path, monkeypatch):
    import fcsparser

    channels = ["FSC-A", "SSC-A"]
    n = 20
    # All channels physically stored at 32 bits so the file layout is valid,
    # but the header advertises mismatched $PnB — the reader should warn and
    # fall back to the widest declared width rather than silently misalign.
    data = _rng_events(n, channels)
    path = tmp_path / "mixed_bits.fcs"
    _write_minimal_fcs(path, data, channels, pnb_overrides={1: 16, 2: 32})

    # Force entry into the tolerant-reader fallback deterministically — whether
    # the standard fcsparser parse happens to choke on a given $PnB mismatch is
    # a fcsparser-internal implementation detail we don't want this test to
    # depend on; what we're testing is the fallback's own handling of it.
    real_parse = fcsparser.parse

    def parse_that_fails_on_standard_call(*args, **kwargs):
        if kwargs.get("reformat_meta"):
            raise ValueError("forced failure to exercise the tolerant fallback")
        return real_parse(*args, **kwargs)

    monkeypatch.setattr(fcsparser, "parse", parse_that_fails_on_standard_call)

    warnings: list[str] = []
    import karcytics_plugins.flow_cytometry.analysis.fcs_io as fcs_io_module

    monkeypatch.setattr(
        fcs_io_module.logger,
        "warning",
        lambda msg, *a, **kw: warnings.append(msg % a if a else msg),
    )

    result = _load_with_fcsparser(path)

    assert any("Mixed $PnB bit-widths" in w for w in warnings)
    assert result.num_events == n


def test_load_with_fcsparser_zero_params_raises_runtime_error(tmp_path):
    channels = ["FSC-A", "SSC-A"]
    data = _rng_events(10, channels)
    path = tmp_path / "zero_par.fcs"
    _write_minimal_fcs(path, data, channels, par_override=0)

    with pytest.raises(RuntimeError, match="0 parameters"):
        _load_with_fcsparser(path)


def test_load_with_fcsparser_insufficient_bytes_for_one_event_raises(tmp_path):
    channels = ["FSC-A", "SSC-A", "FITC-A"]
    n = 5
    data = _rng_events(n, channels)
    path = tmp_path / "empty_after_truncation.fcs"
    bytes_per_event = 4 * len(channels)
    # Leave less than one whole event's worth of bytes.
    _write_minimal_fcs(
        path, data, channels, truncate_data_bytes=n * bytes_per_event - (bytes_per_event - 1)
    )

    with pytest.raises(RuntimeError, match="Cannot recover usable events"):
        _load_with_fcsparser(path)


def test_load_with_fcsparser_big_endian_byte_order(tmp_path):
    channels = ["FSC-A", "SSC-A"]
    n = 15
    data = _rng_events(n, channels)
    path = tmp_path / "big_endian.fcs"
    bytes_per_event = 4 * len(channels)
    _write_minimal_fcs(
        path,
        data,
        channels,
        byte_order="4,3,2,1",
        truncate_data_bytes=2 * bytes_per_event,
    )

    result = _load_with_fcsparser(path)

    assert result.num_events == n - 2
    np.testing.assert_allclose(result.events[channels].values, data[: n - 2], rtol=1e-5)


# ── get_fluorescence_channels / get_channel_marker_label ─────────────────────


def test_get_fluorescence_channels_excludes_scatter_and_time():
    data = FCSData(
        file_path=Path("sample.fcs"),
        channels=["FSC-A", "SSC-A", "FITC-A", "PE-A", "Time"],
        markers=[],
    )
    assert get_fluorescence_channels(data) == ["FITC-A", "PE-A"]


def test_get_channel_marker_label_with_and_without_marker():
    data = FCSData(
        file_path=Path("sample.fcs"),
        channels=["FSC-A", "FITC-A"],
        markers=["", "CD4"],
    )
    assert get_channel_marker_label(data, "FSC-A") == "FSC-A"
    assert get_channel_marker_label(data, "FITC-A") == "CD4 (FITC-A)"
    assert get_channel_marker_label(data, "NOT-A-CHANNEL") == "NOT-A-CHANNEL"
