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

# ===================== 工具函式 =====================

def human_size(num_bytes: int) -> str:
    if num_bytes < 1024.0:
        return f"{num_bytes:.2f} B"
    num_bytes /= 1024.0
    if num_bytes < 1024.0:
        return f"{num_bytes:.2f} KB"
    num_bytes /= 1024.0
    return f"{num_bytes:.2f} MB"

def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def run_cmd(cmd: list) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, text=True)
        return (p.returncode == 0, p.stdout if p.returncode == 0 else p.stderr)
    except Exception as e:
        return False, str(e)

FFMPEG_PATH = "ffmpeg" if command_exists("ffmpeg") else ""

# ==================== 核心轉檔邏輯 ====================

def convert_to_gif(input_data, settings, filename):
    if not FFMPEG_PATH:
        return False, None, "系統未安裝 ffmpeg"

    tmp_dir = tempfile.mkdtemp(prefix="gif_")
    input_path = os.path.join(tmp_dir, "in_" + filename)
    palette_path = os.path.join(tmp_dir, "palette.png")
    output_path = os.path.join(tmp_dir, "out.gif")

    try:
        with open(input_path, "wb") as f:
            f.write(input_data)

        # 根據白話選項轉換為技術參數
        fps = settings['fps']
        width = settings['width']
        
        # 畫質風格對應
        style = settings['style']
        if style == "細膩 (檔案大)":
            dither = "sierra2_4a"
            colors = 256
        elif style == "標準 (推薦)":
            dither = "bayer"
            colors = 128
        else: # 復古 (小體積)
            dither = "none"
            colors = 64

        # 1. 生成調色盤
        cmd_palette = [
            FFMPEG_PATH, "-y", "-i", input_path,
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen=max_colors={colors}",
            palette_path
        ]
        run_cmd(cmd_palette)

        # 2. 轉檔
        cmd_conv = [
            FFMPEG_PATH, "-y", "-i", input_path, "-i", palette_path,
            "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither={dither}",
            output_path
        ]
        ok, err = run_cmd(cmd_conv)
        
        if ok:
            with open(output_path, "rb") as f:
                return True, f.read(), ""
        return False, None, err
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ==================== Streamlit 介面 ====================

st.set_page_config(page_title="GIF 4MB 批次轉檔工具", layout="wide")

# 初始化狀態
if "files_data" not in st.session_state:
    st.session_state["files_data"] = {} # {file_id: {settings, result_bytes}}
if "global_config" not in st.session_state:
    st.session_state["global_config"] = {"fps": 10, "width": 480, "style": "標準 (推薦)"}

st.title("🎬 GIF 批次壓縮轉檔 ")

# --- 第一層：上傳與懶人包 ---
col_up, col_preset = st.columns([1, 1])

with col_up:
    uploaded_files = st.file_uploader("1. 上傳影片", type=["mp4", "mov", "m4v", "gif"], accept_multiple_files=True)

with col_preset:
    st.write("2. 快速設定 (一鍵套用全部)")
    p1, p2, p3 = st.columns(3)
    if p1.button("✅ 安全標準包\n(480px / 10FPS)"):
        st.session_state["global_config"] = {"fps": 10, "width": 480, "style": "標準 (推薦)"}
        for fid in st.session_state["files_data"]:
            st.session_state["files_data"][fid]['settings'] = st.session_state["global_config"].copy()
        st.rerun()
    if p2.button("🎈 極度輕巧包\n(320px / 8FPS)"):
        st.session_state["global_config"] = {"fps": 8, "width": 320, "style": "復古 (小體積)"}
        for fid in st.session_state["files_data"]:
            st.session_state["files_data"][fid]['settings'] = st.session_state["global_config"].copy()
        st.rerun()
    if p3.button("💎 高畫質包\n(640px / 12FPS)"):
        st.session_state["global_config"] = {"fps": 12, "width": 640, "style": "細膩 (檔案大)"}
        for fid in st.session_state["files_data"]:
            st.session_state["files_data"][fid]['settings'] = st.session_state["global_config"].copy()
        st.rerun()

st.divider()

# --- 第二層：批次管理與轉檔 ---
if uploaded_files:
    st.subheader("3. 檔案清單與進度")
    
    # 初始化上傳的檔案
    for f in uploaded_files:
        fid = hashlib.md5(f.name.encode()).hexdigest()
        if fid not in st.session_state["files_data"]:
            st.session_state["files_data"][fid] = {
                "name": f.name,
                "content": f.getvalue(),
                "settings": st.session_state["global_config"].copy(),
                "result": None
            }

    # 批次轉檔按鈕
    if st.button("🚀 開始批次轉檔", type="primary"):
        progress_bar = st.progress(0)
        for i, (fid, info) in enumerate(st.session_state["files_data"].items()):
            ok, res, err = convert_to_gif(info["content"], info["settings"], info["name"])
            if ok:
                st.session_state["files_data"][fid]["result"] = res
            progress_bar.progress((i + 1) / len(st.session_state["files_data"]))
        st.success("全部處理完成！")

    # 列表顯示
    for fid, info in st.session_state["files_data"].items():
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        c1.write(f"📄 {info['name']}")
        
        # 體積監控
        if info["result"]:
            size = len(info["result"])
            size_str = human_size(size)
            if size > 4 * 1024 * 1024:
                c2.markdown(f"🔴 **{size_str} (超過 4MB)**")
            else:
                c2.markdown(f"🟢 {size_str}")
        else:
            c2.write("等待轉檔...")

        if c4.button("微調", key=f"edit_{fid}"):
            st.session_state["editing_now"] = fid

    # 下載全部 ZIP
    ready_files = {info['name']: info['result'] for info in st.session_state["files_data"].values() if info['result']}
    if ready_files:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for name, data in ready_files.items():
                zf.writestr(Path(name).stem + ".gif", data)
        st.download_button("📦 一鍵打包下載全部 GIF", zip_buffer.getvalue(), "all_gifs.zip", "application/zip")

    # --- 第三層：個別微調區 ---
    if "editing_now" in st.session_state:
        fid = st.session_state["editing_now"]
        info = st.session_state["files_data"][fid]
        st.divider()
        st.subheader(f"🛠 正在微調: {info['name']}")
        
        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            new_fps = st.slider("畫面流暢度 (FPS)", 1, 30, info['settings']['fps'], key=f"fps_{fid}")
        with mc2:
            new_width = st.number_input("寬度 (px)", 100, 1200, info['settings']['width'], step=10, key=f"w_{fid}")
        with mc3:
            new_style = st.selectbox("畫質風格", ["細膩 (檔案大)", "標準 (推薦)", "復古 (小體積)"], 
                                   index=["細膩 (檔案大)", "標準 (推薦)", "復古 (小體積)"].index(info['settings']['style']), key=f"s_{fid}")
        
        if st.button("套用並單獨預覽"):
            info['settings'] = {"fps": new_fps, "width": new_width, "style": new_style}
            ok, res, err = convert_to_gif(info["content"], info['settings'], info['name'])
            if ok:
                info["result"] = res
                st.image(res, caption=f"預覽: {human_size(len(res))}")
            else:
                st.error(err)
else:
    st.info("請先上傳影片，開始你的 GIF 製作旅程。")
