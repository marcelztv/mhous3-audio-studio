"""All signal processing for MHous3 Audio Studio - pure numpy/scipy, fully offline.

Arrays are float32/float64 shaped (samples, channels).  Internal sample rate is 48 kHz.
"""
import numpy as np
from scipy import signal
from scipy.interpolate import CubicSpline
from scipy.ndimage import minimum_filter1d, uniform_filter1d

SR = 48000


def db2lin(x):
    return 10.0 ** (np.asarray(x, dtype=np.float64) / 20.0)


def lin2db(x):
    return 20.0 * np.log10(np.maximum(x, 1e-12))


def _2d(x):
    x = np.asarray(x)
    return x[:, None] if x.ndim == 1 else x


# --------------------------------------------------------------------------- filters
def biquad(kind, f, sr=SR, q=0.707, gain=0.0):
    """RBJ cookbook biquad -> one SOS row."""
    f = float(np.clip(f, 10, sr * 0.45))
    w0 = 2 * np.pi * f / sr
    A = 10 ** (gain / 40.0)
    cw, alpha = np.cos(w0), np.sin(w0) / (2 * max(q, 0.05))
    if kind == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * np.sqrt(A) * alpha
        if kind == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    elif kind == "highpass":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lowpass":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "notch":
        b = [1, -2 * cw, 1]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(kind)
    return np.r_[b, a] / a[0]


def apply_sos(x, sos):
    sos = np.atleast_2d(sos)
    return signal.sosfilt(sos, _2d(x), axis=0).astype(np.float32)


def butter_sos(kind, f, order=4, sr=SR):
    return signal.butter(order, f, kind, fs=sr, output="sos")


def highpass(x, f, sr=SR, order=4):
    return apply_sos(x, butter_sos("highpass", f, order, sr)) if f and f > 0 else _2d(x)


def lowpass(x, f, sr=SR, order=4):
    return apply_sos(x, butter_sos("lowpass", f, order, sr)) if f and f > 0 else _2d(x)


def remove_hum(x, base_hz, sr=SR, harmonics=6, q=35):
    rows = [biquad("notch", base_hz * k, sr, q) for k in range(1, harmonics + 1) if base_hz * k < sr * 0.45]
    return apply_sos(x, np.array(rows)) if rows else _2d(x)


def parametric_eq(x, bands, sr=SR):
    """bands: list of (kind, freq, gain_db, q).  Zero-gain bands are skipped."""
    rows = [biquad(k, f, sr, q, g) for k, f, g, q in bands if abs(g) > 0.05]
    return apply_sos(x, np.array(rows)) if rows else _2d(x)


# --------------------------------------------------------------------------- dynamics
def _hop_levels(x, hop):
    """RMS level (dB) per hop, linked across channels."""
    n = len(x) // hop
    if n == 0:
        return np.array([-120.0]), 1
    b = x[: n * hop].astype(np.float64)
    ms = np.mean(b.reshape(n, hop, -1) ** 2, axis=(1, 2))
    return 10 * np.log10(ms + 1e-12), n


def _smooth(target, up_ms, down_ms, hop_ms):
    """Asymmetric one-pole smoothing: separate time constants for rising/falling values."""
    cu = np.exp(-hop_ms / max(up_ms, 0.01))
    cd = np.exp(-hop_ms / max(down_ms, 0.01))
    out = np.empty_like(target)
    s = 0.0
    for i, g in enumerate(target):
        c = cu if g > s else cd
        s = c * s + (1 - c) * g
        out[i] = s
    return out


def _apply_hop_gain(x, gain_db, hop):
    n = len(x)
    centers = (np.arange(len(gain_db)) + 0.5) * hop
    g = np.interp(np.arange(n), centers, db2lin(-gain_db))
    return x * g[:, None].astype(np.float32)


def compressor(x, sr, thr_db, ratio, attack_ms, release_ms, knee_db=6.0, makeup_db=0.0, mix=1.0):
    x = _2d(x)
    hop = max(1, int(sr * 0.001))
    lvl, n = _hop_levels(x, hop)
    over = lvl - thr_db
    ratio = max(ratio, 1.0)
    k = max(knee_db, 1e-6)
    gr = np.where(2 * over < -k, 0.0,
                  np.where(2 * np.abs(over) <= k, (1 - 1 / ratio) * (over + k / 2) ** 2 / (2 * k),
                           (1 - 1 / ratio) * over))
    gr = _smooth(gr, attack_ms, release_ms, 1.0)
    y = _apply_hop_gain(x, gr, hop) * float(db2lin(makeup_db))
    return (1 - mix) * x + mix * y if mix < 1 else y


def expander(x, sr, thr_db, ratio, range_db, attack_ms, release_ms):
    """Downward expander / gate.  `range_db` is the max attenuation (negative number)."""
    x = _2d(x)
    hop = max(1, int(sr * 0.001))
    lvl, n = _hop_levels(x, hop)
    gr = np.clip((thr_db - lvl) * (ratio - 1), 0, abs(range_db))
    gr = _smooth(gr, release_ms, attack_ms, 1.0)  # reduction ramps in slowly, out fast
    return _apply_hop_gain(x, gr, hop)


def deesser(x, sr, freq, thr_db, ratio):
    x = _2d(x)
    lo, hi = max(freq * 0.7, 2000), min(freq * 1.5, sr * 0.45)
    sos = signal.butter(2, [lo, hi], "bandpass", fs=sr, output="sos")
    band = apply_sos(x, sos)
    hop = max(1, int(sr * 0.001))
    lvl, n = _hop_levels(band, hop)
    gr = np.maximum(lvl - thr_db, 0) * (1 - 1 / max(ratio, 1.0))
    gr = _smooth(gr, 1.0, 40.0, 1.0)
    reduced = _apply_hop_gain(band, gr, hop)
    return (x - band + reduced).astype(np.float32)


def saturate(x, drive=2.0, mix=0.3, bias=0.08):
    x = _2d(x)
    d = max(drive, 0.1)
    y = np.tanh(d * x + bias) - np.tanh(bias)
    y = y / np.tanh(d)
    return ((1 - mix) * x + mix * y).astype(np.float32)


def limiter(x, sr, ceiling_db=-1.0, lookahead_ms=6.0):
    """Look-ahead peak limiter.  Mathematically guarantees |y| <= ceiling (sample peak)."""
    x = _2d(x)
    c = float(db2lin(ceiling_db))
    peak = np.max(np.abs(x), axis=1)
    if peak.max() <= c:
        return x
    g = np.minimum(1.0, c / np.maximum(peak, 1e-9))
    la = max(2, int(sr * lookahead_ms / 1000))
    g = minimum_filter1d(g, size=2 * la + 1, mode="nearest")
    g = uniform_filter1d(g, size=la + 1, mode="nearest")
    return (x * g[:, None]).astype(np.float32)


def true_peak_db(x, sr=SR):
    x = _2d(x)
    up = signal.resample_poly(x, 4, 1, axis=0)
    return float(lin2db(np.max(np.abs(up)))) if up.size else -120.0


# --------------------------------------------------------------------------- loudness (ITU-R BS.1770-4)
_K1 = np.array([1.0, -1.69065929318241, 0.73248077421585])
_K1B = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
_K2 = np.array([1.0, -1.99004745483398, 0.99007225036621])
_K2B = np.array([1.0, -2.0, 1.0])
_K_SOS = np.array([np.r_[_K1B, _K1], np.r_[_K2B, _K2]])


def integrated_lufs(x, weights=None):
    x = _2d(x).astype(np.float64)
    n, ch = x.shape
    w = np.ones(ch) if weights is None else np.asarray(weights, dtype=np.float64)
    kw = signal.sosfilt(_K_SOS, x, axis=0)
    block, step = int(0.4 * SR), int(0.1 * SR)
    if n < block:
        kw = np.pad(kw, ((0, block - n), (0, 0)))
        n = block
    cs = np.vstack([np.zeros((1, ch)), np.cumsum(kw ** 2, axis=0)])
    starts = np.arange(0, n - block + 1, step)
    ms = (cs[starts + block] - cs[starts]) / block
    z = (ms * w).sum(axis=1)
    l = -0.691 + 10 * np.log10(z + 1e-15)
    keep = l > -70
    if not keep.any():
        return -np.inf
    rel = -0.691 + 10 * np.log10(z[keep].mean()) - 10
    keep = l > max(rel, -70)
    return float(-0.691 + 10 * np.log10(z[keep].mean())) if keep.any() else -np.inf


def normalize_loudness(x, target_lufs, ceiling_db, weights=None, sr=SR):
    """Gain to target integrated loudness, with look-ahead limiter and true-peak guard."""
    x = _2d(x)
    cur = integrated_lufs(x, weights)
    if not np.isfinite(cur):
        return limiter(x, sr, ceiling_db), cur
    total = target_lufs - cur
    y = x
    for _ in range(5):
        y = limiter(x * float(db2lin(total)), sr, ceiling_db)
        new = integrated_lufs(y, weights)
        if not np.isfinite(new) or abs(new - target_lufs) < 0.2:
            break
        total += target_lufs - new
    tp = true_peak_db(y, sr)
    if tp > ceiling_db + 0.05:
        y = limiter(y, sr, ceiling_db - (tp - ceiling_db) - 0.1)
    return y.astype(np.float32), cur


# --------------------------------------------------------------------------- repair
def declip(x, max_run=64, ctx=6):
    """Cubic-spline reconstruction of clipped peaks.  Returns (audio, runs_fixed, clipped_fraction)."""
    x = _2d(x).astype(np.float32).copy()
    fixed, clipped = 0, 0
    for c in range(x.shape[1]):
        v = x[:, c]
        peak = np.max(np.abs(v))
        if peak < 0.05:
            continue
        thr = peak * 0.995
        mask = np.abs(v) >= thr
        clipped += int(mask.sum())
        if mask.sum() < 3:
            continue
        d = np.diff(np.r_[0, mask.view(np.int8), 0])
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        for s, e in zip(starts, ends):
            ln = e - s
            if ln < 2 or ln > max_run or s < ctx or e + ctx >= len(v):
                continue
            idx = np.r_[np.arange(s - ctx, s), np.arange(e, e + ctx)]
            try:
                cs = CubicSpline(idx, v[idx])
            except ValueError:
                continue
            seg = cs(np.arange(s, e))
            sign = 1.0 if v[s:e].mean() > 0 else -1.0
            v[s:e] = sign * np.maximum(np.abs(seg), thr)
            fixed += 1
    return x, fixed, clipped / max(x.size, 1)


# --------------------------------------------------------------------------- spectral tools
_NFFT, _HOP = 2048, 512


def _stft(x):
    _, _, Z = signal.stft(x, SR, nperseg=_NFFT, noverlap=_NFFT - _HOP, boundary="zeros", padded=True)
    return Z


def _istft(Z, n):
    _, y = signal.istft(Z, SR, nperseg=_NFFT, noverlap=_NFFT - _HOP, boundary=True)
    y = y[:n]
    return np.pad(y, (0, n - len(y))) if len(y) < n else y


def _smooth_gain(G, f_bins=3, t_frames=3):
    G = uniform_filter1d(G, size=f_bins, axis=0, mode="nearest")
    return uniform_filter1d(G, size=t_frames, axis=1, mode="nearest")


def spectral_denoise(x, amount_db=20.0, sensitivity=2.0):
    """Built-in noise reduction: minimum-statistics noise floor + smoothed Wiener-style gain."""
    x = _2d(x)
    n = len(x)
    Zs = [_stft(x[:, c]) for c in range(x.shape[1])]
    P = np.mean([np.abs(Z) ** 2 for Z in Zs], axis=0)
    Ps = uniform_filter1d(P, size=7, axis=1, mode="nearest")
    noise = np.percentile(Ps, 10, axis=1)[:, None] * sensitivity
    gmin = float(db2lin(-amount_db))
    G = np.maximum(gmin, 1.0 - noise / np.maximum(P, 1e-14))
    G = np.clip(_smooth_gain(G, 3, 3), gmin, 1.0)
    out = np.stack([_istft(Z * G, n) for Z in Zs], axis=1)
    return out.astype(np.float32)


def dereverb(x, strength=0.5, rt60=0.6):
    """Late-reverberation suppression by spectral subtraction (Habets-style late-reverb PSD model)."""
    x = _2d(x)
    n = len(x)
    Zs = [_stft(x[:, c]) for c in range(x.shape[1])]
    P = np.mean([np.abs(Z) ** 2 for Z in Zs], axis=0)
    T = _HOP / SR
    D = max(2, int(round(0.05 / T)))                 # 50 ms: boundary between early and late reflections
    delta = 3 * np.log(10) / max(rt60, 0.1)
    decay = np.exp(-2 * delta * D * T)
    Ps = uniform_filter1d(P, size=3, axis=1, mode="nearest")
    late = np.zeros_like(P)
    late[:, D:] = decay * Ps[:, :-D]
    beta = 0.6 + 2.4 * float(strength)
    gmin = float(db2lin(-6 - 18 * float(strength)))
    G = np.sqrt(np.maximum(1.0 - beta * late / np.maximum(P, 1e-14), gmin ** 2))
    G = np.clip(_smooth_gain(G, 3, 3), gmin, 1.0)
    out = np.stack([_istft(Z * G, n) for Z in Zs], axis=1)
    return out.astype(np.float32)


# --------------------------------------------------------------------------- reverb
# name: (rt60 s, size 0-1, predelay ms, damping 0-1)
REVERB_TYPES = {
    "Small Room": (0.35, 0.15, 4, 0.55),
    "Studio Booth": (0.2, 0.05, 2, 0.7),
    "Dialogue Room": (0.5, 0.25, 8, 0.6),
    "Cinema Hall": (1.1, 0.55, 18, 0.5),
    "Concert Hall": (1.9, 0.8, 28, 0.4),
    "Large Stage": (1.4, 0.7, 22, 0.45),
    "Plate": (1.6, 0.3, 0, 0.3),
    "Cathedral": (4.5, 1.0, 40, 0.35),
    "Cave / Tunnel": (3.2, 0.9, 30, 0.6),
    "Warehouse": (2.4, 0.85, 25, 0.55),
}


def make_ir(rt60, size, predelay_ms, damping, seed=0, sr=SR):
    rng = np.random.default_rng(seed)
    length = int(sr * min(rt60 * 1.1 + 0.2, 6.0))
    t = np.arange(length) / sr
    noise = rng.standard_normal(length)
    bands = [(None, 400, 1.25), (400, 4000, 1.0), (4000, None, max(0.15, 1.0 - 0.85 * damping))]
    late = np.zeros(length)
    for lo, hi, mult in bands:
        if lo is None:
            sos = butter_sos("lowpass", hi, 2, sr)
        elif hi is None:
            sos = butter_sos("highpass", lo, 2, sr)
        else:
            sos = signal.butter(2, [lo, hi], "bandpass", fs=sr, output="sos")
        late += signal.sosfilt(sos, noise) * np.exp(-6.9078 * t / (rt60 * mult))
    late *= 1 - np.exp(-t / (0.008 + 0.04 * size))                   # build-up of diffuse field
    er = np.zeros(length)
    n_tap = int(8 + 14 * size)
    times = np.sort(rng.uniform(0.004, 0.012 + 0.09 * size, n_tap))
    for tt in times:
        k = int(tt * sr)
        if k < length:
            er[k] += rng.choice([-1, 1]) * np.exp(-3.0 * tt / max(0.05, size * 0.3 + 0.05)) * 0.9
    er = signal.sosfilt(butter_sos("lowpass", 7500 - 3000 * damping, 2, sr), er)
    ir = late / (np.sqrt(np.sum(late ** 2)) + 1e-9) * 0.85 + er / (np.sqrt(np.sum(er ** 2)) + 1e-9) * 0.35
    ir = np.r_[np.zeros(int(predelay_ms * sr / 1000)), ir]
    return (ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9)).astype(np.float32)


def reverb_wet(mono, kind="Cinema Hall", seed=0, rt60=None, predelay=None, damping=None, lowcut=180, highcut=8000):
    """Return the wet-only reverb signal (n,) for a mono input, using impulse response #seed."""
    r, size, pd, damp = REVERB_TYPES.get(kind, REVERB_TYPES["Cinema Hall"])
    ir = make_ir(r if not rt60 else rt60, size, pd if predelay is None else predelay,
                 damp if damping is None else damping, seed)
    wet = signal.oaconvolve(mono.astype(np.float32), ir, mode="full")[: len(mono)]
    if lowcut and lowcut > 0:
        wet = signal.sosfilt(butter_sos("highpass", lowcut, 2), wet)
    if highcut and highcut > 0:
        wet = signal.sosfilt(butter_sos("lowpass", highcut, 2), wet)
    return wet.astype(np.float32)


# --------------------------------------------------------------------------- channel layouts
def downmix_mono(x):
    return _2d(x).mean(axis=1, keepdims=True).astype(np.float32)


def upmix_51(dry, wet_front, wet_surr, center=0.8, surround=0.6, lfe=0.0):
    """Dialogue-centred 5.1 from mono/stereo.  Order: L R C LFE Ls Rs.  wet_* are (n,2) reverb returns."""
    dry = _2d(dry)
    L = dry[:, 0]
    R = dry[:, -1]
    m = 0.5 * (L + R)
    s = 0.5 * (L - R)
    C = m * center
    Lf = L - 0.5 * C + wet_front[:, 0]
    Rf = R - 0.5 * C + wet_front[:, 1]
    delay = int(0.015 * SR)
    sd = np.r_[np.zeros(delay), s][: len(s)] * surround * 0.7
    sd = signal.sosfilt(butter_sos("lowpass", 8000, 2), sd)
    Ls = sd + wet_surr[:, 0] * surround
    Rs = -sd + wet_surr[:, 1] * surround
    LFE = signal.sosfilt(butter_sos("lowpass", 110, 4), m) * lfe
    return np.stack([Lf, Rf, C, LFE, Ls, Rs], axis=1).astype(np.float32)


def lt_rt_encode(x51):
    """Dolby Surround-style matrix (Lt/Rt) from 5.1."""
    L, R, C, _, Ls, Rs = [x51[:, i] for i in range(6)]
    s = np.imag(signal.hilbert(0.7071 * (Ls + Rs)))
    Lt = L + 0.7071 * C - s
    Rt = R + 0.7071 * C + s
    return (np.stack([Lt, Rt], axis=1) / 1.4).astype(np.float32)


def downmix_to_stereo(x):
    x = _2d(x)
    if x.shape[1] == 1:
        return np.repeat(x, 2, axis=1)
    if x.shape[1] == 2:
        return x
    if x.shape[1] >= 6:
        L, R, C, _, Ls, Rs = [x[:, i] for i in range(6)]
        return (np.stack([L + 0.7071 * C + 0.7071 * Ls, R + 0.7071 * C + 0.7071 * Rs], axis=1) / 1.7).astype(np.float32)
    return x[:, :2]
