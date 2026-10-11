# MHous3 Audio Studio

Free, offline audio rescue and cinema-style finishing for Windows. Everything (ffmpeg + DeepFilterNet AI denoiser) is bundled in one installer. No accounts, no cloud, no paid parts.

## Get the installer (.exe) - one-time, free, ~10 minutes, no coding

### Option A - GitHub builds it for you (easiest, nothing to install)
1. Create a free account at github.com, click **New repository** (name it e.g. `mhous3`, **Public**).
2. On the new repo page click **uploading an existing file**, drag in EVERYTHING from this folder
   (keep the folder structure, including the hidden `.github` folder), click **Commit changes**.
   Tip: easier is `Add file > Upload files` with the unzipped folder's contents, or use GitHub Desktop.
3. Open the **Actions** tab > **Build Windows installer** > **Run workflow**.
4. After ~10-15 minutes open the finished run and download **MHous3-Audio-Studio-Setup** (a zip with the installer .exe).
5. Double-click the installer. Done - it installs like any normal app.

### Option B - build on your own Windows PC
Install Python 3.11+ and Inno Setup 6 (both free), then double-click `build_windows.bat`.
The installer appears in `installer_output\`.

Windows may show "unknown publisher" (the installer isn't code-signed, which costs money). Click **More info > Run anyway**.

## What it does
* Camera-mic / clipped-recorder rescue: declipping, hum removal, AI + built-in noise reduction, de-reverb
* Cinema finishing: voice EQ, gate/expander, de-esser, compressor, parallel compression, saturation, 10 reverb rooms
* Output: Mono, Stereo, Dolby Surround (Lt/Rt), Dolby Digital 5.1 (AC-3 / E-AC-3), WAV/FLAC/MP3/AAC, or MP4/MKV video with the new audio
* LUFS loudness matching (-27 / -24 / -23 / -16 / -14 / custom) + look-ahead limiter and true-peak guard
* A/B preview with loudness matching, waveform + spectrogram, selection editing (trim/cut/silence/fade/gain/normalize/reverse), undo/redo
* Single-file Studio, Batch queue, saved user presets, drag & drop

## Developing / testing
```
pip install -r requirements.txt
python tests/test_dsp.py            # signal-processing checks (needs ffmpeg on PATH or bin/)
python main.py
```
Put `ffmpeg.exe` and `deep-filter.exe` in a `bin/` folder to run from source with everything enabled.
