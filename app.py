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
    """
    使用 ffmpeg 轉檔為 GIF，並試圖用較安全的參數避免崩潰。
    """
    if not FFMPEG_AVAILABLE:
        return False, None, "系統未安裝 ffmpeg，無法轉檔。"

    tmp_dir = tempfile.mkdtemp(prefix="gifconv_")
    input_path = os.path.join(tmp_dir, "input")
    if is_gif:
        input_path += ".gif"
    else:
        input_path += ".mp4"
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(input_data)

        scale_filter = f"scale={target_width}:-1:flags=lanczos"

        # 根據畫質模式設定 palettegen/paletteuse
        if dither == "none":
            dither_option = "dither=none"
        elif dither == "sierra2_4a":
            dither_option = "dither=sierra2_4a"
        else:
            dither_option = "dither=bayer"

        # 壓縮程度調整 palettegen 最大彩色數
        if compress == "保守":
            max_colors = 128
        elif compress == "強化":
            max_colors = 80
        elif compress == "激進":
            max_colors = 64
        else:
            max_colors = 96  # 平衡

        # 建立 palette 中繼檔
        palette_path = os.path.join(tmp_dir, "palette.png")
        cmd_palette = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-vf", f"{scale_filter},fps={fps},palettegen=max_colors={max_colors}",
            palette_path,
        ]
        ok, err = run_cmd(cmd_palette)
        if not ok:
            return False, None, f"建立調色盤失敗：\n{err}"

        # 使用 palette 把影片轉成 GIF
        cmd_gif = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-i", palette_path,
            "-lavfi", f"{scale_filter},fps={fps},paletteuse={dither_option}",
            "-loop", "0",
            output_path,
        ]
        ok, err = run_cmd(cmd_gif)
        if not ok:
            return False, None, f"轉檔 GIF 失敗：\n{err}"

        if not os.path.exists(output_path):
            return False, None, "轉檔後找不到 GIF 檔案。"

        with open(output_path, "rb") as f:
            gif_bytes = f.read()
        return True, gif_bytes, ""
    except Exception as e:
        return False, None, f"轉檔過程異常：{e}"
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

def reencode_gif(
    gif_bytes: bytes,
    fps: int,
    target_width: int,
    dither: str,
    compress: str,
) -> tuple[bool, bytes | None, str]:
    """
    使用 ffmpeg 重新壓縮已存在的 GIF（控制 FPS / 寬度 / palette）。
    """
    if not FFMPEG_AVAILABLE:
        return False, None, "系統未安裝 ffmpeg，無法轉檔。"

    tmp_dir = tempfile.mkdtemp(prefix="gifreenc_")
    input_path = os.path.join(tmp_dir, "input.gif")
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(gif_bytes)

        scale_filter = f"scale={target_width}:-1:flags=lanczos"

        if dither == "none":
            dither_option = "dither=none"
        elif dither == "sierra2_4a":
            dither_option = "dither=sierra2_4a"
        else:
            dither_option = "dither=bayer"

        if compress == "保守":
            max_colors = 128
        elif compress == "強化":
            max_colors = 80
        elif compress == "激進":
            max_colors = 64
        else:
            max_colors = 96

        palette_path = os.path.join(tmp_dir, "palette.png")
        cmd_palette = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-vf", f"{scale_filter},fps={fps},palettegen=max_colors={max_colors}",
            palette_path,
        ]
        ok, err = run_cmd(cmd_palette)
        if not ok:
            return False, None, f"GIF 建立調色盤失敗：\n{err}"

        cmd_gif = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-i", palette_path,
            "-lavfi", f"{scale_filter},fps={fps},paletteuse={dither_option}",
            "-loop", "0",
            output_path,
        ]
        ok, err = run_cmd(cmd_gif)
        if not ok:
            return False, None, f"GIF 重新編碼失敗：\n{err}"

        if not os.path.exists(output_path):
            return False, None, "GIF 重新編碼後找不到成品。"

        with open(output_path, "rb") as f:
            out_bytes = f.read()
        return True, out_bytes, ""
    except Exception as e:
        return False, None, f"GIF 重新編碼過程異常：{e}"
    finally:
        try:
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

# ==================== Streamlit 介面 ====================

st.set_page_config(page_title="GIF 轉檔工具", layout="wide")

# ---- 狀態 ----
if "global_settings" not in st.session_state:
    st.session_state["global_settings"] = {"fps": 10, "width": 800, "dither": "bayer", "compress": "平衡"}
if "video_settings" not in st.session_state:
    st.session_state["video_settings"] = {}
if "final_cache" not in st.session_state:
    st.session_state["final_cache"] = {}
if "zip_bytes" not in st.session_state:
    st.session_state["zip_bytes"] = None

def get_effective_settings(video_id: str) -> dict:
    global_settings = st.session_state["global_settings"]
    video_settings = st.session_state["video_settings"].get(video_id, {})
    return {
        "fps": video_settings.get("fps", global_settings["fps"]),
        "width": video_settings.get("width", global_settings["width"]),
        "dither": video_settings.get("dither", global_settings["dither"]),
        "compress": video_settings.get("compress", global_settings["compress"]),
    }

def update_video_setting(video_id: str, key: str, value):
    if "video_settings" not in st.session_state:
        st.session_state["video_settings"] = {}
    if video_id not in st.session_state["video_settings"]:
        st.session_state["video_settings"][video_id] = {}
    st.session_state["video_settings"][video_id][key] = value

def generate_video_id(file) -> str:
    if not file:
        return ""
    raw = f"{file.name}:{file.size}".encode("utf-8", errors="ignore")
    return hashlib.md5(raw).hexdigest()

def get_final_cache_key(video_id: str, fps: int, width: int, dither: str, compress: str) -> str:
    return f"final_{video_id}_{fps}_{width}_{dither}_{compress}"

st.title("GIF 轉檔工具")

if not FFMPEG_AVAILABLE:
    st.error("偵測不到 ffmpeg，請先在執行環境安裝 ffmpeg。")

col_left, col_right = st.columns([1.1, 1.9])

with col_left:
    st.subheader("上傳檔案")
    uploaded_files = st.file_uploader(
        "上傳影片或 GIF（可多個）",
        type=["mp4", "mov", "m4v", "gif"],
        accept_multiple_files=True,
        key="uploader",
    )

    selected_file = None
    selected_id = None

    if uploaded_files:
        names = [f.name for f in uploaded_files]
        choice = st.selectbox("選擇要轉檔的檔案", names)
        for f in uploaded_files:
            if f.name == choice:
                selected_file = f
                selected_id = generate_video_id(f)
                break

with col_right:
    if not uploaded_files:
        st.info("請先在左側上傳檔案。")
    elif not selected_file:
        st.info("請在左側選擇一個檔案。")
    else:
        eff = get_effective_settings(selected_id)
        ext = Path(selected_file.name).suffix.lower()
        is_gif = (ext == ".gif")

        st.subheader("轉檔設定")

        c1, c2 = st.columns(2)
        with c1:
            fps_val = st.slider("FPS", 1, 20, int(eff["fps"]), key=f"fps_{selected_id}")
            if fps_val != eff["fps"]:
                update_video_setting(selected_id, "fps", int(fps_val))

            width_val = st.number_input(
                "寬度（px）",
                min_value=100,
                max_value=1920,
                value=int(eff["width"]),
                step=2,
                key=f"width_{selected_id}",
            )
            # 強制偶數
            if width_val % 2 != 0:
                width_val = width_val - 1 if width_val > 100 else width_val + 1
            if int(width_val) != eff["width"]:
                update_video_setting(selected_id, "width", int(width_val))

        with c2:
            label_to_value = {"輕量模式": "none", "平衡模式": "bayer", "高品質模式": "sierra2_4a"}
            value_to_label = {
                "none": "輕量模式",
                "bayer": "平衡模式",
                "sierra2_4a": "高品質模式",
                "floyd_steinberg": "高品質模式",
                "sierra2": "高品質模式",
            }
            current_label = value_to_label.get(eff["dither"], "平衡模式")
            quality_label = st.selectbox(
                "畫質模式",
                ["輕量模式", "平衡模式", "高品質模式"],
                index=["輕量模式", "平衡模式", "高品質模式"].index(current_label),
                key=f"dither_{selected_id}",
            )
            dither_value = label_to_value[quality_label]
            if dither_value != eff["dither"]:
                update_video_setting(selected_id, "dither", dither_value)

            compress_val = st.selectbox(
                "壓縮程度",
                ["保守", "平衡", "強化", "激進"],
                index=["保守", "平衡", "強化", "激進"].index(eff["compress"]),
                key=f"compress_{selected_id}",
            )
            if compress_val != eff["compress"]:
                update_video_setting(selected_id, "compress", compress_val)

        # ✅ 重新取得最新設定，確保寬度 / FPS 都是使用者剛剛設的
        eff = get_effective_settings(selected_id)
        width_even = int(eff["width"]) if int(eff["width"]) % 2 == 0 else int(eff["width"]) - 1
        final_key = get_final_cache_key(selected_id, eff["fps"], width_even, eff["dither"], eff["compress"])

        # 自動依當前設定產生完整 GIF（若尚未在快取中）
        if final_key not in st.session_state["final_cache"]:
            data = selected_file.getvalue()
            if is_gif:
                ok, out_bytes, err_msg = reencode_gif(
                    data,
                    fps=eff["fps"],
                    target_width=width_even,
                    dither=eff["dither"],
                    compress=eff["compress"],
                )
            else:
                ok, out_bytes, err_msg = safe_convert(
                    data,
                    fps=eff["fps"],
                    target_width=width_even,
                    dither=eff["dither"],
                    compress=eff["compress"],
                    is_gif=False,
                )

            if not ok or not out_bytes:
                st.error(f"轉檔失敗：{err_msg}")
            else:
                st.session_state["final_cache"][final_key] = out_bytes

        if final_key in st.session_state["final_cache"]:
            gif_bytes = st.session_state["final_cache"][final_key]
            st.subheader("預覽")
            st.image(gif_bytes, use_column_width=True)
            st.caption(f"成品大小：{human_size(len(gif_bytes))}")

            st.download_button(
                "下載 GIF",
                data=gif_bytes,
                file_name=f"{Path(selected_file.name).stem}.gif",
                mime="image/gif",
                key=f"dl_{selected_id}",
            )

st.markdown("---")

# 批次 ZIP（選用）
uploaded_files = st.session_state.get("uploader")
if uploaded_files:
    if st.button("產生所有檔案的 GIF 並打包 ZIP"):
        with st.spinner("正在處理所有檔案..."):
            all_gifs = []
            for f in uploaded_files:
                vid = generate_video_id(f)
                eff = get_effective_settings(vid)
                width_even = int(eff["width"]) if int(eff["width"]) % 2 == 0 else int(eff["width"]) - 1
                final_key = get_final_cache_key(vid, eff["fps"], width_even, eff["dither"], eff["compress"])

                if final_key not in st.session_state["final_cache"]:
                    data = f.getvalue()
                    ext = Path(f.name).suffix.lower()
                    is_gif = (ext == ".gif")
                    if is_gif:
                        ok, out_bytes, err_msg = reencode_gif(
                            data,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            compress=eff["compress"],
                        )
                    else:
                        ok, out_bytes, err_msg = safe_convert(
                            data,
                            fps=eff["fps"],
                            target_width=width_even,
                            dither=eff["dither"],
                            compress=eff["compress"],
                            is_gif=False,
                        )
                    if not ok or not out_bytes:
                        st.error(f"{f.name} 轉檔失敗：{err_msg}")
                        continue
                    st.session_state["final_cache"][final_key] = out_bytes

                gif_bytes = st.session_state["final_cache"][final_key]
                all_gifs.append((f"{Path(f.name).stem}.gif", gif_bytes))

            if all_gifs:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for name, data in all_gifs:
                        zf.writestr(name, data)
                st.session_state["zip_bytes"] = buf.getvalue()
                st.success("ZIP 準備好了，可以下載。")

if st.session_state.get("zip_bytes"):
    st.download_button(
        "下載所有 GIF 的 ZIP 檔",
        data=st.session_state["zip_bytes"],
        file_name="gifs_bundle.zip",
        mime="application/zip",
        key="dl_zip",
    )
