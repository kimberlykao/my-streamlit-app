# app.py
# -*- coding: utf-8 -*-
import os
import io
import zipfile
import shutil
import tempfile
import subprocess
import hashlib
from pathlib import Path

import streamlit as st

# ===================== 公用工具 =====================

def human_size(num_bytes: int) -> str:
    try:
        num_bytes = float(num_bytes)
    except Exception:
        num_bytes = 0.0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"

def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def run_cmd(cmd: list) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
        if p.returncode == 0:
            return True, p.stdout
        else:
            return False, p.stderr
    except Exception as e:
        return False, str(e)

# ========== ffmpeg / gifsicle 指令查找 ==========

def find_ffmpeg() -> str:
    if command_exists("ffmpeg"):
        return "ffmpeg"
    return ""

def find_gifsicle() -> str:
    if command_exists("gifsicle"):
        return "gifsicle"
    return ""

FFMPEG_PATH = find_ffmpeg()
GIFSICLE_PATH = find_gifsicle()
FFMPEG_AVAILABLE = bool(FFMPEG_PATH)
GIFSICLE_AVAILABLE = bool(GIFSICLE_PATH)

# ==================== 轉檔邏輯 ====================

def safe_convert(
    input_data: bytes,
    fps: int,
    target_width: int,
    dither: str,
    compress: str,
    is_gif: bool,
) -> tuple[bool, bytes | None, str]:
    if not FFMPEG_AVAILABLE:
        return False, None, "系統未安裝 ffmpeg，無法轉檔。"

    tmp_dir = tempfile.mkdtemp(prefix="gifconv_")
    input_path = os.path.join(tmp_dir, "input")
    input_path += ".gif" if is_gif else ".mp4"
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(input_data)

        scale_filter = f"scale={target_width}:-1:flags=lanczos"

        dither_option = (
            "dither=none" if dither == "none"
            else "dither=sierra2_4a" if dither == "sierra2_4a"
            else "dither=bayer"
        )

        max_colors = (
            128 if compress == "保守"
            else 80 if compress == "強化"
            else 64 if compress == "激進"
            else 96
        )

        palette_path = os.path.join(tmp_dir, "palette.png")
        ok, err = run_cmd([
            FFMPEG_PATH, "-y", "-i", input_path,
            "-vf", f"{scale_filter},fps={fps},palettegen=max_colors={max_colors}",
            palette_path
        ])
        if not ok:
            return False, None, f"建立調色盤失敗：\n{err}"

        ok, err = run_cmd([
            FFMPEG_PATH, "-y",
            "-i", input_path, "-i", palette_path,
            "-lavfi", f"{scale_filter},fps={fps},paletteuse={dither_option}",
            "-loop", "0",
            output_path
        ])
        if not ok:
            return False, None, f"轉檔 GIF 失敗：\n{err}"

        with open(output_path, "rb") as f:
            return True, f.read(), ""

    except Exception as e:
        return False, None, str(e)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def reencode_gif(
    gif_bytes: bytes,
    fps: int,
    target_width: int,
    dither: str,
    compress: str,
) -> tuple[bool, bytes | None, str]:
    return safe_convert(gif_bytes, fps, target_width, dither, compress, True)

# ==================== Streamlit 狀態 ====================

st.set_page_config(page_title="GIF 轉檔工具", layout="wide")

if "global_settings" not in st.session_state:
    st.session_state["global_settings"] = {"fps": 10, "width": 800, "dither": "bayer", "compress": "平衡"}
if "video_settings" not in st.session_state:
    st.session_state["video_settings"] = {}
if "final_cache" not in st.session_state:
    st.session_state["final_cache"] = {}
if "zip_bytes" not in st.session_state:
    st.session_state["zip_bytes"] = None

def get_effective_settings(video_id: str) -> dict:
    g = st.session_state["global_settings"]
    v = st.session_state["video_settings"].get(video_id, {})
    return {
        "fps": v.get("fps", g["fps"]),
        "width": v.get("width", g["width"]),
        "dither": v.get("dither", g["dither"]),
        "compress": v.get("compress", g["compress"]),
    }

def update_video_setting(video_id: str, key: str, value):
    st.session_state["video_settings"].setdefault(video_id, {})[key] = value

def generate_video_id(file) -> str:
    raw = f"{file.name}:{file.size}".encode()
    return hashlib.md5(raw).hexdigest()

def apply_settings_to_all(source_id, files):
    source = get_effective_settings(source_id)
    for f in files:
        vid = generate_video_id(f)
        st.session_state["video_settings"][vid] = source.copy()

# ==================== UI ====================

st.title("GIF 轉檔工具")

col_left, col_right = st.columns([1.1, 1.9])

with col_left:
    uploaded_files = st.file_uploader(
        "上傳影片或 GIF（可多個）",
        type=["mp4", "mov", "m4v", "gif"],
        accept_multiple_files=True,
    )

    selected_file = None
    selected_id = None

    if uploaded_files:
        name = st.selectbox("選擇要轉檔的檔案", [f.name for f in uploaded_files])
        selected_file = next(f for f in uploaded_files if f.name == name)
        selected_id = generate_video_id(selected_file)

with col_right:
    if uploaded_files and selected_file:
        eff = get_effective_settings(selected_id)

        st.subheader("轉檔設定")

        # ⭐ 新增的一鍵套用按鈕（唯一 UI 變動）
        if st.button("一鍵套用目前設定到所有檔案"):
            apply_settings_to_all(selected_id, uploaded_files)
            st.success("已套用到所有檔案")

        c1, c2 = st.columns(2)
        with c1:
            fps = st.slider("FPS", 1, 20, eff["fps"])
            update_video_setting(selected_id, "fps", fps)

            width = st.number_input("寬度（px）", 100, 1920, eff["width"], step=2)
            width -= width % 2
            update_video_setting(selected_id, "width", width)

        with c2:
            dither = st.selectbox("畫質模式", ["none", "bayer", "sierra2_4a"], index=["none","bayer","sierra2_4a"].index(eff["dither"]))
            update_video_setting(selected_id, "dither", dither)

            compress = st.selectbox("壓縮程度", ["保守","平衡","強化","激進"], index=["保守","平衡","強化","激進"].index(eff["compress"]))
            update_video_setting(selected_id, "compress", compress)

        data = selected_file.getvalue()
        ok, gif_bytes, err = safe_convert(data, fps, width, dither, compress, selected_file.name.endswith(".gif"))
        if ok:
            st.image(gif_bytes)
            st.download_button("下載 GIF", gif_bytes, f"{Path(selected_file.name).stem}.gif", "image/gif")
